"""Transient native-input readiness is awaited; exact data and errors remain strict."""

import tempfile
import unittest
import os
from urllib.parse import quote

from selenium.common.exceptions import ElementNotInteractableException, TimeoutException


class Field:
    def __init__(self, readonly=False):
        self.value, self.calls, self.readonly = "", 0, readonly
    def is_displayed(self):
        return True
    def is_enabled(self):
        return True
    def get_property(self, key):
        return self.readonly if key == "readOnly" else self.value
    def get_attribute(self, key):
        return "password" if key == "type" else None
    def clear(self):
        self.value = ""
    def send_keys(self, value):
        self.calls += 1
        if self.calls == 1:
            raise ElementNotInteractableException("Transient input layout")
        self.value = value


class Driver:
    def __init__(self, field):
        self.field = field
    def find_element(self, *args):
        return self.field
    def find_elements(self, *args):
        return [self.field]
    def execute_script(self, *args):
        pass


class InputReadinessTests(unittest.TestCase):
    def test_native_gradebook_waits_for_input_without_changing_the_data(self):
        from gradebook.page import GradebookPage
        field = Field()
        page = GradebookPage(Driver(field), dict(timeout=.4, poll_frequency=.01, locators={"password": ["id", "password"]}), self)
        page.type_text("password", "private test credential")
        self.assertEqual(field.value, "private test credential")
        self.assertEqual(field.calls, 2)
        self.assertIn("Wait for stable native input: password", page.trace)
        self.assertNotIn("private test credential", "\n".join(page.trace))

    def test_generic_input_retry_is_bounded_and_readonly_cannot_pass(self):
        from automation.engine import StepEngine
        from automation.schema import new_step
        with tempfile.TemporaryDirectory() as directory:
            field = Field()
            engine = StepEngine(Driver(field), {}, output=directory)
            engine.run_phase([new_step("type_exact", target="id=password", value="  exact  ", timeout=.4)], "test")
            self.assertEqual(field.value, "  exact  ")
            self.assertEqual(engine.records[-1]["status"], "PASS")
            self.assertNotIn("  exact  ", str(engine.records))
            readonly = StepEngine(Driver(Field(True)), {}, output=directory)
            readonly.capture = lambda *args: None
            with self.assertRaises(TimeoutException):
                readonly.run_phase([new_step("type", target="id=password", value="input", timeout=.05)], "test")
            self.assertEqual(readonly.records[-1]["status"], "ERROR")


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for native login initialization")
class LoginInitializationTests(unittest.TestCase):
    def test_async_password_replacement_finishes_before_native_credentials_are_entered(self):
        from gradebook.browser import create_browser, close_browser
        from gradebook.page import GradebookPage
        html = '''<input id="username"><input id="password" type="password">
        <button id="login" onclick="window.submitted=[document.querySelector('#username').value,document.querySelector('#password').value];document.querySelector('#logged').hidden=false">Log in</button>
        <span id="logged" hidden>Logged in</span><span id="error" hidden>Error</span>
        <script>window.M={util:{pending_js:['password-template']}};
        setTimeout(()=>{document.querySelector('#password').outerHTML='<input id="password" type="password">';M.util.pending_js=[]},600);</script>'''
        driver = create_browser("chrome", {}, headless=True)
        try:
            site = dict(timeout=5, locators={key: ["id", value] for key, value in {
                "username": "username", "password": "password", "login_button": "login",
                "logged_in": "logged", "login_error": "error"}.items()})
            page = GradebookPage(driver, site, self)
            page.url = lambda key: "data:text/html;charset=utf-8," + quote(html)
            page.go_gradebook = lambda: None
            enter = page.type_text
            def checked_enter(key, value):
                self.assertEqual(driver.execute_script("return M.util.pending_js.length"), 0)
                enter(key, value)
            page.type_text = checked_enter
            page.login("teacher-fixture", "fixture-password")
            self.assertEqual(driver.execute_script("return window.submitted"), ["teacher-fixture", "fixture-password"])
            self.assertNotIn("fixture-password", str(page.trace))
        finally:
            close_browser(driver)
