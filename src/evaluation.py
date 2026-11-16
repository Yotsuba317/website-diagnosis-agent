"""Paired A/B/C runs with identical recorded observations, and hidden case labels."""

import csv
import hashlib
import json
import statistics
from pathlib import Path

from .agent import ROOT, Ollama, diagnose
from .lab import laboratory
from .report import save
from .tools import RecordedProbes, collect_observations


def grade(result, case):
    final = result.get("final")
    predicted = final["diagnosis"] if final else "execution_error"
    stages = ("check_dns", "check_tcp", "check_http")
    decisive = case.get("decisive_tool") or {
        "dns_failure": "check_dns", "tcp_failure": "check_tcp",
    }.get(case["expected"], "check_http")
    required = set(stages[:stages.index(decisive) + 1])
    cited = set(final["evidence_ids"]) if final else set()
    cited_tools = {e["tool"] for e in result["evidence"] if e["evidence_id"] in cited}
    coverage = len(required & cited_tools) / len(required)
    correct = predicted == case["expected"]
    trace = result["trace"]
    drafts = result.get("drafts", [])
    return {"case_id": case["id"], "case_source": case["source"], "expected": case["expected"],
            "predicted": predicted, "correct": int(correct),
            "first_draft_correct": int(bool(drafts and drafts[0]["final"]["diagnosis"] == case["expected"])) if result["engine"] == "ollama" else None,
            "validation_retries": len(result.get("validation_errors", [])),
            "narrative_repair_used": int(result.get("narrative_repair_used", False)),
            "task_success": int(bool(correct and decisive in cited_tools and final["recommendations"])),
            "evidence_coverage": coverage, "tool_calls": len(trace),
            "valid_tool_calls": sum(call["accepted"] for call in trace),
            "llm_requests": result["llm_requests"], "elapsed_seconds": result["elapsed_seconds"],
            "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"],
            "error": result.get("error", "")}


def evaluate_cases(cases, output, engine="ollama", modes=("baseline", "tools", "skill"),
                   repeats=1, model=None, host=None, on_event=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    model = (model or Ollama().model) if engine == "ollama" else None
    if engine == "rules":
        modes = ("skill",)
    manifest = {"engine": engine, "model": model if engine == "ollama" else None,
                "modes": list(modes), "case_ids": [case["id"] for case in cases], "repeats": repeats,
                "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in [*sorted((ROOT / "src").glob("*.py")), ROOT / "data/cases.json",
                                               ROOT / "skills/website-investigation/SKILL.md"]}}
    (output / "run-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in cases:
        with laboratory(case) as provider:
            observations = collect_observations(provider)
            target = provider.target
        # Real local network observations are collected once, before A/B/C. The
        # model cannot access the case ID, fault injection or expected answer.
        (output / f"observations-{case['id']}.json").write_text(
            json.dumps({"target": target, "observations": observations}, ensure_ascii=False, indent=2), encoding="utf-8")
        for repeat in range(1, repeats + 1):
            for mode in modes:
                if on_event:
                    on_event({"type": "evaluation_item", "case_id": case["id"], "mode": mode,
                              "repeat": repeat, "completed": len(rows), "total": len(cases) * repeats * len(modes)})
                print(f"评测 {case['id']} / {mode} / repeat {repeat} ...", flush=True)
                replay = RecordedProbes(target, observations)
                result = diagnose(replay, engine=engine, mode=mode, model=model, host=host,
                                  on_event=on_event, incident=case.get("incident"))
                result["evaluation"] = {"case_id": case["id"], "expected": case["expected"],
                                        "repeat": repeat, "observations_replayed": True,
                                        "criterion": case.get("criterion")}
                json_path, _ = save(result, output / "traces", f"{case['id']}-{mode}-r{repeat}")
                row = {"mode": mode, "repeat": repeat, **grade(result, case), "trace_file": json_path.relative_to(output).as_posix()}
                rows.append(row)
                if on_event:
                    on_event({"type": "evaluation_scored", "case_id": case["id"], "mode": mode,
                              "correct": row["correct"], "completed": len(rows),
                              "total": len(cases) * repeats * len(modes)})
                print(f"  expected={row['expected']}; predicted={row['predicted']}; success={row['task_success']}", flush=True)
    with (output / "evaluation.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for mode in modes:
        group = [row for row in rows if row["mode"] == mode]
        calls = sum(row["tool_calls"] for row in group)
        normal = [row for row in group if row["expected"] == "normal"]
        summary.append({"mode": mode, "runs": len(group),
            "conclusion_accuracy": statistics.mean(row["correct"] for row in group),
            "task_success_rate": statistics.mean(row["task_success"] for row in group),
            "first_draft_accuracy": statistics.mean(row["first_draft_correct"] for row in group) if engine == "ollama" else None,
            "mean_evidence_coverage": statistics.mean(row["evidence_coverage"] for row in group),
            "valid_tool_call_rate": sum(row["valid_tool_calls"] for row in group) / calls if calls else None,
            "mean_elapsed_seconds": statistics.mean(row["elapsed_seconds"] for row in group),
            "execution_errors": sum(bool(row["error"]) for row in group),
            "narrative_repair_runs": sum(row["narrative_repair_used"] for row in group),
            "normal_false_alarm_rate": sum(row["predicted"] not in ("normal", "execution_error") for row in normal) / len(normal) if normal else None})
    report = {"engine": engine, "model": model if engine == "ollama" else None, "repeats": repeats,
              "protocol": "A receives identical raw observations as text; B/C query those observations through tools. Case labels are hidden from all model prompts.",
              "rules_warning": "Rules-only smoke test; not evidence of LLM/Skill benefit" if engine == "rules" else None,
              "summary": summary, "rows": rows}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 对照实验结果", "", f"引擎：{engine}；重复次数：{repeats}。", "",
             "A=baseline（直接分析相同原始观测），B=tools，C=skill。",
             "各组模型、问题和原始观测相同；B/C 的工具返回值为同一批真实探测或明确标记的模拟观测回放。",
             "expected 标签未传给 Agent。规则模式仅为工具冒烟测试，不代表任何 LLM 或 Skill 效果。", "",
             "所有组共用结构及观测一致性校验；错误草稿和修正次数单独保存，不用规则替换模型结论。", "",
             "| 模式 | 运行数 | 首次草稿正确率 | 最终正确率 | 任务成功率 | 证据覆盖率 | 平均秒数 | 执行失败 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for item in summary:
        first = f"{item['first_draft_accuracy']:.1%}" if item["first_draft_accuracy"] is not None else "不适用"
        lines.append(f"| {item['mode']} | {item['runs']} | {first} | {item['conclusion_accuracy']:.1%} | {item['task_success_rate']:.1%} | {item['mean_evidence_coverage']:.1%} | {item['mean_elapsed_seconds']:.2f} | {item['execution_errors']} |")
    lines += ["", "结论正确率：匹配预先定义诊断类别的运行数 / 全部运行数（含执行失败）。",
              "任务成功：类别正确、引用决定性阶段证据，且有后续建议。",
              "证据覆盖率：引用的必要阶段工具数 / 本案例必要阶段工具数。",
              "工具调用正确率：工具名、参数与前置条件有效的调用数 / 总调用数；无工具组不适用。",
              "这些自动指标不完整衡量因果解释或建议质量，仍需人工审阅 traces 中的结论、反证和不确定性。",
              "小案例集上的高分不代表真实校园网覆盖率；模型调用失败按失败如实记录。", ""]
    (output / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    return report
