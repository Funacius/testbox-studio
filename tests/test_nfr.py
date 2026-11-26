"""NFR matrix, measurement semantics and real exported-level execution."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path

from automation.nfr import checked_nfr, measured_records, summarize
from automation.schema import new_step, script_record


def fixture():
    record = script_record("NFR-01")
    record.update(title="Save and wait for persisted state", actions_json=json.dumps([
        new_step("open", target="${base_url}", phase="setup"),
        new_step("type", target="id=name", value="0007"),
        new_step("click", target="id=save", id="save"),
        new_step("assert_value", target="id=saved", expected="saved", id="ready"),
        new_step("click", target="id=reset", phase="cleanup")]))
    return record


class NfrTests(unittest.TestCase):
    def test_matrix_requires_distinct_browsers_and_finite_limits(self):
        record = fixture()
        with self.assertRaisesRegex(ValueError, "two different"):
            checked_nfr({"browsers": ["chrome"]}, [record], "compatibility")
        with self.assertRaisesRegex(ValueError, "distinct"):
            checked_nfr({"browsers": ["chrome", "chrome"]}, [record], "compatibility")
        for limit in ("nan", "inf", 0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                checked_nfr({"measurements": {"NFR-01": dict(start="save", end="ready", maximum_seconds=limit)}}, [record], "elapsed")
        with self.assertRaisesRegex(ValueError, "in order"):
            checked_nfr({"measurements": {"NFR-01": dict(start="ready", end="save", maximum_seconds=1)}}, [record], "elapsed")

    def test_timer_snapshot_preserves_authored_steps_and_measures_selected_interval(self):
        record = fixture()
        before = deepcopy(record)
        config = checked_nfr({"measurements": {"NFR-01": dict(start="save", end="ready", maximum_seconds=2)}}, [record], "elapsed")
        measured = measured_records([record], config)
        steps = json.loads(measured[0]["actions_json"])
        self.assertEqual([s["command"] for s in steps], ["open", "type", "start_timer", "click", "assert_value", "stop_timer", "click"])
        self.assertEqual(steps[2]["target"], steps[5]["target"])
        self.assertEqual(record, before)
        self.assertEqual(steps[5]["expected"], "2.0")

    def test_summary_does_not_accept_missing_or_failing_samples(self):
        config = dict(levels=[1, 2], browsers=["chrome"], repetitions=2,
            measurements={"NFR-01": dict(maximum_seconds=1, timer_name="nfr_elapsed_NFR-01")})
        rows = [dict(level=level, browser="chrome", case_id="NFR-01", row_index=0, status="PASS",
            metrics=[dict(name="nfr_elapsed_NFR-01", elapsed_seconds=value)]) for level in (1, 2) for value in (.1, .2)]
        result = summarize(rows, config, "elapsed", 4)
        self.assertTrue(result["successful"])
        self.assertAlmostEqual(result["groups"][0]["median_seconds"], .15)
        self.assertEqual(result["groups"][0]["p95_seconds"], .2)
        rows[-1]["metrics"] = []
        self.assertFalse(summarize(rows, config, "elapsed", 4)["successful"])
        self.assertFalse(summarize(rows[:-1], config, "elapsed", 4)["successful"])
        self.assertFalse(summarize([], config, "elapsed", 4, True)["successful"])


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for real browser NFR matrix")
class NfrBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_generic_browser import Handler
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def run_matrix(self, directory, kind, config, *, stop=False, slow=0):
        root = Path(directory)
        project = root / "project.json"
        project.write_text(json.dumps(dict(records=[fixture()], settings=dict(base_url=f"http://127.0.0.1:{self.server.server_port}", nfr=config, slow_ms=slow))), encoding="utf-8")
        command = [sys.executable, "-m", "automation.nfr", "--project", str(project), "--kind", kind, "--headless", "--output", str(root)]
        if stop:
            request = root / "stop.request"
            request.touch()
            command += ["--stop-file", str(request)]
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True,
            text=True, encoding="utf-8", timeout=180)
        report = next(root.glob("nfr-*/results.json"), None)
        return result, json.loads(report.read_text(encoding="utf-8")) if report else None

    def test_compatibility_executes_chrome_and_edge_through_both_level_programs(self):
        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_matrix(directory, "compatibility", dict(levels=[1, 2], browsers=["chrome", "edge"], repetitions=1))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(report["successful"])
            self.assertEqual(report["counts"]["PASS"], 4)
            self.assertEqual({(r["level"], r["browser"]) for r in report["results"]}, {(1, "chrome"), (1, "edge"), (2, "chrome"), (2, "edge")})
            self.assertEqual({r["capabilities"]["browserName"].lower() for r in report["results"]}, {"chrome", "microsoftedge"})

    def test_elapsed_samples_limits_and_stop_are_reported_without_false_pass(self):
        config = dict(levels=[1, 2], browsers=["chrome"], repetitions=2,
            measurements={"NFR-01": dict(start="save", end="ready", maximum_seconds=10)})
        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_matrix(directory, "elapsed", config)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(report["nfr"]["successful"])
            self.assertEqual(len(report["results"]), 4)
            self.assertTrue(all(len(g["samples_seconds"]) == 2 for g in report["nfr"]["groups"]))
        config.update(repetitions=1)
        config["measurements"]["NFR-01"]["maximum_seconds"] = .000001
        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_matrix(directory, "elapsed", config)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(report["counts"]["FAIL"], 2)
            self.assertFalse(report["successful"])
            self.assertTrue(all(r["step_results"][-1]["phase"] == "cleanup" for r in report["results"]))
        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_matrix(directory, "elapsed", config, stop=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(report["metadata"]["stopped"])
            self.assertFalse(report["successful"])
            self.assertEqual(report["counts"]["NOT_RUN"], 2)
            self.assertEqual(report["metadata"]["completed_executions"], 0)
            self.assertEqual({r["level"] for r in report["results"]}, {1, 2})
            self.assertTrue(all(r["status"] == "NOT_RUN" for r in report["results"]))
        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_matrix(directory, "elapsed", config, slow=100)
            self.assertEqual(result.returncode, 2)
            self.assertIsNone(report)
            self.assertIn("step delay to 0", result.stderr)
