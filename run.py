"""Command-line entry point. Run `python run.py --help`."""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from src.agent import ROOT, diagnose
from src.evaluation import evaluate_cases
from src.lab import laboratory, load_cases
from src.report import print_result, save
from src.tools import Probes


def add_agent_options(parser):
    parser.add_argument("--engine", choices=("ollama", "rules"), default="ollama")
    parser.add_argument("--mode", choices=("baseline", "tools", "skill"), default="skill")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b"))
    parser.add_argument("--host", default=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))
    parser.add_argument("--out", type=Path, default=ROOT / "results")


def main():
    parser = argparse.ArgumentParser(description="网站访问异常诊断 Agent：真实工具、可控故障、对照评测")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="检查 Ollama 和可用模型")
    doctor.add_argument("--host", default=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))
    web = commands.add_parser("web", help="启动本机网页工作台（无第三方 Python 依赖）")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--open", action="store_true", help="启动后打开默认浏览器")
    live = commands.add_parser("diagnose", help="检查一个实际网址（从本机直连）")
    live.add_argument("url")
    live.add_argument("--timeout", type=float, default=3.0)
    live.add_argument("--slow-ms", type=float, default=800)
    add_agent_options(live)
    demo = commands.add_parser("demo", help="启动本地故障服务后进行实际诊断")
    demo.add_argument("--case", choices=[case["id"] for case in load_cases()], default="http_error")
    demo.add_argument("--all", action="store_true")
    add_agent_options(demo)
    evaluation = commands.add_parser("evaluate", help="相同数据条件下运行 A/B/C 或规则冒烟评测")
    add_agent_options(evaluation)
    evaluation.add_argument("--cases", nargs="+", choices=[case["id"] for case in load_cases()])
    evaluation.add_argument("--modes", nargs="+", choices=("baseline", "tools", "skill"), default=["baseline", "tools", "skill"])
    evaluation.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    try:
        if args.command == "web":
            from src.web import serve
            if not 1 <= args.port <= 65535:
                parser.error("port 必须在 1 到 65535 之间")
            serve(port=args.port, open_browser=args.open)
            return 0
        if args.command == "doctor":
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(args.host.rstrip("/") + "/api/tags", timeout=5) as response:
                data = json.load(response)
            print("Ollama 可访问。模型：" + ", ".join(item["name"] for item in data.get("models", [])))
            return 0
        if args.command == "evaluate":
            if args.repeats < 1:
                parser.error("--repeats 必须为正整数")
            cases = [case for case in load_cases() if not args.cases or case["id"] in args.cases]
            report = evaluate_cases(cases, args.out, engine=args.engine, modes=args.modes,
                                    repeats=args.repeats, model=args.model, host=args.host)
            for item in report["summary"]:
                print(f"{item['mode']}: 正确率 {item['conclusion_accuracy']:.1%}；成功率 {item['task_success_rate']:.1%}；执行失败 {item['execution_errors']}")
            print("评测结果：" + str(args.out / "evaluation.md"))
            return 1 if any(row["error"] for row in report["rows"]) else 0
        if args.command == "diagnose":
            if not (0 < args.timeout <= 30 and 0 < args.slow_ms):
                parser.error("timeout 应在 (0,30] 秒内；slow-ms 应为正数")
            result = diagnose(Probes(args.url, args.timeout, args.slow_ms), engine=args.engine,
                              mode=args.mode, model=args.model, host=args.host)
            print_result(result)
            _, path = save(result, args.out)
            print("报告：" + str(path))
            return int(result.get("final") is None)
        failed = False
        for case in load_cases():
            if not args.all and case["id"] != args.case:
                continue
            print(f"\n实验案例：{case['title']}；数据类型：{case['source']}", flush=True)
            with laboratory(case) as provider:
                result = diagnose(provider, engine=args.engine, mode=args.mode,
                                  model=args.model, host=args.host, incident=case.get("incident"))
            result["laboratory"] = {"case_id": case["id"], "expected": case["expected"], "source": case["source"]}
            print_result(result)
            _, path = save(result, args.out, case["id"])
            print("报告：" + str(path))
            failed |= result.get("final") is None
        return int(failed)
    except (ValueError, OSError) as error:
        print("错误：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
