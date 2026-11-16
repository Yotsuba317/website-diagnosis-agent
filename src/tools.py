"""Read-only DNS, TCP and HTTP(S) probes bound to one user-specified target."""

import copy
import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit


TOOL_DESCRIPTIONS = {
    "check_dns": "Check this target's DNS resolution. Call this first. No arguments. Reports IP addresses or a DNS error.",
    "check_tcp": "After check_dns succeeds, test the target TCP port. No arguments. A failed connection alone cannot prove a firewall blocked it.",
    "check_http": "After check_dns and check_tcp succeed, check TLS and HTTP response headers and response wait time. No arguments. Reports certificate/protocol errors, HTTP errors or slow responses.",
}
TOOL_SCHEMAS = [{"type": "function", "function": {
    "name": name, "description": description,
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}} for name, description in TOOL_DESCRIPTIONS.items()]
TOOL_PREREQUISITES = {
    "check_tcp": ("check_dns",),
    "check_http": ("check_dns", "check_tcp"),
}


def prerequisite_error(name, observations):
    """Apply the same successful-stage requirements to live and replay calls."""
    for required in TOOL_PREREQUISITES.get(name, ()):
        status = observations.get(required, {}).get("status")
        if status != "ok":
            return {"status": "not_ready", "required_tool": required,
                    "required_status": status or "missing"}
    return None


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_target(url):
    if any(ord(char) < 32 for char in url):
        raise ValueError("网址不能包含控制字符")
    if "://" not in url:
        url = "https://" + url
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("请输入有效的 http:// 或 https:// 网址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("请勿在网址中包含用户名和密码")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("端口必须为 1 到 65535") from error
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("端口必须为 1 到 65535")
    path = parsed.path or "/"
    path = path + ("?" + parsed.query if parsed.query else "")
    try:
        path.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("网址路径中的中文请先使用 URL 编码") from error
    return {"url": parsed._replace(fragment="").geturl(), "host": parsed.hostname.encode("idna").decode(),
            "port": port, "scheme": parsed.scheme, "path": path}


class Probes:
    def __init__(self, url, timeout=3.0, slow_ms=800.0):
        self.target = parse_target(url)
        self.timeout, self.slow_ms = timeout, slow_ms
        self.cache = {}
        self.connected_ip = None

    def call(self, name):
        if name not in TOOL_DESCRIPTIONS:
            raise ValueError("未知工具")
        if name in self.cache:
            return copy.deepcopy(self.cache[name])
        blocked = prerequisite_error(name, self.cache)
        if blocked:
            return blocked
        result = getattr(self, name)()
        result.update(tool=name, observed_at=utc_now(), source="live_probe",
                      vantage_point="machine running this program; direct connection; no proxy")
        self.cache[name] = result
        return copy.deepcopy(result)

    def check_dns(self):
        target = self.target
        started = time.perf_counter()
        try:
            address = str(ipaddress.ip_address(target["host"]))
            return {"status": "ok", "addresses": [address], "ip_literal": True, "elapsed_ms": 0.0}
        except ValueError:
            pass
        answers = queue.Queue()

        def resolve():
            try:
                answers.put((True, socket.getaddrinfo(target["host"], target["port"], type=socket.SOCK_STREAM)))
            except OSError as error:
                answers.put((False, str(error)))

        threading.Thread(target=resolve, daemon=True).start()
        try:
            success, answer = answers.get(timeout=self.timeout)
        except queue.Empty:
            return {"status": "error", "error_type": "dns_timeout", "elapsed_ms": self.timeout * 1000}
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        if not success:
            return {"status": "error", "error_type": "dns_resolution_failed", "detail": answer, "elapsed_ms": elapsed}
        addresses = list(dict.fromkeys(record[4][0] for record in answer))
        return {"status": "ok", "addresses": addresses, "ip_literal": False, "elapsed_ms": elapsed}

    def check_tcp(self):
        dns = self.cache["check_dns"]
        if dns["status"] != "ok":
            return {"status": "skipped", "reason": "DNS did not supply a usable address"}
        attempts = []
        for address in dns["addresses"][:3]:
            started = time.perf_counter()
            try:
                with socket.create_connection((address, self.target["port"]), timeout=self.timeout):
                    pass
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                self.connected_ip = address
                return {"status": "ok", "address": address, "port": self.target["port"],
                        "elapsed_ms": elapsed, "previous_attempts": attempts}
            except OSError as error:
                attempts.append({"address": address, "error_type": type(error).__name__,
                                 "detail": str(error), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
        return {"status": "error", "error_type": "tcp_connection_failed", "attempts": attempts}

    def check_http(self):
        if self.cache["check_tcp"]["status"] != "ok":
            return {"status": "skipped", "reason": "TCP connection did not succeed"}
        target = self.target
        sock = None
        stage = "tcp"
        started = time.perf_counter()
        try:
            sock = socket.create_connection((self.connected_ip, target["port"]), timeout=self.timeout)
            connect_ms = (time.perf_counter() - started) * 1000
            tls_ms = 0.0
            if target["scheme"] == "https":
                stage = "tls"
                tls_started = time.perf_counter()
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=target["host"])
                tls_ms = (time.perf_counter() - tls_started) * 1000
            stage = "http"
            host_header = target["host"]
            if ":" in host_header:
                host_header = "[" + host_header + "]"
            host_header += ":" + str(target["port"])
            request = (f"GET {target['path']} HTTP/1.1\r\nHost: {host_header}\r\n"
                       "User-Agent: CourseWebsiteDiagnosis/0.1\r\nConnection: close\r\n\r\n")
            wait_started = time.perf_counter()
            sock.sendall(request.encode("ascii"))
            response = http.client.HTTPResponse(sock)
            response.begin()
            wait_ms = (time.perf_counter() - wait_started) * 1000
            status = response.status
            result = {"status": "ok", "http_status": status, "tcp_connect_ms": round(connect_ms, 2),
                      "scheme": target["scheme"], "tls_checked": target["scheme"] == "https",
                      "http_error": 400 <= status <= 599,
                      "tls_ms": round(tls_ms, 2), "response_wait_ms": round(wait_ms, 2),
                      "total_ms": round((time.perf_counter() - started) * 1000, 2),
                      "slow_threshold_ms": self.slow_ms, "slow": wait_ms >= self.slow_ms,
                      "body_checked": False, "redirect_followed": False}
            response.close()
            return result
        except ssl.SSLError as error:
            return {"status": "error", "error_type": "tls_error", "stage": stage, "detail": str(error)}
        except (OSError, http.client.HTTPException) as error:
            return {"status": "error", "error_type": "request_failed", "stage": stage,
                    "detail": str(error), "total_ms": round((time.perf_counter() - started) * 1000, 2)}
        finally:
            if sock is not None:
                sock.close()


class RecordedProbes:
    """Replay identical raw observations for fair, repeatable A/B/C comparisons."""
    def __init__(self, target, records):
        self.target = target
        self.records = copy.deepcopy(records)
        self.cache = {}

    def call(self, name):
        if name not in TOOL_DESCRIPTIONS:
            raise ValueError("未知工具")
        if name in self.cache:
            return copy.deepcopy(self.cache[name])
        blocked = prerequisite_error(name, self.cache)
        if blocked:
            return blocked
        result = copy.deepcopy(self.records.get(name, {
            "status": "unavailable", "tool": name, "source": "recorded_fixture"}))
        self.cache[name] = result
        return copy.deepcopy(result)


def collect_observations(provider):
    records = {}
    for name in TOOL_DESCRIPTIONS:
        result = provider.call(name)
        records[name] = result
        if result["status"] != "ok":
            break
    return records
