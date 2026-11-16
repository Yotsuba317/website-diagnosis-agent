"""Regression cases for plausible-looking but unsupported model explanations."""

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from src.agent import Ollama, check_consistency, compatible_diagnoses, diagnose, rules_conclusion
from src.report import print_result, render
from src.tools import RecordedProbes, parse_target
from src.validation import check_repair_selection, repair_text_choices, summary_choices


def fixture(code=200, slow=False):
    records = {
        "check_dns": {"status": "ok", "addresses": ["192.0.2.10"], "ip_literal": False},
        "check_tcp": {"status": "ok"},
        "check_http": {"status": "ok", "http_status": code, "http_error": code >= 400,
                       "scheme": "https", "tls_checked": True, "tls_ms": 49.34,
                       "response_wait_ms": 1200 if slow else 134.36,
                       "slow_threshold_ms": 800, "slow": slow},
    }
    evidence = [{"evidence_id": f"E{i+1}", "tool": name, **record}
                for i, (name, record) in enumerate(records.items())]
    return records, evidence, rules_conclusion(evidence)


def response(final):
    return {"message": {"content": json.dumps(final, ensure_ascii=False)}}


class NarrativeTests(unittest.TestCase):
    def test_screenshot_summary_is_rejected_despite_correct_category(self):
        _, evidence, final = fixture()
        final["summary"] = "HTTPS 请求在 TLS 握手阶段耗时较长（49.34ms），响应等待时间超过阈值（134.36ms > 800ms threshold）。"
        with self.assertRaisesRegex(ValueError, "summary"):
            check_consistency(final, evidence)

    def test_timing_math_cannot_be_moved_to_other_fields(self):
        _, evidence, original = fixture()
        for field in ("supported_hypotheses", "rejected_hypotheses", "uncertainties", "recommendations"):
            for text in ("134.36 ms > 800 ms", "0.13436 秒超过阈值", "134.36 > 800"):
                with self.subTest(field=field, text=text):
                    final = copy.deepcopy(original)
                    final[field] = [text]
                    with self.assertRaisesRegex(ValueError, "数值"):
                        check_consistency(final, evidence)

    def test_fast_response_cannot_support_slowness_in_either_200_or_503_case(self):
        for code in (200, 503):
            _, evidence, original = fixture(code=code)
            for text in ("响应偏慢", "响应等待时间超过阈值", "slow_response"):
                with self.subTest(code=code, text=text):
                    final = copy.deepcopy(original)
                    final["supported_hypotheses"] = [text]
                    with self.assertRaisesRegex(ValueError, "慢响应"):
                        check_consistency(final, evidence)

    def test_tls_time_alone_does_not_prove_tls_slowness(self):
        _, evidence, final = fixture()
        final["supported_hypotheses"] = ["TLS 握手耗时较长"]
        with self.assertRaisesRegex(ValueError, "TLS 耗时阈值"):
            check_consistency(final, evidence)

    def test_ip_and_plain_http_do_not_prove_dns_or_tls_success(self):
        _, evidence, original = fixture(code=503)
        evidence[0]["ip_literal"] = True
        evidence[-1].update(scheme="http", tls_checked=False)
        for text in ("DNS 解析正常", "TLS 握手正常", "HTTPS 握手成功", "证书有效"):
            with self.subTest(assertion=text):
                final = copy.deepcopy(original)
                final["supported_hypotheses"] = [text]
                with self.assertRaises(ValueError):
                    check_consistency(final, evidence)

    def test_observed_http_status_cannot_be_described_as_missing(self):
        _, evidence, original = fixture(code=503)
        for text in ("无法确认 HTTP 响应状态", "HTTP 状态码缺失", "未获得 HTTP 响应"):
            with self.subTest(uncertainty=text):
                final = copy.deepcopy(original)
                final["uncertainties"] = [text]
                with self.assertRaises(ValueError):
                    check_consistency(final, evidence)

    def test_actual_slow_response_and_qualified_followup_are_allowed(self):
        _, evidence, final = fixture(slow=True)
        check_consistency(final, evidence)
        _, evidence, final = fixture()
        final["supported_hypotheses"] = ["本次响应未超过阈值"]
        final["uncertainties"] = ["无法判断其他探测位置是否存在慢响应。"]
        final["recommendations"] = ["若用户仍觉得响应慢，请在其所在网络位置复测。"]
        check_consistency(final, evidence)
        final["recommendations"] = ["不要重启服务；先在用户所在位置复测。"]
        check_consistency(final, evidence)

    def test_unobserved_stages_and_observed_faults_cannot_be_excluded(self):
        _, evidence, final = fixture()
        evidence[0]["ip_literal"] = True
        evidence[-1] = {"evidence_id": "E3", "tool": "check_http", "status": "unavailable"}
        final.update(diagnosis="insufficient_evidence", summary=summary_choices(evidence)["insufficient_evidence"])
        for text in ("dns_failure", "tls_failure", "http_error", "slow_response"):
            with self.subTest(excluded=text):
                final["rejected_hypotheses"] = [text]
                with self.assertRaises(ValueError):
                    check_consistency(final, evidence)
        _, evidence, final = fixture(slow=True)
        final["rejected_hypotheses"] = ["slow_response"]
        with self.assertRaises(ValueError):
            check_consistency(final, evidence)

    def test_irrelevant_or_disruptive_recommendations_are_rejected(self):
        _, evidence, original = fixture()
        for text in ("检查 HTTPS 证书有效期", "增加 HTTP 请求重试次数或延长超时时间",
                     "重启目标服务器", "重新部署目标服务", "关闭证书验证"):
            with self.subTest(advice=text):
                final = copy.deepcopy(original)
                final["recommendations"] = [text]
                with self.assertRaises(ValueError):
                    check_consistency(final, evidence)
        _, evidence, final = fixture()
        evidence[-1] = {"evidence_id": "E3", "tool": "check_http", "status": "error", "error_type": "tls_error"}
        final = rules_conclusion(evidence)
        check_consistency(final, evidence)

    def test_rejected_draft_is_retained_but_not_published_in_report(self):
        records, _, good = fixture()
        good["rejected_hypotheses"] = []
        bad = copy.deepcopy(good)
        bad["summary"] = "响应偏慢，134.36ms > 800ms"
        client = Mock()
        client.chat.side_effect = [response(bad), response(good)]
        result = diagnose(RecordedProbes(parse_target("https://fixture.test"), records),
                          mode="baseline", client=client)
        self.assertEqual(result["final"], good)
        self.assertEqual(result["drafts"][0]["final"], bad)
        self.assertEqual(len(result["validation_errors"]), 1)
        self.assertTrue(result["narrative_repair_used"])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            print_result(result)
        for output in (stdout.getvalue(), render(result)):
            self.assertNotIn(bad["summary"], output)
            self.assertIn(good["summary"], output)
            self.assertIn("134.36 ms <", output)

    def test_persistent_bad_explanation_is_an_execution_failure(self):
        records, _, bad = fixture()
        bad["recommendations"] = ["重新部署目标服务"]
        client = Mock()
        client.chat.return_value = response(bad)
        result = diagnose(RecordedProbes(parse_target("https://fixture.test"), records),
                          mode="baseline", client=client, max_rounds=2)
        self.assertIsNone(result["final"])
        self.assertEqual(len(result["drafts"]), 2)
        self.assertEqual(result["program_findings"]["diagnosis"], "normal")

    def test_repair_candidates_are_valid_and_selection_is_enforced(self):
        for code, slow in ((200, False), (503, False), (200, True)):
            with self.subTest(code=code, slow=slow):
                _, evidence, final = fixture(code, slow)
                choices = repair_text_choices(evidence, compatible_diagnoses(evidence), final)
                for field, options in choices.items():
                    for option in options:
                        candidate = copy.deepcopy(final)
                        candidate[field] = [option]
                        check_consistency(candidate, evidence)
                final["rejected_hypotheses"] = []
                check_repair_selection(final, choices)
                final["recommendations"] = ["忽略候选，随意修改配置"]
                with self.assertRaises(ValueError):
                    check_repair_selection(final, choices)
                final["diagnosis"] = "insufficient_evidence"
                final["summary"] = summary_choices(evidence)["insufficient_evidence"]
                with self.assertRaisesRegex(ValueError, "明确阶段"):
                    check_repair_selection(final, choices)

    def test_repair_schema_constrains_each_text_field(self):
        _, evidence, final = fixture()
        choices = repair_text_choices(evidence, compatible_diagnoses(evidence), final)
        client = Ollama()
        client.summary_choices = summary_choices(evidence)
        client.repair_text_choices = choices
        stream = Mock()
        stream.__enter__ = Mock(return_value=io.BytesIO(b'{"message": {"content": "{}"}}'))
        stream.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = stream
        from unittest.mock import patch
        with patch("src.agent.urllib.request.build_opener", return_value=opener):
            client.chat([])
        fields = json.loads(opener.open.call_args.args[0].data)["format"]["properties"]
        for field, options in choices.items():
            self.assertEqual(fields[field]["items"]["enum"], options)
        self.assertEqual(fields["recommendations"]["minItems"], 1)

    def test_ollama_schema_constrains_summary_without_restricting_initial_categories(self):
        _, evidence, _ = fixture()
        client = Ollama()
        client.summary_choices = summary_choices(evidence)
        stream = Mock()
        stream.__enter__ = Mock(return_value=io.BytesIO(b'{"message": {"content": "{}"}}'))
        stream.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = stream
        from unittest.mock import patch
        with patch("src.agent.urllib.request.build_opener", return_value=opener):
            client.chat([])
        payload = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(set(payload["format"]["properties"]["summary"]["enum"]), set(summary_choices(evidence).values()))
        self.assertEqual(len(payload["format"]["properties"]["diagnosis"]["enum"]), 7)


if __name__ == "__main__":
    unittest.main()
