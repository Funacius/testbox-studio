"""Opt-in real-browser contract tests against an isolated local web fixture."""

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from automation.schema import new_step, script_record

HTML = b'''<!doctype html><meta charset="utf-8"><title>Testbox fixture</title>
<input id="name"><input type="checkbox" id="checked">
<select id="kind"><option value="a">Alpha</option><option value="b">Beta</option></select>
<button id="save" onclick="document.getElementById('message').textContent=document.getElementById('name').value;document.getElementById('saved').value='saved'">Save</button>
<output id="message"></output><input id="saved" readonly><button id="reset" onclick="document.getElementById('name').value='';document.getElementById('saved').value='';document.getElementById('message').textContent='clean'">Reset</button>
<input id="short" maxlength="3"><span class="duplicate" hidden>hidden first</span><span class="duplicate">visible second</span>
<button class="two">One</button><button class="two">Two</button>
'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for an actual headless browser")
class BrowserContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_dataset_execution_assertion_failure_evidence_and_cleanup(self):
        from automation.runner import main
        record = script_record("FORM-01")
        steps = [new_step("open", target="${base_url}", phase="setup"),
                 new_step("type", target="@name", value="${name}"),
                 new_step("assert_value", target="@name", expected="${name}"),
                 new_step("select", target="id=kind", value="Beta"),
                 new_step("assert_value", target="id=kind", expected="b"),
                 new_step("check", target="id=checked", value="true"),
                 new_step("assert_checked", target="id=checked", expected="true"),
                 new_step("start_timer", target="save"), new_step("click", target="id=save"),
                 new_step("assert_value", target="id=saved", expected="saved"),
                 new_step("stop_timer", target="save", expected="10"),
                 new_step("assert_text", target="id=message", expected="${message}"),
                 new_step("click", target="id=reset", phase="cleanup"),
                 new_step("assert_text", target="id=message", expected="clean", phase="cleanup")]
        record["actions_json"] = json.dumps(steps)
        record["dataset_json"] = json.dumps([{"name": "  exact input  ", "message": "exact input"},
                                               {"name": "0007", "message": "0007"}])
        failing = {**record, "case_id": "FORM-FAIL", "dataset_json": '[{"name":"actual", "message":"wrong"}]'}
        failed_steps = json.loads(failing["actions_json"])
        failed_steps[11]["timeout"] = .5
        failing["actions_json"] = json.dumps(failed_steps)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "snapshot.json"
            project.write_text(json.dumps(dict(records=[record, failing], settings={"base_url": self.url, "locators": {"name": "id=name"}})), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(["--project", str(project), "--headless", "--reuse-browser", "--events", "--output", str(root / "runs")])
            report = json.loads(next((root / "runs").glob("*/results.json")).read_text(encoding="utf-8"))
            self.assertEqual(status, 1)
            self.assertEqual(report["counts"], {"PASS": 2, "FAIL": 1, "ERROR": 0, "SKIP": 0})
            self.assertEqual([r["row_index"] for r in report["results"]], [0, 1, 0])
            failed = report["results"][-1]
            self.assertEqual(failed["cleanup_error"], "")
            self.assertEqual(failed["step_results"][-1]["status"], "PASS")
            self.assertEqual(failed["step_results"][-1]["phase"], "cleanup")
            self.assertTrue(any(Path(p).is_file() for p in failed["evidence"] if p.endswith(".png")))
            self.assertTrue(all(r["metrics"][0]["elapsed_seconds"] < 10 for r in report["results"]))

    def test_imported_example_steps_and_three_dataset_rows_run_as_real_browser_cases(self):
        from automation.runner import main
        from studio.importing import map_dataset, map_steps, read_grids, suggest_mapping
        from tools.demo_site import DemoHandler
        example = Path(__file__).resolve().parents[1] / "examples"
        step_grid = read_grids(example / "login-steps.csv")[0]["rows"]
        records, drafts = map_steps(step_grid, 0, suggest_mapping(step_grid[0]))
        self.assertEqual(drafts, 0)
        data, _ = map_dataset(read_grids(example / "login-data.csv")[0]["rows"], 0)
        records[0]["dataset_json"] = json.dumps(data)
        server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "snapshot.json"
                project.write_text(json.dumps(dict(records=records, settings={"base_url": f"http://127.0.0.1:{server.server_port}"})), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    status = main(["--project", str(project), "--headless", "--output", str(root / "runs")])
                report = json.loads(next((root / "runs").glob("*/results.json")).read_text(encoding="utf-8"))
                self.assertEqual(status, 0)
                self.assertEqual(report["counts"], {"PASS": 3, "FAIL": 0, "ERROR": 0, "SKIP": 0})
                self.assertEqual(len(report["results"]), 3)
                self.assertTrue(all(len(r["step_results"]) == 5 for r in report["results"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_browser_normalization_and_multiple_matches_do_not_produce_false_passes(self):
        from automation.engine import StepEngine
        from gradebook.browser import close_browser, create_browser
        driver = create_browser("chrome", {"window": [1440, 900]}, headless=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                engine = StepEngine(driver, {"base_url": self.url}, output=directory)
                engine.run_phase([new_step("open", target="${base_url}"),
                                  new_step("type", target="id=short", value="abcdef"),
                                  new_step("assert_value", target="id=short", expected="abc")], "test")
                self.assertTrue(engine.records[1]["actual"]["browser_normalized"])
                with self.assertRaises(AssertionError):
                    engine.run_phase([new_step("assert_absent", target="css=.duplicate", timeout=.2)], "test")
                with self.assertRaisesRegex(ValueError, "matches 2"):
                    engine.run_phase([new_step("click", target="css=.two", timeout=.2)], "test")
                with self.assertRaisesRegex(RuntimeError, "exact input"):
                    engine.run_phase([new_step("type_exact", target="id=short", value="abcdef")], "test")
        finally:
            close_browser(driver)


if __name__ == "__main__":
    unittest.main()
