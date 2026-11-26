"""Structured control flow validates before execution and keeps loop identity."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from automation.flow import check_budget, flow_plan
from automation.schema import new_step, script_record, script_data


class FlowTests(unittest.TestCase):
    def test_invalid_blocks_and_expansion_are_rejected_before_browser_creation(self):
        from automation.runner import preflight
        record = script_record("FLOW-1")
        for commands in (("else",), ("if_equal", "end_repeat"), ("if_equal", "else", "else", "end_if")):
            record["actions_json"] = json.dumps([new_step(c) for c in commands] + [new_step("click", target="id=x")])
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                preflight([record], {})
        steps = [new_step("repeat", target="i", value="100"), new_step("repeat", target="j", value="100"),
                 new_step("click", target="id=x"), new_step("end_repeat"), new_step("end_repeat")]
        with self.assertRaisesRegex(ValueError, "10000"):
            check_budget(steps, "test", {})

    def test_nested_branches_loops_and_scoped_index_do_not_evaluate_skipped_actions(self):
        from automation.engine import StepEngine
        with tempfile.TemporaryDirectory() as directory:
            engine = StepEngine(None, {}, {"i": "original"}, output=directory)
            steps = [new_step("repeat", target="i", value="3"),
                     new_step("if_equal", target="${i}", expected="2"),
                     new_step("set_variable", target="hit", value="${i}"),
                     new_step("else"), new_step("set_variable", target="miss", value="${i}"),
                     new_step("if_contains", target="abc", expected="z"),
                     new_step("upload", target="id=missing", value="${not_defined}"),
                     new_step("end_if"), new_step("end_if"), new_step("end_repeat")]
            engine.run_phase(steps, "test")
            self.assertEqual(engine.variables, {"i": "original", "base_url": "", "hit": "2", "miss": "3"})
            self.assertTrue(any(r["status"] == "SKIP" for r in engine.records))
            hits = [r for r in engine.records if r["command"] == "set_variable" and r["status"] == "PASS"]
            self.assertEqual([r["loop_path"][0]["iteration"] for r in hits], [1, 2, 3])
            self.assertEqual(len({r["execution"] for r in engine.records}), len(engine.records))

    def test_cleanup_continues_after_error_in_loop_and_restores_scope(self):
        from automation.engine import StepEngine
        with tempfile.TemporaryDirectory() as directory:
            engine = StepEngine(None, {}, output=directory)
            engine.capture = lambda *args: None
            actions = [new_step("repeat", target="i", value="2"),
                       new_step("upload", target="id=missing", value="does-not-exist.txt"),
                       new_step("set_variable", target="completed_iteration", value="${i}"),
                       new_step("end_repeat"), new_step("set_variable", target="cleaned", value="yes")]
            for step in actions:
                step["phase"] = "cleanup"
            with self.assertRaisesRegex(RuntimeError, "Cleanup did not complete"):
                engine.run_phase(actions, "cleanup")
            self.assertEqual(engine.variables["cleaned"], "yes")
            self.assertEqual(engine.variables["completed_iteration"], "2")
            self.assertNotIn("i", engine.variables)
            self.assertEqual(sum(r["status"] == "ERROR" for r in engine.records), 2)

    def test_stop_inside_repeat_restores_index_and_cleanup_remains_available(self):
        from automation.engine import StepEngine
        from automation.playback import ExecutionStopped
        with tempfile.TemporaryDirectory() as directory:
            engine = StepEngine(None, {}, {"iteration": "before"}, output=directory)
            def control(step):
                if step["command"] == "set_variable" and engine.variables["iteration"] == "2":
                    raise ExecutionStopped("Requested stop")
            engine.control = control
            steps = [new_step("repeat", target="iteration", value="3"),
                     new_step("set_variable", target="last", value="${iteration}"), new_step("end_repeat")]
            with self.assertRaises(ExecutionStopped):
                engine.run_phase(steps, "test")
            self.assertEqual(engine.variables["iteration"], "before")
            self.assertEqual(engine.variables["last"], "1")
            engine.run_phase([new_step("set_variable", target="cleanup", value="completed", phase="cleanup")], "cleanup")
            self.assertEqual(engine.variables["cleanup"], "completed")


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for real browser flow/export verification")
class FlowBrowserTests(unittest.TestCase):
    def test_real_browser_repeat_conditions_and_portable_export_on_both_levels(self):
        from tests.test_generic_browser import Handler
        from automation.exporting import export_python
        from automation.runner import main
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = script_record("FLOW-01")
                record["actions_json"] = json.dumps([new_step("open", target="${base_url}", phase="setup"),
                    new_step("repeat", target="iteration", value="${count}"),
                    new_step("type", target="id=name", value="${iteration}"), new_step("click", target="id=save"),
                    new_step("if_equal", target="${iteration}", expected="2"),
                    new_step("assert_text", target="id=message", expected="2"), new_step("else"),
                    new_step("assert_value", target="id=name", expected="${iteration}"), new_step("end_if"),
                    new_step("if_visible", target="id=missing"), new_step("click", target="id=missing"),
                    new_step("else"), new_step("assert_value", target="id=saved", expected="saved"), new_step("end_if"),
                    new_step("end_repeat"), new_step("click", target="id=reset", phase="cleanup")])
                record["dataset_json"] = '[{"count":"3"}]'
                settings = dict(base_url=f"http://127.0.0.1:{server.server_port}")
                export_python(root / "suite.zip", [record], settings)
                with zipfile.ZipFile(root / "suite.zip") as archive:
                    archive.extractall(root / "outside")
                for level in (1, 2):
                    result = subprocess.run([sys.executable, str(root / f"outside/level{level}/test_cases.py"), "--headless"],
                        cwd=root, env={**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8"}, capture_output=True,
                        text=True, encoding="utf-8", timeout=90)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    report = json.loads(next((root / f"outside/results/level{level}").glob("*/results.json")).read_text(encoding="utf-8"))
                    iterations = [r["loop_path"][0]["iteration"] for r in report["results"][0]["step_results"] if r["command"] == "type"]
                    self.assertEqual(iterations, [1, 2, 3])
                # A zero-count test body must not be presented as a successful test.
                empty = {**record, "dataset_json": '[{"count":"0"}]'}
                project = root / "empty.json"
                project.write_text(json.dumps(dict(records=[empty], settings=settings)), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(["--project", str(project), "--headless", "--output", str(root / "empty")])
                report = json.loads(next((root / "empty").glob("*/results.json")).read_text(encoding="utf-8"))
                self.assertEqual(code, 1)
                self.assertEqual(report["counts"]["ERROR"], 1)
                self.assertIn("No test action executed", report["results"][0]["actual"])
                self.assertEqual(report["results"][0]["step_results"][-1]["phase"], "cleanup")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
