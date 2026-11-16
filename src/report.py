"""Persist readable reports and the full actual tool/model trace."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .agent import rules_conclusion


LABELS = {"normal": "本次基础访问正常", "dns_failure": "DNS 解析失败",
          "tcp_failure": "TCP 连接失败", "tls_failure": "TLS 握手或证书问题",
          "http_error": "HTTP 错误响应", "slow_response": "响应等待偏长",
          "insufficient_evidence": "证据不足"}
NARRATIVE_NOTE = "摘要采用与类别绑定的程序短句；其余模型文字通过有限规则检查，仍需人工核对。"


def fact_lines(result):
    lines = []
    for item in result["evidence"]:
        if item["tool"] == "check_dns" and item.get("ip_literal"):
            lines.append("输入是 IP，本次没有验证 DNS 服务器。")
        if item["tool"] == "check_http" and "http_status" in item:
            relation = ">=" if item["slow"] else "<"
            lines.append(f"HTTP {item['http_status']}；响应等待 {item['response_wait_ms']} ms {relation} 阈值 {item['slow_threshold_ms']} ms。")
            if item.get("tls_checked") is False:
                lines.append("本次是 HTTP 请求，未执行 TLS 握手或证书检查。")
    return lines


def render(result):
    final = result.get("final")
    lines = ["# 网站访问诊断报告", "", f"- 目标：`{result['target']['url']}`",
             f"- 引擎：`{result['engine']}`；模式：`{result['mode']}`；模型：`{result['model']}`",
             f"- 读取专业 Skill：{'是' if result['skill_loaded'] else '否'}",
             f"- 用时：{result['elapsed_seconds']} 秒；模型请求：{result['llm_requests']} 次", ""]
    if result.get("incident"):
        lines += ["## 报障描述（待验证）", "", result["incident"], ""]
    if result.get("candidate_hypotheses"):
        lines += ["## 调查前候选假设", ""] + ["- " + item for item in result["candidate_hypotheses"]] + [""]
    for warning in result.get("warnings", []):
        lines += [f"> {warning}", ""]
    if result["engine"] == "ollama" and result.get("narrative_policy"):
        lines += [f"> {NARRATIVE_NOTE}", ""]
    if result.get("validation_errors"):
        lines += ["## 输出校验与修正记录", ""] + ["- " + item for item in result["validation_errors"]] + [""]
    if fact_lines(result):
        lines += ["## 程序直接核对的事实", ""] + ["- " + item for item in fact_lines(result)] + [""]
    program = result.get("program_findings") or rules_conclusion(result["evidence"])
    lines += ["## 程序核对的阶段建议", "", "这是确定性规则对实际观测的核对，不计为 LLM 判断成绩。", "",
              program["summary"], ""] + ["- " + item for item in program["recommendations"]] + [""]
    if final:
        lines += ["## 判断", "", f"**{LABELS[final['diagnosis']]}**：{final['summary']}", "",
                  "引用证据：" + ", ".join(final["evidence_ids"]), ""]
        for key, title in (("supported_hypotheses", "支持的判断"), ("rejected_hypotheses", "反证与排除"),
                           ("uncertainties", "不确定性"), ("recommendations", "建议与复测")):
            suffix = "（模型生成，待核对）" if result["engine"] == "ollama" else ""
            lines += ["## " + title + suffix, ""] + ["- " + item for item in final[key]] + [""]
    else:
        lines += ["## 执行失败", "", result.get("error", "未知错误"), ""]
    lines += ["## 实际证据", ""]
    for observation in result["evidence"]:
        lines += [f"### {observation['evidence_id']} / {observation['tool']}", "", "```json",
                  json.dumps(observation, ensure_ascii=False, indent=2), "```", ""]
    lines += ["## 工具调用 Trace", "", "```json", json.dumps(result["trace"], ensure_ascii=False, indent=2),
              "```", "", "完整 JSON 还包含本次模型消息、实际加载的 Skill 和 token 统计。", ""]
    return "\n".join(lines)


def save(result, directory, prefix="diagnosis"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    stem = f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"
    json_path, md_path = directory / (stem + ".json"), directory / (stem + ".md")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render(result), encoding="utf-8")
    return json_path, md_path


def print_result(result):
    final = result.get("final")
    print(f"\n目标：{result['target']['url']}")
    print(f"引擎：{result['engine']} | 模式：{result['mode']} | Skill：{result['skill_loaded']}")
    if result.get("incident"):
        print("报障描述（待验证）：" + result["incident"])
    for candidate in result.get("candidate_hypotheses", []):
        print("待检验：" + candidate)
    for item in result["evidence"]:
        detail = ""
        if item["tool"] == "check_http" and "http_status" in item:
            detail = f" | HTTP {item['http_status']} | 响应等待 {item['response_wait_ms']} ms"
        print(f"  {item['evidence_id']} {item['tool']}: {item['status']} [{item.get('source', 'unknown')}]{detail}")
    for fact in fact_lines(result):
        print("实测核对：" + fact)
    program = result.get("program_findings") or rules_conclusion(result["evidence"])
    for advice in program["recommendations"]:
        print("程序阶段建议：" + advice)
    if final:
        print(f"判断：{LABELS[final['diagnosis']]} — {final['summary']}")
        for advice in final["recommendations"]:
            print(("模型补充（待核对）：" if result["engine"] == "ollama" else "建议：") + advice)
    else:
        print("执行失败：" + result.get("error", "未知错误"))
    for warning in result.get("warnings", []):
        print("说明：" + warning)
    if result["engine"] == "ollama" and result.get("narrative_policy"):
        print("说明：" + NARRATIVE_NOTE)
    print(f"模型调用 {result['llm_requests']} 次；耗时 {result['elapsed_seconds']} 秒")
    if result.get("validation_errors"):
        print(f"输出校验要求修正 {len(result['validation_errors'])} 次；完整草稿保存在 JSON。")
