"""Native browser recording, picker interception, privacy and replay contracts."""

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from automation.recording import RecordingBuffer, RecorderSession, decode_console
from automation.schema import new_step, script_data, script_record
from studio.templates import builtins, checked_library, instantiate


class RecordingTests(unittest.TestCase):
    def test_console_decoding_and_data_parameterization_preserve_literal_text(self):
        prefix = "__TESTBOX_abc__"
        event = dict(event="step", command="type", target="id=name", value='  0007 ${literal} " \\  ')
        message = "http://local 1:5 " + json.dumps(prefix + json.dumps(event))
        self.assertEqual(decode_console(message, prefix), event)
        self.assertIsNone(decode_console(message, "other"))
        buffer = RecordingBuffer(["recorded_input_1"])
        buffer.ingest(event)
        buffer.ingest({**event, "value": "updated"})
        self.assertEqual(len(buffer.steps), 1)
        self.assertEqual(buffer.variables, {"recorded_input_2": "updated"})
        buffer.ingest(dict(event="step", command="type", target="id=password", value="must-never-be-stored", sensitive=True))
        self.assertEqual(buffer.steps[-1]["value"], "${password}")
        self.assertNotIn("must-never-be-stored", json.dumps(buffer.steps) + json.dumps(buffer.variables))
        buffer.ingest(dict(event="step", command="press_key", target="id=password", value="TAB", sensitive=True))
        self.assertEqual(buffer.steps[-1]["value"], "TAB")

    def test_templates_keep_dataset_cleanup_and_generate_independent_step_ids(self):
        record = script_record("ORIGINAL")
        record.update(actions_json=json.dumps([new_step("click", target="id=run"), new_step("click", target="id=reset", phase="cleanup")]),
            dataset_json='[{"input":"  0007  "}]', notes="Source reference retained")
        template = checked_library({"My reusable case": record})["My reusable case"]
        clone = instantiate(template, "NEW-01")
        self.assertEqual(clone["dataset_json"], record["dataset_json"])
        self.assertEqual(clone["notes"], record["notes"])
        before, after = script_data(record), script_data(clone)
        self.assertEqual([s["phase"] for s in after["steps"]], ["test", "cleanup"])
        self.assertTrue(set(s["id"] for s in before["steps"]).isdisjoint(s["id"] for s in after["steps"]))
        self.assertEqual(template["case_id"], "ORIGINAL")
        self.assertEqual(len(builtins()), 3)


RECORDER_HTML = b'''<!doctype html><meta charset="utf-8"><title>Recorder fixture</title>
<input id="name"><input id="password" type="password">
<button id="save" onclick="document.getElementById('message').textContent=document.getElementById('name').value">Save</button>
<output id="message"></output><input type="checkbox" id="checked">
<select id="kind"><option value="a">Alpha</option><option value="b">Beta</option></select>
<a id="next" href="/next">Next page</a>
<button id="alert" onclick="alert('hello')">Alert</button>
<button id="prompt" onclick="document.getElementById('message').textContent=prompt('name')||'dismissed'">Prompt</button>
'''


class RecorderHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(RECORDER_HTML)
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for actual Chrome recorder verification")
class RecordingBrowserTests(unittest.TestCase):
    def test_alerts_manual_window_close_reopen_and_synthetic_events(self):
        from selenium.common.exceptions import UnexpectedAlertPresentException
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecorderHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = RecorderSession(headless=True)
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            session.open(url)
            session.poll()
            session.set_mode("record")
            session.driver.execute_script("const e=document.getElementById('name');e.value='synthetic';e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));")
            self.assertFalse(any(e.get("event") == "step" for e in session.poll()))
            session.driver.find_element("id", "alert").click()
            try:
                queued = session.poll()
            except UnexpectedAlertPresentException:
                queued = []
            self.assertEqual(session.driver.switch_to.alert.text, "hello")
            step = session.handle_alert("accept_alert")
            self.assertEqual(step["command"], "accept_alert")
            self.assertTrue(any(e.get("command") == "click" for e in queued + session.poll()))
            session.driver.find_element("id", "prompt").click()
            session.handle_alert("accept_alert", "native reply")
            self.assertEqual(session.driver.find_element("id", "message").text, "native reply")
            session.driver.find_element("id", "prompt").click()
            session.handle_alert("dismiss_alert")
            self.assertEqual(session.driver.find_element("id", "message").text, "dismissed")
            old_driver = session.driver
            session.driver.close()
            session.open(url)
            self.assertIsNot(session.driver, old_driver)
            self.assertIsNotNone(session.script_id)
            session.set_mode("record")
            session.driver.find_element("id", "name").send_keys("reopened")
            session.driver.find_element("id", "save").click()
            session.set_mode("idle")
            self.assertTrue(any(e.get("value") == "reopened" for e in session.poll()))
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_builtin_login_template_runs_both_dataset_rows_against_its_documented_demo(self):
        import contextlib
        import io
        from automation.runner import main
        from tools.demo_site import DemoHandler
        server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "project.json"
                record = instantiate(builtins()["Data-driven login (local demo)"], "TEMPLATE-LOGIN")
                project.write_text(json.dumps(dict(records=[record], settings={"base_url": f"http://127.0.0.1:{server.server_port}"})), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(["--project", str(project), "--headless", "--output", str(root / "runs")])
                report = json.loads(next((root / "runs").glob("*/results.json")).read_text(encoding="utf-8"))
                self.assertEqual(code, 0, report)
                self.assertEqual(report["counts"]["PASS"], 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_native_events_picker_does_not_click_and_capture_survives_navigation(self):
        from automation.engine import StepEngine
        from gradebook.browser import close_browser, create_browser
        from selenium.webdriver.common.keys import Keys
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecorderHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = RecorderSession(headless=True)
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            opening = session.open(url)
            session.poll()
            session.set_mode("record")
            literal = '  0007 ${literal} " \\  '
            session.driver.find_element("id", "name").send_keys(literal)
            session.driver.find_element("id", "password").send_keys("private-recorder-secret-93741")
            session.driver.find_element("id", "password").send_keys(Keys.TAB)
            session.driver.find_element("id", "save").click()
            session.driver.find_element("id", "checked").click()
            # Selenium Select synthesizes an untrusted change event in Chrome.
            # Exercise native keyboard selection, as a recorder user would.
            kind = session.driver.find_element("id", "kind")
            kind.send_keys(Keys.END, Keys.TAB)
            self.assertEqual(kind.get_property("value"), "b")
            session.set_mode("idle")
            events = session.poll()
            self.assertNotIn("private-recorder-secret-93741", json.dumps(events))
            self.assertTrue(any(e.get("command") == "check" for e in events))
            self.assertTrue(any(e.get("command") == "select_value" for e in events))
            buffer = RecordingBuffer()
            buffer.add(opening)
            for event in events:
                buffer.ingest(event)
            self.assertIn(literal, buffer.variables.values())
            # Picker intercepts the native click, so Save must not change text.
            session.driver.execute_script("document.getElementById('message').textContent='unchanged'")
            session.set_mode("pick")
            session.driver.find_element("id", "save").click()
            picked = next(e for e in session.poll() if e.get("event") == "picked")
            self.assertIn("id=save", picked["targets"])
            self.assertEqual(session.driver.find_element("id", "message").text, "unchanged")
            # The registered new-document script must keep recording after a link.
            session.set_mode("record")
            session.driver.find_element("id", "next").click()
            session.driver.find_element("id", "name").send_keys("next page")
            session.driver.find_element("id", "save").click()
            session.set_mode("idle")
            after = session.poll()
            self.assertTrue(any(e.get("event") == "document" and e.get("url", "").endswith("/next") for e in after))
            self.assertTrue(any(e.get("command") == "type" and e.get("value") == "next page" for e in after))
            # Replay captured native interactions through the app's actual engine.
            driver = create_browser("chrome", {}, headless=True)
            try:
                with tempfile.TemporaryDirectory() as directory:
                    engine = StepEngine(driver, {}, {**buffer.variables, "password": "different-runtime-password"}, output=directory)
                    engine.run_phase(buffer.steps + [new_step("assert_value", target="id=name", expected=next(s["value"] for s in buffer.steps if s["command"] == "type" and s["target"] == "id=name")),
                        new_step("assert_checked", target="id=checked", expected="true"), new_step("assert_value", target="id=kind", expected="b")], "test")
                    self.assertTrue(all(r["status"] == "PASS" for r in engine.records))
            finally:
                close_browser(driver)
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            thread.join()
