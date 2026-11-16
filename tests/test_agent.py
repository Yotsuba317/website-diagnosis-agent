"""Deterministic tests; live localhost probes, no LLM or external websites needed."""

import json
import unittest
from unittest.mock import Mock

from src.agent import AgentError, ToolSession, check_consistency, compatible_diagnoses, diagnose, parse_final, rules_conclusion
from src.evaluation import grade
from src.lab import laboratory, load_cases
from src.tools import Probes, RecordedProbes, collect_observations, parse_target


def normal_provider():
    common = {"source": "synthetic_fixture"}
    return RecordedProbes(parse_target("http://fixture.test"), {
        "check_dns": {**common, "status": "ok", "addresses": ["192.0.2.10"]},
        "check_tcp": {**common, "status": "ok"},
        "check_http": {**common, "status": "ok", "http_status": 200, "slow": False,
                       "response_wait_ms": 5, "slow_threshold_ms": 800},
    })


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append((list(messages), tools))
        return next(self.responses)


def final_response(final):
    return {"message": {"role": "assistant", "content": json.dumps(final, ensure_ascii=False)}}


class AgentTests(unittest.TestCase):
    def test_target_validation_and_bound_scope(self):
        self.assertEqual(parse_target("example.org")["port"], 443)
        self.assertEqual(parse_target("http://example.org")["port"], 80)
        self.assertEqual(parse_target("https://example.org:1")["port"], 1)
        self.assertEqual(parse_target("http://[::1]:65535")["port"], 65535)
        self.assertEqual(parse_target("http://127.0.0.1:8000/a?b=1#fragment")["path"], "/a?b=1")
        for value in ("file:///etc/passwd", "https://user:password@example.org", "http://x:99999",
                      "http://x:0", "https://x:0", "http://[::1]:0", "http://x:-1",
                      "http://x\r\nInjected: yes"):
            with self.subTest(url=value), self.assertRaises(ValueError):
                parse_target(value)

    def test_actual_local_faults_and_explicit_synthetic_cases(self):
        for case in load_cases():
            with self.subTest(case=case["id"]):
                with laboratory(case) as provider:
                    result = diagnose(provider, engine="rules")
                self.assertEqual(result["final"]["diagnosis"], case["expected"])
                self.assertEqual(grade(result, case)["task_success"], 1)
                self.assertEqual(result["llm_requests"], 0)
                self.assertTrue(result["warnings"])
                self.assertTrue(all(item.get("source") in ("live_probe", "synthetic_fixture") for item in result["evidence"]))
                if case["id"] == "dns_failure":
                    self.assertEqual(len(result["trace"]), 1)
                if case["id"] == "tcp_failure":
                    self.assertEqual(len(result["trace"]), 2)

    def test_unknown_tools_and_extra_arguments_are_not_executed(self):
        session = ToolSession(normal_provider())
        self.assertEqual(session.call("run_shell", {})["status"], "tool_error")
        self.assertEqual(session.call("check_dns", {"url": "http://other.test"})["status"], "tool_error")
        self.assertFalse(any(call["accepted"] for call in session.trace))
        self.assertEqual(session.evidence, [])

    def test_cached_results_keep_same_evidence_id(self):
        session = ToolSession(normal_provider())
        first, second = session.call("check_dns", {}), session.call("check_dns", {})
        self.assertEqual(first, second)
        self.assertEqual(len(session.evidence), 1)
        self.assertEqual(len(session.trace), 2)

    def test_non_object_arguments_do_not_execute_provider(self):
        provider = normal_provider()
        provider.call = Mock(wraps=provider.call)
        session = ToolSession(provider)
        for arguments in ([], "", 0, False, None, [1], "{}"):
            with self.subTest(arguments=arguments):
                self.assertEqual(session.call("check_dns", arguments)["status"], "tool_error")
                self.assertFalse(session.trace[-1]["accepted"])
        provider.call.assert_not_called()
        self.assertEqual(session.evidence, [])
        self.assertEqual(session.call("check_dns", {})["status"], "ok")
        provider.call.assert_called_once_with("check_dns")

    def test_live_and_replay_require_successful_prerequisites(self):
        for provider in (Probes("http://127.0.0.1"), normal_provider()):
            with self.subTest(provider=type(provider).__name__):
                self.assertEqual(provider.call("check_http")["required_tool"], "check_dns")
                self.assertEqual(provider.call("check_tcp")["status"], "not_ready")
                self.assertEqual(provider.call("check_dns")["status"], "ok")
                self.assertEqual(provider.call("check_http")["required_tool"], "check_tcp")
                # A previously blocked call must not be cached as a completed check.
                provider.cache["check_tcp"] = {"status": "ok"}
                if isinstance(provider, Probes):
                    provider.check_http = Mock(return_value={"status": "ok"})
                self.assertEqual(provider.call("check_http")["status"], "ok")

    def test_failed_or_missing_prerequisites_do_not_replay_later_success(self):
        for failed_tool in ("check_dns", "check_tcp"):
            for status in ("error", "unavailable", "skipped"):
                with self.subTest(tool=failed_tool, status=status):
                    provider = normal_provider()
                    provider.records[failed_tool] = {"status": status}
                    session = ToolSession(provider)
                    for name in ("check_dns", "check_tcp"):
                        session.call(name, {})
                        if name == failed_tool:
                            break
                    before = list(session.evidence)
                    self.assertEqual(session.call("check_http", {})["status"], "not_ready")
                    self.assertFalse(session.trace[-1]["accepted"])
                    self.assertEqual(session.evidence, before)
                    self.assertEqual(provider.call("check_http")["status"], "not_ready")

    def test_session_does_not_use_provider_history_as_model_evidence(self):
        provider = normal_provider()
        collect_observations(provider)
        provider.call = Mock(wraps=provider.call)
        session = ToolSession(provider)
        self.assertEqual(session.call("check_http", {})["status"], "not_ready")
        self.assertEqual(session.evidence, [])
        provider.call.assert_not_called()

    def test_model_recovers_from_out_of_order_replay_without_credit_for_bad_call(self):
        provider = normal_provider()
        evidence = [{"evidence_id": f"E{i+1}", "tool": name, **record}
                    for i, (name, record) in enumerate(provider.records.items())]
        def calls(*names):
            return {"message": {"tool_calls": [
                {"function": {"name": name, "arguments": {}}} for name in names]}}
        model = FakeModel([calls("check_http"), calls("check_dns", "check_tcp", "check_http"),
                           final_response(rules_conclusion(evidence))])
        result = diagnose(provider, mode="tools", client=model)
        self.assertEqual(result["final"]["diagnosis"], "normal")
        self.assertEqual([call["accepted"] for call in result["trace"]], [False, True, True, True])
        score = grade(result, {"id": "normal", "expected": "normal", "source": "synthetic_fixture"})
        self.assertEqual((score["valid_tool_calls"], score["tool_calls"]), (3, 4))
        self.assertEqual(score["evidence_coverage"], 1)

    def test_collection_and_model_stop_when_prerequisite_is_unavailable(self):
        provider = normal_provider()
        del provider.records["check_dns"]
        self.assertEqual(list(collect_observations(provider)), ["check_dns"])
        model = FakeModel([
            {"message": {"tool_calls": [{"function": {"name": "check_dns", "arguments": {}}}]}},
            final_response(rules_conclusion([])),
        ])
        result = diagnose(provider, client=model)
        self.assertEqual(result["final"]["diagnosis"], "insufficient_evidence")
        self.assertIsNone(model.calls[1][1])

    def test_model_controls_tools_and_skill_is_actually_in_prompt(self):
        evidence = [{"evidence_id": f"E{i+1}", "tool": name, **record}
                    for i, (name, record) in enumerate(normal_provider().records.items())]
        final = rules_conclusion(evidence)
        tool_calls = {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": name, "arguments": {}}}
            for name in ("check_dns", "check_tcp", "check_http")]}}
        model = FakeModel([tool_calls, final_response(final)])
        result = diagnose(normal_provider(), client=model)
        self.assertEqual(result["final"]["diagnosis"], "normal")
        self.assertEqual(len(result["trace"]), 3)
        self.assertEqual(result["llm_requests"], 2)
        self.assertIn("SKILL", result["skill_path"])
        self.assertIn("check_dns", model.calls[0][0][0]["content"])
        self.assertEqual(len(model.calls[0][1]), 3)
        self.assertIsNone(model.calls[1][1])

    def test_dns_failure_switches_from_probing_to_final_answer(self):
        case = next(case for case in load_cases() if case["id"] == "dns_failure")
        with laboratory(case) as provider:
            observation = provider.call("check_dns")
            evidence = [{"evidence_id": "E1", "tool": "check_dns", **observation}]
            model = FakeModel([
                {"message": {"tool_calls": [{"function": {"name": "check_dns", "arguments": {}}}]}},
                final_response(rules_conclusion(evidence)),
            ])
            result = diagnose(provider, client=model)
        self.assertEqual(result["final"]["diagnosis"], "dns_failure")
        self.assertEqual(len(result["trace"]), 1)
        self.assertIsNone(model.calls[1][1])

    def test_baseline_gets_same_observations_and_no_tools(self):
        provider = normal_provider()
        evidence = [{"evidence_id": f"E{i+1}", "tool": name, **record}
                    for i, (name, record) in enumerate(provider.records.items())]
        model = FakeModel([final_response(rules_conclusion(evidence))])
        incident = "用户曾报告站点打不开，请复测。"
        result = diagnose(provider, mode="baseline", client=model, incident=incident)
        self.assertEqual(result["final"]["diagnosis"], "normal")
        self.assertEqual(result["incident"], incident)
        self.assertGreaterEqual(len(result["candidate_hypotheses"]), 2)
        self.assertIn("报障描述（待验证）：" + incident, model.calls[0][0][1]["content"])
        self.assertEqual(result["trace"], [])
        self.assertFalse(result["skill_loaded"])
        self.assertIsNone(model.calls[0][1])
        self.assertTrue(any("http_status" in message["content"] for message in model.calls[0][0]))

    def test_unknown_evidence_is_rejected(self):
        final = rules_conclusion([])
        final["evidence_ids"] = ["E999"]
        with self.assertRaises(ValueError):
            parse_final(json.dumps(final), [])

    def test_status_and_timing_contradiction_is_rejected_without_replacement(self):
        provider = normal_provider()
        provider.records["check_http"].update(http_status=503, slow=False, response_wait_ms=0.79)
        evidence = [{"evidence_id": f"E{i+1}", "tool": name, **record}
                    for i, (name, record) in enumerate(provider.records.items())]
        wrong = rules_conclusion(evidence)
        wrong["diagnosis"] = "slow_response"
        with self.assertRaises(ValueError):
            check_consistency(wrong, evidence)
        model = FakeModel([final_response(wrong), final_response(rules_conclusion(evidence))])
        result = diagnose(provider, mode="baseline", client=model)
        self.assertEqual(result["drafts"][0]["final"]["diagnosis"], "slow_response")
        self.assertEqual(result["final"]["diagnosis"], "http_error")
        self.assertEqual(len(result["validation_errors"]), 1)

    def test_repair_candidates_and_decisive_citation_follow_observations(self):
        provider = normal_provider()
        evidence = [{"evidence_id": f"E{i+1}", "tool": name, **record}
                    for i, (name, record) in enumerate(provider.records.items())]
        self.assertEqual(set(compatible_diagnoses(evidence)), {"normal", "insufficient_evidence"})
        final = rules_conclusion(evidence)
        final["evidence_ids"] = ["E1"]
        with self.assertRaises(ValueError):
            check_consistency(final, evidence)

    def test_ollama_failure_is_reported_without_rules_fallback(self):
        class Broken:
            def chat(self, *_):
                raise AgentError("deliberate model failure")
        result = diagnose(normal_provider(), client=Broken())
        self.assertIsNone(result["final"])
        self.assertEqual(result["engine"], "ollama")
        self.assertIn("deliberate", result["error"])

    def test_round_limit_records_failure(self):
        model = FakeModel([{"message": {"content": "not JSON"}}] * 2)
        result = diagnose(normal_provider(), client=model, max_rounds=2)
        self.assertIsNone(result["final"])
        self.assertEqual(result["llm_requests"], 2)

    def test_redirect_does_not_prove_final_destination_is_healthy(self):
        provider = normal_provider()
        provider.records["check_http"]["http_status"] = 302
        result = diagnose(provider, engine="rules")
        self.assertEqual(result["final"]["diagnosis"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
