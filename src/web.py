"""Loopback-only web workbench using the existing probes, agent and reports."""

import copy
import json
import math
import mimetypes
import os
import platform
import threading
import urllib.request
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .agent import ROOT, diagnose
from .evaluation import evaluate_cases
from .lab import laboratory, load_cases
from .report import save
from .tools import Probes, parse_target


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_json(path):
    if path.stat().st_size > 20_000_000:
        raise ValueError("文件过大，请直接在本机查看")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ollama_host(value):
    if not isinstance(value, str):
        raise ValueError("Ollama 地址必须是本机 HTTP 地址")
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or not (1 <= (parsed.port or 11434) <= 65535)):
        raise ValueError("Ollama 地址仅支持本机，例如 http://127.0.0.1:11434")
    if parsed.port == 0:
        raise ValueError("Ollama 端口不能为 0")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{parsed.port if parsed.port is not None else 11434}"


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} 必须在 {low} 到 {high} 之间")
    return value


def validate_job(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象")
    kind = payload.get("kind", "diagnose")
    engine = payload.get("engine", "ollama")
    mode = payload.get("mode", "skill")
    if kind not in ("diagnose", "demo", "evaluate") or engine not in ("ollama", "rules") or mode not in ("baseline", "tools", "skill"):
        raise ValueError("不支持的任务、引擎或调查模式")
    if engine == "rules" and mode == "baseline":
        raise ValueError("规则测试不支持直接分析模式")
    model = payload.get("model", os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b"))
    if not isinstance(model, str) or not model.strip() or len(model) > 160:
        raise ValueError("请选择有效模型")
    options = {"kind": kind, "engine": engine, "mode": mode, "model": model.strip(),
               "host": ollama_host(payload.get("host", os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))),
               "timeout": number(payload.get("timeout", 3), "探测超时", 0.1, 30),
               "slow_ms": number(payload.get("slow_ms", 800), "慢响应阈值", 1, 60000)}
    case_ids = [case["id"] for case in load_cases()]
    if kind == "diagnose":
        url = payload.get("url", "")
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError("请输入有效网址")
        options["url"] = parse_target(url.strip())["url"]
    elif kind == "demo":
        if payload.get("case_id") not in case_ids:
            raise ValueError("请选择有效故障案例")
        options["case_id"] = payload["case_id"]
    else:
        selected = payload.get("cases", case_ids)
        modes = payload.get("modes", ["baseline", "tools", "skill"])
        repeats = payload.get("repeats", 1)
        if not isinstance(selected, list) or not selected or any(item not in case_ids for item in selected):
            raise ValueError("至少选择一个有效案例")
        if not isinstance(modes, list) or not modes or any(item not in ("baseline", "tools", "skill") for item in modes):
            raise ValueError("至少选择一个有效实验组")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= 5:
            raise ValueError("重复次数须为 1 到 5 的整数")
        options.update(cases=list(dict.fromkeys(selected)),
                       modes=["skill"] if engine == "rules" else list(dict.fromkeys(modes)), repeats=repeats)
    return options


class JobCancelled(RuntimeError):
    pass


class Workbench:
    def __init__(self, output=None):
        self.output = Path(output or ROOT / "results").resolve()
        self.web_output = self.output / "web"
        self.web_output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.cancellations = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diagnosis")
        for path in self.web_output.glob("*/job.json"):
            try:
                job = read_json(path)
                if not isinstance(job, dict) or not isinstance(job.get("created_at"), str) or job.get("id") != path.parent.name:
                    continue
                if job.get("status") in ("queued", "running", "cancelling"):
                    job.update(status="interrupted", error="服务已重新启动，请重新运行此任务。")
                if isinstance(job.get("id"), str):
                    self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError):
                continue

    def _persist(self, job):
        directory = self.web_output / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "job.json.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "job.json")

    def submit(self, payload):
        options = validate_job(payload)
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        job = {"id": identifier, "status": "queued", "created_at": now(), "options": options,
               "events": [], "report_paths": [], "evaluation_path": None}
        with self.lock:
            if sum(item["status"] in ("queued", "running", "cancelling") for item in self.jobs.values()) >= 10:
                raise ValueError("等待任务较多，请稍后再试")
            self.jobs[identifier] = job
            self.cancellations[identifier] = threading.Event()
            self._persist(job)
        self.executor.submit(self._run, identifier)
        return self.get_job(identifier)

    def get_job(self, identifier):
        with self.lock:
            if identifier not in self.jobs:
                raise FileNotFoundError("任务不存在")
            return copy.deepcopy(self.jobs[identifier])

    def list_jobs(self):
        with self.lock:
            return [{key: copy.deepcopy(value) for key, value in job.items() if key != "events"}
                    for job in sorted(self.jobs.values(), key=lambda item: item["created_at"], reverse=True)[:100]]

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job:
                raise FileNotFoundError("任务不存在")
            if job["status"] in ("queued", "running", "cancelling"):
                self.cancellations[identifier].set()
                job["status"] = "cancelling"
                self._persist(job)
        return self.get_job(identifier)

    def _event(self, identifier, event):
        cancelled = self.cancellations[identifier]
        if cancelled.is_set() and event.get("type") not in ("tool", "model_finished", "diagnosis_finished"):
            raise JobCancelled("已停止后续步骤；已取得的观测保留在任务记录中。")
        with self.lock:
            job = self.jobs[identifier]
            job["events"].append({"at": now(), **event})
            job["events"] = job["events"][-600:]
            self._persist(job)
        if cancelled.is_set():
            raise JobCancelled("已停止后续步骤；已取得的观测保留在任务记录中。")

    def _run(self, identifier):
        with self.lock:
            job = self.jobs[identifier]
            options = job["options"]
            job.update(status="running", started_at=now())
            self._persist(job)
        output = self.web_output / identifier
        callback = lambda event: self._event(identifier, event)
        try:
            callback({"type": "started", "message": "任务已开始"})
            shared = {key: options[key] for key in ("engine", "model", "host")}
            if options["kind"] == "evaluate":
                cases = [case for case in load_cases() if case["id"] in options["cases"]]
                evaluation = evaluate_cases(cases, output, modes=options["modes"], repeats=options["repeats"],
                                            on_event=callback, **shared)
                callback({"type": "evaluation_finished", "summary": evaluation["summary"]})
                with self.lock:
                    job["evaluation_path"] = str((output / "summary.json").relative_to(self.output)).replace("\\", "/")
                    job["report_paths"] = [str(path.relative_to(self.output)).replace("\\", "/") for path in sorted((output / "traces").glob("*.json"))]
                failed = any(row["error"] for row in evaluation["rows"])
            else:
                if options["kind"] == "demo":
                    case = next(case for case in load_cases() if case["id"] == options["case_id"])
                    with laboratory(case) as provider:
                        result = diagnose(provider, mode=options["mode"], on_event=callback,
                                          incident=case.get("incident"), **shared)
                    result["laboratory"] = {"case_id": case["id"], "expected": case["expected"], "source": case["source"]}
                else:
                    result = diagnose(Probes(options["url"], options["timeout"], options["slow_ms"]),
                                      mode=options["mode"], on_event=callback, **shared)
                callback({"type": "saving", "message": "正在保存报告"})
                path, _ = save(result, output)
                with self.lock:
                    job["report_paths"] = [str(path.relative_to(self.output)).replace("\\", "/")]
                    job["error"] = result.get("error")
                failed = result.get("final") is None
            with self.lock:
                job["status"] = "failed" if failed else "completed"
                if failed and not job.get("error"):
                    job["error"] = "部分模型执行未成功，已保留实际观测和完整记录。"
        except JobCancelled as error:
            with self.lock:
                job.update(status="cancelled", error=str(error))
        except Exception as error:
            with self.lock:
                job.update(status="failed", error=str(error))
        finally:
            with self.lock:
                job["finished_at"] = now()
                self._persist(job)

    def file(self, relative, suffixes=(".json", ".md", ".csv")):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("无效的报告路径")
        path = (self.output / relative).resolve()
        if not path.is_relative_to(self.output) or path.suffix not in suffixes:
            raise ValueError("仅可读取结果目录中的报告")
        if not path.is_file():
            raise FileNotFoundError("报告文件不存在")
        return path

    def reports(self):
        rows = []
        for path in self.output.rglob("*.json"):
            if path.name in ("job.json", "summary.json", "run-manifest.json"):
                continue
            try:
                result = read_json(path)
                if not isinstance(result, dict) or not isinstance(result.get("target"), dict) or "engine" not in result:
                    continue
                final = result.get("final") or {}
                rows.append({"path": str(path.relative_to(self.output)).replace("\\", "/"),
                             "url": result["target"].get("url", ""), "engine": result.get("engine"),
                             "mode": result.get("mode"), "model": result.get("model"),
                             "diagnosis": final.get("diagnosis", "execution_error"),
                             "started_at": result.get("started_at", ""), "elapsed_seconds": result.get("elapsed_seconds"),
                             "case_id": (result.get("laboratory") or result.get("evaluation") or {}).get("case_id"),
                             "replayed": bool((result.get("evaluation") or {}).get("observations_replayed")),
                             "narrative_repair_used": bool(result.get("narrative_repair_used"))})
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return sorted(rows, key=lambda row: row["started_at"], reverse=True)

    def evaluations(self):
        rows = []
        for path in self.output.rglob("summary.json"):
            try:
                report = read_json(path)
                if isinstance(report, dict) and isinstance(report.get("summary"), list) and "rows" in report:
                    rows.append({"path": str(path.relative_to(self.output)).replace("\\", "/"),
                                 "engine": report.get("engine"), "model": report.get("model"),
                                 "summary": report["summary"], "repeats": report.get("repeats"),
                                 "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
            except (OSError, ValueError, TypeError):
                continue
        return sorted(rows, key=lambda row: row["modified_at"], reverse=True)

    def close(self):
        with self.lock:
            for flag in self.cancellations.values():
                flag.set()
        self.executor.shutdown(wait=True, cancel_futures=False)


def health(host):
    base = {"python": platform.python_version(), "output": str(ROOT / "results"),
            "default_model": os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b"), "host": host}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(host + "/api/tags", timeout=3) as response:
            payload = json.load(response)
        base.update(connected=True, models=[item["name"] for item in payload.get("models", [])])
    except (OSError, ValueError, KeyError) as error:
        base.update(connected=False, models=[], error="无法连接 Ollama。请启动 Ollama，或使用规则工具测试。", detail=str(error))
    return base


def create_server(port=8765, state=None, static_directory=None):
    state = state or Workbench()
    static_directory = Path(static_directory or ROOT / "frontend" / "dist").resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, content, status=200, content_type="application/json; charset=utf-8", filename=None):
            if not isinstance(content, bytes):
                content = json.dumps(content, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
            self.end_headers()
            self.wfile.write(content)

        def _allowed(self):
            port_number = self.server.server_port
            allowed = {f"127.0.0.1:{port_number}", f"localhost:{port_number}"}
            if self.headers.get("Host") not in allowed:
                self._send({"error": "仅允许本机访问"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + item for item in allowed}:
                self._send({"error": "请求来源不匹配"}, 403)
                return False
            return True

        def do_GET(self):
            if not self._allowed():
                return
            try:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                path = parsed.path
                if path == "/api/bootstrap":
                    return self._send({"cases": load_cases(), "default_model": os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b"),
                                       "default_host": os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"), "output": str(state.output)})
                if path == "/api/health":
                    return self._send(health(ollama_host(query.get("host", [os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")])[0])))
                if path == "/api/jobs":
                    return self._send({"jobs": state.list_jobs()})
                if path.startswith("/api/jobs/"):
                    return self._send(state.get_job(path.removeprefix("/api/jobs/")))
                if path == "/api/reports":
                    return self._send({"reports": state.reports()})
                if path == "/api/evaluations":
                    return self._send({"evaluations": state.evaluations()})
                if path in ("/api/report", "/api/evaluation", "/api/download"):
                    relative = query.get("path", [""])[0]
                    file_path = state.file(relative)
                    if path == "/api/download":
                        format_name = query.get("format", ["json"])[0]
                        if format_name not in ("json", "md", "csv"):
                            raise ValueError("不支持的下载格式")
                        file_path = state.file(str(file_path.with_suffix("." + format_name).relative_to(state.output)).replace("\\", "/"))
                        return self._send(file_path.read_bytes(), content_type="application/octet-stream", filename=file_path.name)
                    result = read_json(file_path)
                    if path == "/api/report" and (not isinstance(result, dict) or "engine" not in result or "target" not in result):
                        raise ValueError("该文件不是诊断报告")
                    return self._send(result)
                if path.startswith("/api/"):
                    raise FileNotFoundError("接口不存在")
                asset = (static_directory / unquote(path).lstrip("/")).resolve()
                if not asset.is_relative_to(static_directory):
                    raise ValueError("无效资源路径")
                if path == "/" or not asset.suffix:
                    asset = static_directory / "index.html"
                if not asset.is_file():
                    raise FileNotFoundError("前端资源尚未构建；开发者请在 frontend 中执行构建。")
                mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(asset.suffix,
                        mimetypes.guess_type(str(asset))[0] or "application/octet-stream")
                return self._send(asset.read_bytes(), content_type=mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
            except FileNotFoundError as error:
                self._send({"error": str(error)}, 404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (ValueError, TypeError, OSError) as error:
                self._send({"error": str(error)}, 400)

        def do_POST(self):
            if not self._allowed():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536 or not self.headers.get("Content-Type", "").startswith("application/json"):
                    raise ValueError("请输入不超过 64KB 的 JSON 请求")
                def invalid_constant(_):
                    raise ValueError("JSON 数值无效")
                payload = json.loads(self.rfile.read(length), parse_constant=invalid_constant)
                path = urlsplit(self.path).path
                if path == "/api/jobs":
                    return self._send(state.submit(payload), 202)
                if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                    return self._send(state.cancel(path[len("/api/jobs/"):-len("/cancel")]))
                raise FileNotFoundError("接口不存在")
            except FileNotFoundError as error:
                self._send({"error": str(error)}, 404)
            except (ValueError, TypeError, OSError) as error:
                self._send({"error": str(error)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.workbench = state
    return server


def serve(port=8765, open_browser=False):
    server = create_server(port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"\n网站诊断工作台：{url}\n仅在本机运行。按 Ctrl+C 关闭。", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止任务并关闭工作台…", flush=True)
    finally:
        server.server_close()
        server.workbench.close()
