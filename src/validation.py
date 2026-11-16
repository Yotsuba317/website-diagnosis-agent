"""Bounded checks for known narrative errors; not a general semantic verifier."""

import re


class NarrativeError(ValueError):
    """A parseable draft contains a known narrative contradiction."""


SUMMARY_TEMPLATES = {
    "normal": "本次基础访问检查正常。",
    "dns_failure": "当前目标的 DNS 解析失败。",
    "tcp_failure": "已获得目标地址，但目标端口连接失败。",
    "tls_failure": "TCP 可连接，但 TLS 握手或证书验证失败。",
    "http_error": "目标已返回 HTTP 错误响应。",
    "slow_response": "本次响应等待超过配置阈值。",
    "insufficient_evidence": "现有检查不足以确定结果，请补充缺失观测。",
}
TIMING_NUMBER = re.compile(
    r"\d+(?:\.\d+)?\s*(?:毫秒|秒|milliseconds?\b|seconds?\b|ms\b|s\b)"
    r"|\d+(?:\.\d+)?\s*(?:[<>≤≥=]|不?大于|不?小于|超过|低于)\s*\d", re.I)
SLOW_CLAIM = re.compile(
    r"slow_response|slow response|响应.{0,8}(?:偏慢|缓慢|过慢|慢|延迟|超时|超过阈值)"
    r"|慢响应|(?:等待|耗时).{0,8}(?:偏长|过长|较长|超.{0,4}阈值)", re.I)
TLS_TIMING_CLAIM = re.compile(
    r"(?:TLS|握手).{0,24}(?:偏慢|缓慢|过慢|偏长|过长|较长|超时|慢响应)", re.I)
QUALIFIED = re.compile(r"若|如果|假如|是否|不能|无法|尚未|未发现|未见|没有|不慢|未超|未达到|不超过|不高于", re.I)
TLS_WORD = re.compile(r"TLS|证书|握手|certificate", re.I)
DISRUPTIVE_ADVICE = re.compile(r"重启|重新部署|重装|关闭.{0,8}(?:证书|防火墙)|禁用.{0,8}(?:证书|防火墙)")


def suggests_disruptive_action(text):
    for clause in re.split(r"[。；;，,]", text):
        for match in DISRUPTIVE_ADVICE.finditer(clause):
            if not re.search(r"(?:不要|不得|禁止|避免|无需|无须|不能|勿|不通过|不应).{0,8}$", clause[:match.start()]):
                return True
    return False


def summary_choices(evidence):
    choices = dict(SUMMARY_TEMPLATES)
    http = next((item for item in evidence if item["tool"] == "check_http"), {})
    if http.get("status") == "ok":
        code = http.get("http_status", 0)
        if 400 <= code <= 599:
            choices["http_error"] = f"目标已返回 HTTP {code} 错误响应。"
        elif not 200 <= code <= 299:
            choices["insufficient_evidence"] = "目标返回重定向或其他状态，本次未追踪后续访问。"
    return choices


def repair_text_choices(evidence, compatible, program):
    """Explicit program-supplied candidates, used only after narrative rejection."""
    records = {item["tool"]: item for item in evidence}
    dns, tcp, http = (records.get(name, {}) for name in ("check_dns", "check_tcp", "check_http"))
    excluded = []
    unknown = list(program["uncertainties"])
    if dns.get("status") == "ok" and not dns.get("ip_literal"):
        excluded.append("本次域名解析成功，不支持完全解析失败。")
    if dns.get("ip_literal"):
        unknown.append("输入为 IP，本次未验证 DNS 解析服务。")
    if tcp.get("status") == "ok":
        excluded.append("本次 TCP 连接成功，不支持端口完全不可达。")
    if http.get("status") == "ok":
        if http.get("tls_checked"):
            excluded.append("本次 TLS 握手和证书校验已通过。")
        if 200 <= http.get("http_status", 0) <= 299:
            excluded.append("本次已获得成功的 HTTP 响应，不支持 HTTP 错误响应。")
        if http.get("slow") is False:
            excluded.append("本次响应等待未达到慢响应阈值。")
    else:
        unknown.append("缺少完整 HTTP 响应，尚不能验证服务状态和响应等待情况。")
    if http.get("tls_checked") is not True:
        unknown.append("本次未完成 TLS 握手和证书校验。")
    summaries = summary_choices(evidence)
    # An abstention must not replace an already observed failure/success stage
    # during the explicitly program-assisted repair step.
    compatible = [name for name in compatible if name != "insufficient_evidence"] or ["insufficient_evidence"]
    return {"supported_hypotheses": [summaries[name] for name in compatible],
            "rejected_hypotheses": excluded, "uncertainties": unknown,
            "recommendations": list(program["recommendations"])}


def check_repair_selection(final, choices):
    if final["summary"] not in choices["supported_hypotheses"]:
        raise NarrativeError("文字修正阶段已有明确阶段观测，diagnosis 和 summary 必须匹配该阶段候选。")
    for field, allowed in choices.items():
        if any(value not in allowed for value in final[field]):
            raise NarrativeError(f"文字修正阶段 {field} 必须逐字选用程序提供的候选。")
    if not final["recommendations"]:
        raise NarrativeError("文字修正阶段 recommendations 至少选择一项。")


def check_narrative(final, evidence):
    """Reject a draft rather than silently rewriting it into a successful answer."""
    records = {item["tool"]: item for item in evidence}
    dns, http = (records.get(name, {}) for name in ("check_dns", "check_http"))
    expected_summary = summary_choices(evidence)[final["diagnosis"]]
    if final["summary"] != expected_summary:
        raise NarrativeError("summary 必须逐字使用当前 diagnosis 对应的短句：" + expected_summary)

    for field in ("supported_hypotheses", "rejected_hypotheses", "uncertainties", "recommendations"):
        for value in final[field]:
            if TIMING_NUMBER.search(value):
                raise NarrativeError(f"{field} 不得重述耗时数值或进行数值比较；数值由程序直接展示。")

    # Assertions and exclusions have opposite polarity. Questions, conditional
    # follow-up checks and explicit uncertainty must not be treated as diagnoses.
    for value in final["supported_hypotheses"]:
        for clause in re.split(r"[。；;，,]", value):
            if QUALIFIED.search(clause):
                continue
            if re.search(r"(?:DNS|域名解析).{0,8}(?:正常|成功|通过|无异常)", clause, re.I):
                if dns.get("status") != "ok" or dns.get("ip_literal"):
                    raise NarrativeError("没有实际域名解析成功的观测，不能声称 DNS 服务正常。")
            if re.search(r"(?:TLS|HTTPS|握手|证书).{0,12}(?:正常|成功|通过|有效|无异常)", clause, re.I):
                if http.get("tls_checked") is not True or http.get("status") != "ok":
                    raise NarrativeError("没有 TLS 握手及证书校验成功的观测，不能声称 TLS 正常。")
            if TLS_TIMING_CLAIM.search(clause):
                raise NarrativeError("没有配置 TLS 耗时阈值，不能断言 TLS 握手偏慢或耗时过长。")
            if SLOW_CLAIM.search(clause) and http.get("slow") is not True:
                raise NarrativeError("观测未确认慢响应，不能把响应偏慢或超过阈值列为支持的判断。")

    for value in final["rejected_hypotheses"]:
        if TLS_WORD.search(value) and http.get("tls_checked") is not True:
            raise NarrativeError("未完成 TLS 检查，不能排除 TLS/证书故障；请放入 uncertainties。")
        if re.search(r"DNS|域名解析", value, re.I) and dns.get("ip_literal"):
            raise NarrativeError("IP 输入未验证 DNS 服务，不能排除 DNS 故障。")
        if SLOW_CLAIM.search(value) and http.get("slow") is not False:
            raise NarrativeError("缺少未超阈值的观测，不能排除慢响应。")
        if re.search(r"http_error|HTTP.{0,8}(?:错误|异常|故障)", value, re.I):
            if http.get("status") != "ok" or http.get("http_error") is True or http.get("http_status", 0) >= 400:
                raise NarrativeError("未获得无 HTTP 错误的响应，不能排除 HTTP 服务错误。")

    for value in final["uncertainties"]:
        if http.get("status") == "ok" and "http_status" in http:
            missing_http = re.search(
                r"(?:无法确认|无法判断|未确认|未获得|未获取|缺少|缺失).{0,12}HTTP.{0,8}(?:响应|状态)"
                r"|HTTP.{0,8}(?:响应状态|状态码).{0,8}(?:未知|缺失|缺少|不明|未确认)", value, re.I)
            if missing_http:
                raise NarrativeError("已经获得 HTTP 响应和状态码，不能声称缺少或无法确认本次 HTTP 状态。")
        if http.get("scheme") == "http" and re.search(r"无法排除.{0,16}(?:TLS|证书).{0,8}(?:错误|故障|失败)", value, re.I):
            raise NarrativeError("本次请求使用 HTTP，TLS 不适用于本次请求，不能把 TLS 故障列为本次请求的待排查原因。")

    for value in final["recommendations"]:
        if suggests_disruptive_action(value):
            raise NarrativeError("现有探测不足以支持重启、重新部署或关闭安全检查；请先核查配置或日志并复测。")
        if TLS_WORD.search(value) and http.get("status") == "ok":
            raise NarrativeError("已获得 HTTP 响应，不应优先建议修复 TLS/证书；请围绕已观测阶段提出建议。")
        if re.search(r"(?:增加|延长|提高|调大).{0,16}(?:超时|timeout)", value, re.I) and http.get("status") == "ok":
            raise NarrativeError("本次已获得响应，没有超时故障证据，不建议增大超时时间。")
