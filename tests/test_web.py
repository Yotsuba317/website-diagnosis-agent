"""HTTP-level workbench tests, with all temporary files under the project."""

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import ROOT
from src.web import Workbench, create_server, ollama_host, validate_job


class WebValidationTests(unittest.TestCase):
    def test_local_ollama_host_only(self):
        self.assertEqual(ollama_host("http://127.0.0.1:11434/"), "http://127.0.0.1:11434")
        self.assertEqual(ollama_host("http://localhost"), "http://localhost:11434")
        for value in ("https://127.0.0.1", "http://example.org", "http://user:pass@localhost:11434",
                      "http://localhost:0", "http://localhost/api", "http://localhost?x=1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ollama_host(value)

    def test_invalid_targets_and_parameters_rejected_before_execution(self):
        for payload in ({"url": "file:///test"}, {"url": "http://x:0"}, {"url": "https://x", "timeout": True},
                        {"url": "https://x", "slow_ms": float("inf")}, {"url": "https://x", "mode": "unknown"},
                        {"kind": "demo", "case_id": "unknown"}, {"kind": "evaluate", "cases": []},
                        {"kind": "evaluate", "repeats": True}, {"kind": "evaluate", "repeats": 1.5}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_job(payload)
        self.assertEqual(validate_job({"url": "example.org"})["url"], "https://example.org")


class WebHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary_root = ROOT / "work" / "tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="web-", dir=temporary_root)
        cls.folder = Path(cls.temporary.name).resolve()
        if not cls.folder.is_relative_to(temporary_root.resolve()):
            raise RuntimeError("Temporary test directory escaped the project")
        cls.state = Workbench(cls.folder / "results")
        cls.static = cls.folder / "static"
        cls.static.mkdir()
        (cls.static / "index.html").write_text("<!doctype html><title>NetLens test</title>", encoding="utf-8")
        (cls.static / "app.js").write_text("console.log('ready')", encoding="utf-8")
        cls.server = create_server(0, cls.state, cls.static)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)
        cls.state.close()
        cls.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        data = json.dumps(body).encode("utf-8") if body is not None else None
        connection.request(method, path, data, request_headers)
        response = connection.getresponse()
        content = response.read()
        result = (response.status, dict(response.getheaders()), content)
        connection.close()
        return result

    def wait_job(self, identifier):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.state.get_job(identifier)
            if job["status"] not in ("queued", "running", "cancelling"):
                return job
            time.sleep(0.03)
        self.fail("Job did not reach a terminal state")

    def test_static_and_api_identity(self):
        status, headers, content = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"NetLens", content)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, headers, _ = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        status, _, content = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(content)["cases"]), 7)

    def test_cross_origin_and_unrecognized_host_are_rejected(self):
        status, _, _ = self.request("POST", "/api/jobs", {"kind": "demo", "case_id": "normal"},
                                    {"Origin": "https://unrelated.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/api/bootstrap", headers={"Host": "unrelated.example"})
        self.assertEqual(status, 403)

    def test_traversal_and_invalid_requests_are_rejected(self):
        for path in ("/api/report?path=../../run.py", "/api/report?path=%2e%2e%2fsecret.json", "/../../run.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 400)
        self.assertEqual(self.request("POST", "/api/jobs", {"url": "http://x:0"})[0], 400)
        self.assertEqual(self.request("GET", "/api/jobs/missing")[0], 404)

    def test_real_local_case_progress_report_and_download(self):
        status, _, content = self.request("POST", "/api/jobs", {"kind": "demo", "case_id": "http_error", "engine": "rules"})
        self.assertEqual(status, 202)
        job = self.wait_job(json.loads(content)["id"])
        self.assertEqual(job["status"], "completed", job)
        tools = [event["tool"] for event in job["events"] if event["type"] == "tool"]
        self.assertEqual(tools, ["check_dns", "check_tcp", "check_http"])
        relative = job["report_paths"][0]
        status, _, content = self.request("GET", "/api/report?path=" + relative)
        self.assertEqual(status, 200)
        report = json.loads(content)
        self.assertEqual(report["final"]["diagnosis"], "http_error")
        self.assertEqual(report["evidence"][-1]["http_status"], 503)
        status, headers, content = self.request("GET", "/api/download?path=" + relative + "&format=md")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("HTTP 503", content.decode("utf-8"))
        status, _, content = self.request("GET", "/api/reports")
        self.assertTrue(any(row["path"] == relative for row in json.loads(content)["reports"]))
        restored = Workbench(self.folder / "results")
        try:
            self.assertEqual(restored.get_job(job["id"])["status"], "completed")
        finally:
            restored.close()

    def test_rules_evaluation_is_available_and_clearly_labelled(self):
        job = self.state.submit({"kind": "evaluate", "engine": "rules", "cases": ["normal", "http_error"]})
        result = self.wait_job(job["id"])
        self.assertEqual(result["status"], "completed", result)
        summary = json.loads(self.request("GET", "/api/evaluation?path=" + result["evaluation_path"])[2])
        self.assertEqual(summary["engine"], "rules")
        self.assertEqual(summary["summary"][0]["runs"], 2)
        self.assertEqual(summary["summary"][0]["task_success_rate"], 1)
        self.assertTrue(summary["rules_warning"])
        self.assertEqual(len(result["report_paths"]), 2)

    def test_cancel_waits_for_current_operation_and_prevents_next_step(self):
        started, release = threading.Event(), threading.Event()
        def operation(provider, **options):
            options["on_event"]({"type": "model_started", "request": 1})
            started.set()
            release.wait(4)
            options["on_event"]({"type": "model_finished", "request": 1})
            self.fail("Cancellation should stop before completing diagnosis")
        with patch("src.web.diagnose", side_effect=operation):
            job = self.state.submit({"kind": "demo", "case_id": "normal"})
            self.assertTrue(started.wait(3))
            try:
                status, _, content = self.request("POST", f"/api/jobs/{job['id']}/cancel", {})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(content)["status"], "cancelling")
            finally:
                release.set()
            finished = self.wait_job(job["id"])
            self.assertEqual(finished["status"], "cancelled")
            self.assertEqual(finished["report_paths"], [])
            self.assertIn("model_finished", [event["type"] for event in finished["events"]])

    def test_health_reports_missing_model_service_truthfully(self):
        with patch("src.web.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = ConnectionRefusedError("offline")
            status, _, content = self.request("GET", "/api/health")
        payload = json.loads(content)
        self.assertEqual(status, 200)
        self.assertFalse(payload["connected"])
        self.assertEqual(payload["models"], [])


if __name__ == "__main__":
    unittest.main()
