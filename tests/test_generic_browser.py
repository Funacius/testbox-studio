"""Opt-in real-browser contract tests against an isolated local web fixture."""

import contextlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
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
<input id="password" type="password"><input id="disabled" disabled value="locked">
<iframe id="frame" srcdoc="<input id='inside'><span id='frameMessage'>Frame ready</span>"></iframe>
<input id="file" type="file" onchange="document.getElementById('filename').textContent=this.files[0].name"><span id="filename"></span>
<button id="spawn" onclick="window.open('/other','_blank')">New window</button>
<button id="alert" onclick="alert('hello')">Alert</button>
<button id="prompt" onclick="document.getElementById('promptResult').textContent=prompt('name')||'dismissed'">Prompt</button><span id="promptResult"></span>
'''


class Handler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

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

    def test_locator_probe_counts_visible_matches_and_restores_previous_highlight(self):
        from automation.locators import probe_locator
        from gradebook.browser import close_browser, create_browser
        driver = create_browser("chrome", {"window": [1440, 900]}, headless=True)
        try:
            driver.get(self.url)
            result = probe_locator(driver, "@field", {"field": "css=#${field}"}, {"field": "name"})
            self.assertEqual((result["status"], result["visible_matches"]), ("MATCH", 1))
            self.assertEqual(driver.execute_script("return document.getElementById('name').style.outlineWidth"), "3px")
            result = probe_locator(driver, "css=.two", {})
            self.assertEqual((result["status"], result["visible_matches"]), ("AMBIGUOUS", 2))
            self.assertEqual(driver.execute_script("return document.getElementById('name').style.outlineWidth"), "")
            self.assertEqual(probe_locator(driver, "id=missing", {})["status"], "NOT FOUND")
            self.assertEqual(driver.execute_script("return document.getElementById('message').textContent"), "")
        finally:
            close_browser(driver)

    def test_frame_window_alert_upload_stored_variables_and_explicit_screenshot(self):
        from automation.engine import StepEngine
        from gradebook.browser import close_browser, create_browser
        driver = create_browser("chrome", {"window": [1440, 900]}, headless=True)
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                upload = root / "sample.txt"
                upload.write_text("Upload fixture", encoding="utf-8")
                engine = StepEngine(driver, {"base_url": self.url, "highlight": True}, output=root)
                steps = [new_step("open", target="${base_url}"), new_step("wait_visible", target="id=name"),
                    new_step("set_variable", target="content", value="saved-text"),
                    new_step("type_exact", target="id=name", value="${content}"), new_step("click", target="id=save"),
                    new_step("store_text", target="id=message", value="from_page"),
                    new_step("store_value", target="id=name", value="from_input"),
                    new_step("assert_text", target="id=message", expected="${from_page}"),
                    new_step("assert_value", target="id=name", expected="${from_input}"),
                    new_step("assert_contains", target="id=message", expected="saved"),
                    new_step("select_value", target="id=kind", value="b"), new_step("assert_value", target="id=kind", expected="b"),
                    new_step("check", target="id=checked", value="true"), new_step("check", target="id=checked", value="false"),
                    new_step("assert_checked", target="id=checked", expected="false"),
                    new_step("assert_enabled", target="id=disabled", expected="false"),
                    new_step("wait_absent", target="id=missing"), new_step("assert_absent", target="id=missing"),
                    new_step("frame", target="id=frame"), new_step("type", target="id=inside", value="inside"),
                    new_step("assert_value", target="id=inside", expected="inside"),
                    new_step("default_content"), new_step("assert_visible", target="id=name"),
                    new_step("upload", target="id=file", value=str(upload)), new_step("assert_text", target="id=filename", expected="sample.txt"),
                    new_step("click", target="id=alert"), new_step("accept_alert"),
                    new_step("click", target="id=prompt"), new_step("accept_alert", value="given"), new_step("assert_text", target="id=promptResult", expected="given"),
                    new_step("click", target="id=prompt"), new_step("dismiss_alert"), new_step("assert_text", target="id=promptResult", expected="dismissed"),
                    new_step("click", target="id=spawn"), new_step("switch_window", target="last", value="2"),
                    new_step("assert_url", expected="${base_url}/other"), new_step("close_window"), new_step("switch_window", target="0", value="1"),
                    new_step("assert_url", expected="${base_url}/"), new_step("screenshot")]
                engine.run_phase(steps, "test")
                self.assertEqual(len(engine.records), len(steps))
                self.assertTrue(all(r["status"] == "PASS" for r in engine.records))
                self.assertTrue(Path(engine.records[-1]["evidence"][0]).is_file())
                self.assertGreaterEqual(engine.assertions, 12)
        finally:
            close_browser(driver)

    def test_typed_credentials_are_masked_in_textual_failure_reports_and_logs(self):
        from automation.runner import main
        secret = "private-demo-credential-92731"
        record = script_record("PRIVACY-1")
        record["actions_json"] = json.dumps([new_step("open", target="${base_url}"),
            new_step("type", target="id=password", value=secret),
            new_step("assert_value", target="id=password", expected="wrong", timeout=.2)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project.json"
            project.write_text(json.dumps(dict(records=[record], settings={"base_url": self.url})), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                status = main(["--project", str(project), "--headless", "--events", "--output", str(root / "runs")])
            self.assertEqual(status, 1)
            output = next((root / "runs").iterdir())
            for name in ("results.json", "results.csv", "steps.csv", "report.html", "unittest.log"):
                self.assertNotIn(secret, (output / name).read_text(encoding="utf-8-sig"), name)
            self.assertNotIn(secret, stream.getvalue())
            self.assertIn("[REDACTED]", (output / "results.json").read_text(encoding="utf-8"))

    def test_child_runner_breakpoint_single_step_and_stop_preserve_cleanup(self):
        from automation.playback import write_control
        record = script_record("CONTROL-01")
        steps = [new_step("open", target="${base_url}", phase="setup"),
                 new_step("type", target="id=name", value="actual"),
                 new_step("click", target="id=save", breakpoint=True),
                 new_step("assert_value", target="id=saved", expected="saved"),
                 new_step("click", target="id=reset", phase="cleanup", breakpoint=True),
                 new_step("assert_text", target="id=message", expected="clean", phase="cleanup")]
        record["actions_json"] = json.dumps(steps)
        record["dataset_json"] = '[{},{}]'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, control = root / "snapshot.json", root / "control.json"
            project.write_text(json.dumps(dict(records=[record], settings={"base_url": self.url})), encoding="utf-8")
            write_control(control, "run", 0)
            process = subprocess.Popen([sys.executable, "-u", "-m", "automation.runner", "--project", str(project),
                       "--control-file", str(control), "--headless", "--events", "--output", str(root / "runs")],
                       cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8")
            events, lines = queue.Queue(), []
            def read():
                for line in process.stdout:
                    lines.append(line)
                    if line.startswith("@@GRADEBOOK_EVENT "):
                        events.put(json.loads(line[len("@@GRADEBOOK_EVENT "):]))
                events.put({"event": "eof"})
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            def until(predicate):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    event = events.get(timeout=max(.1, deadline - time.monotonic()))
                    if event["event"] == "eof":
                        self.fail("Runner ended before expected playback event: " + "".join(lines)[-4000:])
                    if predicate(event):
                        return event
                self.fail("Expected playback event did not arrive")
            try:
                paused = until(lambda e: e["event"] == "playback" and e["state"] == "paused")
                self.assertEqual(paused["step_id"], steps[2]["id"])
                write_control(control, "next", 1)
                click = until(lambda e: e["event"] == "step_end" and e["step_id"] == steps[2]["id"])
                self.assertEqual(click["status"], "PASS")
                paused = until(lambda e: e["event"] == "playback" and e["state"] == "paused")
                self.assertEqual(paused["step_id"], steps[3]["id"])
                write_control(control, "stop", 2)
                self.assertEqual(process.wait(timeout=30), 1)
                reader.join(timeout=3)
                report = json.loads(next((root / "runs").glob("*/results.json")).read_text(encoding="utf-8"))
                self.assertTrue(report["metadata"]["stopped"])
                self.assertFalse(report["successful"])
                self.assertEqual(report["metadata"]["planned_executions"], 2)
                self.assertEqual(report["counts"], {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 1})
                result = report["results"][0]
                self.assertEqual(result["cleanup_error"], "")
                self.assertEqual([s["status"] for s in result["step_results"] if s["phase"] == "cleanup"], ["PASS", "PASS"])
                self.assertNotIn(steps[3]["id"], [s["step_id"] for s in result["step_results"]])
            finally:
                if process.poll() is None:
                    write_control(control, "stop", 99)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)
                reader.join(timeout=3)
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
