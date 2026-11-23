"""Moodle Gradebook operations shared by CSV cases in both automation levels.

All application URLs and selectors come from the supplied site configuration.
Cleanup checks the saved run-specific ID before deleting any newly created row.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin

from selenium.common.exceptions import ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException, TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


class TraceLog(list):
    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback

    def append(self, description):
        super().append(description)
        if self.callback:
            self.callback(description)


class GradebookPage:
    def __init__(self, driver, site: dict, assertion, on_step=None):
        self.driver = driver
        self.site = site
        self.assertion = assertion
        self.wait = WebDriverWait(driver, site["timeout"],
                                  poll_frequency=site.get("poll_frequency", 0.1))
        self.baseline: set[str] | None = None
        self.runtime_id = ""
        self.trace = TraceLog(on_step)

    def locator(self, key: str, **values) -> tuple[str, str]:
        by, selector = self.site["locators"][key]
        return by, selector.format(**values)

    def url(self, key: str, **values) -> str:
        fields = {"course_id": self.site["course_id"], **values}
        return urljoin(self.site["base_url"].rstrip("/") + "/",
                       self.site["urls"][key].format(**fields))

    def element(self, key: str, **values):
        return self.wait.until(EC.visibility_of_element_located(self.locator(key, **values)))

    def present(self, key: str, **values):
        return self.driver.find_elements(*self.locator(key, **values))

    def visible(self, key: str, **values) -> bool:
        return any(e.is_displayed() for e in self.present(key, **values))

    def click(self, key: str, **values) -> None:
        """Check visibility/hit testing; use a logged fallback if native click is lost."""
        locator = self.locator(key, **values)
        def attempt(driver):
            try:
                element = EC.element_to_be_clickable(locator)(driver)
                if not element:
                    return False
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});", element)
                exposed = driver.execute_script(
                    "const e=arguments[0],r=e.getBoundingClientRect();"
                    "const t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);"
                    "return !!t && (t===e || e.contains(t));", element)
                if not exposed:
                    return False
                driver.execute_script(
                    "arguments[0].__testboxClickSeen=false;"
                    "arguments[0].addEventListener('click',function(){this.__testboxClickSeen=true},{once:true,capture:true});", element)
                element.click()
                try:
                    delivered = driver.execute_script("return arguments[0].__testboxClickSeen===true", element)
                except WebDriverException as exc:
                    if isinstance(exc, StaleElementReferenceException) or "Node with given id does not belong to the document" in str(exc):
                        return True  # Successful navigation replaced the clicked document.
                    raise
                if not delivered:
                    if not self.site.get("allow_interaction_fallbacks", False):
                        raise RuntimeError(f"Native click was blocked for {key}; check browser-owned dialogs")
                    self.trace.append(f"Native click not delivered; use DOM click fallback for {key}")
                    driver.execute_script("arguments[0].click()", element)
                return True
            except (ElementClickInterceptedException, StaleElementReferenceException):
                return False
        self.wait.until(attempt, f"Control is not exposed for a native click: {key}")

    def describe_response(self) -> str:
        errors = []
        for key in self.site["locators"]:
            if key.startswith("error_"):
                errors.extend(e.text for e in self.present(key) if e.is_displayed() and e.text)
        body = self.driver.find_element(*self.locator("body")).text
        for text in self.site.get("application_error_texts", []):
            if text.casefold() in body.casefold():
                errors.append(text)
        return json.dumps({"url": self.driver.current_url, "messages": errors}, ensure_ascii=False)

    def assert_until(self, predicate, message: str):
        def condition(_):
            try:
                value = predicate()
                if value:
                    return value
                body = self.driver.find_element(*self.locator("body")).text
                for text in self.site.get("application_error_texts", []):
                    if text.casefold() in body.casefold():
                        raise AssertionError(f"{message}; application returned: {text}")
                return False
            except (NoSuchElementException, StaleElementReferenceException):
                return False
        try:
            return self.wait.until(condition)
        except TimeoutException as exc:
            raise AssertionError(f"{message}; actual: {self.describe_response()}") from exc

    def login(self, username: str, password: str) -> None:
        self.trace.append("Log in with the configured teacher account")
        for attempt in range(3):
            try:
                self.driver.get(self.url("login"))
                self.wait.until(lambda _: self.visible("logged_in") or self.visible("username"))
                if not self.visible("logged_in"):
                    self.type_text("username", username)
                    self.type_text("password", password)
                    if not self.visible("logged_in"):
                        self.click("login_button")
                self.wait.until(lambda _: self.visible("logged_in") or self.visible("login_error"))
                if self.visible("login_error"):
                    raise RuntimeError("Teacher login failed; check MOODLE_USERNAME/MOODLE_PASSWORD")
                break
            except WebDriverException as exc:
                if not isinstance(exc, StaleElementReferenceException) and "Node with given id does not belong to the document" not in str(exc):
                    raise
                if attempt == 2:
                    raise
                self.trace.append(f"Login DOM was replaced; retry authentication ({attempt + 2}/3)")
        self.go_gradebook()

    def go_gradebook(self) -> None:
        self.trace.append("Open Gradebook setup")
        self.driver.get(self.url("gradebook"))
        self.element("gradebook_ready")

    def row_ids(self) -> set[str]:
        rows = self.present("manual_rows")
        result = {str(e.get_attribute("data-itemid")) for e in rows}
        if any(not n.isdecimal() for n in result):
            raise RuntimeError("Manual rows do not expose numeric data-itemid values")
        return result

    def begin_case(self, runtime_id: str) -> None:
        self.runtime_id = runtime_id
        self.go_gradebook()
        self.baseline = self.row_ids()
        self.trace.append(f"Recorded {len(self.baseline)} baseline manual rows; runtime ID={runtime_id}")

    def expand_form(self) -> None:
        for link in self.present("expand_all"):
            if link.is_displayed() and "expand" in link.text.casefold():
                link.click()
                break

    def type_text(self, key: str, value: str) -> None:
        if key not in {"username", "password"}:
            self.trace.append(f"Enter {key} = {value!r}")
        field = self.element(key)
        self.wait.until(lambda _: self.enabled(key), f"Field is not editable: {key}")
        field.clear()
        if value:
            field.send_keys(value)
            if field.get_property("value") != value:
                if not self.site.get("allow_interaction_fallbacks", False):
                    raise RuntimeError(f"Native text entry was blocked for {key}; check browser-owned dialogs")
                # Some Windows IME/browser combinations acknowledge SendKeys
                # without inserting its text. Chromium's text-input command
                # emits the input event and avoids that keyboard-layout path.
                self.trace.append(f"Use Chromium text input fallback for {key}")
                field.clear()
                self.driver.execute_script("arguments[0].focus()", field)
                self.driver.execute_cdp_cmd("Input.insertText", {"text": value})
        actual = field.get_property("value")
        if actual != value:
            raise RuntimeError(f"Could not enter exact data in {key}: expected {value!r}, got {actual!r}")
        # Trigger Moodle's change handlers without trimming spaces or changing data.
        self.driver.execute_script(
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true})); arguments[0].blur();", field)

    def select_option(self, key: str, value: str | None = None, label: str | None = None) -> None:
        field = self.element(key)
        self.wait.until(lambda _: self.enabled(key), f"Select is not editable: {key}")
        control = Select(field)
        if label is not None:
            matches = [o for o in control.options if o.text.strip() == label]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one {key} option labelled {label!r}")
            target = matches[0].get_attribute("value")
            control.select_by_visible_text(label)
        else:
            target = str(value)
            control.select_by_value(target)
        if field.get_property("value") != target:
            if not self.site.get("allow_interaction_fallbacks", False):
                raise RuntimeError(f"Native selection was blocked for {key}; check browser-owned dialogs")
            self.trace.append(f"Use DOM selection fallback for {key} = {target}")
            self.driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", field, target)
        self.assertion.assertEqual(field.get_property("value"), target, f"Selected {key}")

    def enabled(self, key: str) -> bool:
        elements = self.present(key)
        return bool(elements) and elements[0].is_enabled() and not elements[0].get_property("readOnly")

    def check_dependencies(self, grade_type: str) -> None:
        states = {"grademin": grade_type == "Value", "grademax": grade_type == "Value",
                  "scaleid": grade_type == "Scale"}
        for key, expected in states.items():
            self.assert_until(lambda k=key, e=expected: bool(self.present(k)) and self.enabled(k) == e,
                              f"Expected {key} enabled={expected} for {grade_type}")

    def set_checkbox(self, key: str, checked: bool, require_initial_off: bool = False) -> None:
        self.trace.append(f"Set checkbox {key} = {checked}")
        element = self.element(key)
        if require_initial_off:
            self.assertion.assertFalse(element.is_selected(), f"{key} should initially be unchecked")
        if element.is_selected() != checked:
            self.click(key)
        self.assert_until(lambda: self.element(key).is_selected() == checked,
                          f"Expected {key} checked={checked}")

    def fill_new(self, inputs: dict) -> None:
        self.trace.append("Open and fill the full New grade item form")
        self.driver.get(self.url("new_item"))
        self.element("itemname")
        self.expand_form()
        self.assert_until(lambda: bool(self.present("scaleid")) and not self.enabled("scaleid"),
                          "Scale should be disabled on a new Value form")
        fields = inputs["fields"]
        self.type_text("itemname", fields["itemname"])
        self.type_text("idnumber", self.runtime_id)
        self.trace.append(f"Select grade type {inputs['grade_type']}")
        self.select_option("gradetype", value=self.site["grade_types"][inputs["grade_type"]])
        self.check_dependencies(inputs["grade_type"])
        if inputs["grade_type"] == "Scale":
            self.trace.append(f"Select scale {inputs['scale']}")
            self.select_option("scaleid", label=inputs["scale"])
        for key, value in fields.items():
            if key not in {"itemname", "idnumber", "aggregationcoef2"}:
                self.type_text(key, value)
        # Enable weight override before filling its dependent weight field.
        # If that field is present, it is filled below after its checkbox changes.
        for key, checked in inputs.get("checks", {}).items():
            self.set_checkbox(key, checked, require_initial_off=True)
        for key, value in inputs.get("selects", {}).items():
            self.trace.append(f"Select {key} = {value}")
            self.select_option(key, value=value)
        for prefix, parts in inputs.get("dates", {}).items():
            self.trace.append(f"Configure {prefix}: {parts}")
            self.set_checkbox(prefix + "_enabled", True, require_initial_off=True)
            for part in ("year", "month", "day", "hour", "minute"):
                self.select_option(prefix + "_" + part, value=parts[part])
        if "aggregationcoef2" in fields:
            self.type_text("aggregationcoef2", fields["aggregationcoef2"])

    def submit(self) -> None:
        self.trace.append("Click Save changes")
        self.click("save")

    def open_item(self, item_id: str) -> None:
        self.trace.append(f"Reopen saved item {item_id}")
        self.driver.get(self.url("edit_item", item_id=item_id))
        self.element("itemname")
        self.expand_form()

    def assert_saved(self, saved: dict) -> None:
        self.assertion.assertEqual(self.element("idnumber").get_property("value"), self.runtime_id,
                                   "Reopened item must have this run's exact ID number")
        self.assertion.assertEqual(Select(self.element("gradetype")).first_selected_option.get_attribute("value"),
                                   self.site["grade_types"][saved["grade_type"]])
        self.check_dependencies(saved["grade_type"])
        for key, expected in saved["fields"].items():
            actual = self.element(key).get_property("value")
            if key == "idnumber":
                expected = self.runtime_id
            if key in {"grademin", "grademax", "gradepass", "aggregationcoef2"}:
                try:
                    self.assertion.assertEqual(Decimal(actual), Decimal(expected), f"Saved {key}")
                except InvalidOperation as exc:
                    raise AssertionError(f"Saved {key} is not numeric: {actual!r}") from exc
            else:
                # Exact comparison preserves empty strings and the three-space case.
                self.assertion.assertEqual(actual, expected, f"Saved {key}")
        if "scale" in saved:
            self.assertion.assertEqual(Select(self.element("scaleid")).first_selected_option.text.strip(), saved["scale"])
        for key, expected in saved["selects"].items():
            self.assertion.assertEqual(Select(self.element(key)).first_selected_option.get_attribute("value"), expected)
        for key, expected in saved["checks"].items():
            self.assertion.assertEqual(self.element(key).is_selected(), expected, f"Saved {key}")
        for prefix, parts in saved["dates"].items():
            self.assertion.assertTrue(self.element(prefix + "_enabled").is_selected())
            for part, expected in parts.items():
                self.assertion.assertEqual(Select(self.element(prefix + "_" + part)).first_selected_option.get_attribute("value"), expected)
        self.trace.append("Verified persisted field values against expected_json from CSV")

    def save_and_verify(self, expected: dict) -> str:
        before = self.row_ids() if self.visible("gradebook_ready") else None
        # Called from a form: capture IDs from the baseline and already created rows.
        if before is None:
            before = set(self.baseline or ())
        self.submit()
        self.assert_until(lambda: self.visible("gradebook_ready"), "Expected successful save and return to Gradebook")
        new_ids = self.row_ids() - before
        self.assertion.assertEqual(len(new_ids), 1, f"Expected exactly one new manual item; got {new_ids}")
        item_id = new_ids.pop()
        self.open_item(item_id)
        self.assert_saved(expected["saved"])
        if expected.get("decimals_disabled"):
            self.assertion.assertFalse(self.enabled("decimals"), "Letter display should disable decimal places")
        if expected.get("hidden_disabled"):
            self.assertion.assertFalse(self.enabled("hidden"), "Hidden until should disable Hidden")
        return item_id

    def expect_validation(self, error: dict) -> None:
        key = "error_" + error["field"]
        self.trace.append(f"Expect inline {error['field']} feedback: {error['text']}")
        self.assert_until(lambda: self.visible(key), f"Expected visible inline error: {error['text']}")
        self.assertion.assertTrue(self.visible("itemname"), "Validation must leave the form available")
        self.assertion.assertFalse(self.visible("gradebook_ready"), "Invalid input must not redirect to setup")
        actual = " ".join(self.element(key).text.split())
        self.assertion.assertEqual(actual, " ".join(error["text"].split()))

    def cancel(self) -> None:
        self.trace.append("Cancel and return to Gradebook")
        self.click("cancel")
        self.element("gradebook_ready")

    def assert_rows(self, expected: set[str]) -> None:
        self.assertion.assertEqual(self.row_ids(), expected, "Manual-item IDs changed unexpectedly")

    def execute(self, workflow: str, inputs: dict, expected: dict) -> None:
        self.fill_new(inputs)
        if expected.get("decimals_disabled"):
            self.assert_until(lambda: not self.enabled("decimals"), "Letter display must disable decimal places")
        if expected.get("hidden_disabled"):
            self.assert_until(lambda: not self.enabled("hidden"), "Hidden until must disable Hidden")
        if workflow == "cancel":
            labels = [e.text.strip() for e in Select(self.element("gradetype")).options]
            self.assertion.assertEqual(labels, expected["grade_type_options"])
            self.cancel()
            self.assert_rows(self.baseline)
        elif workflow == "validation":
            self.submit()
            self.expect_validation(expected["error"])
            self.cancel()
            self.assert_rows(self.baseline)
        elif workflow == "recover":
            self.submit()
            self.expect_validation(expected["error"])
            for key, value in inputs["recovery"].items():
                self.type_text(key, value)
            self.save_and_verify(expected)
        elif workflow == "duplicate":
            original_id = self.save_and_verify(expected)
            self.cancel()
            with_original = self.row_ids()
            second = {**inputs, "fields": {**inputs["fields"], "itemname": inputs["duplicate_name"]}}
            self.fill_new(second)
            self.submit()
            self.expect_validation(expected["error"])
            self.cancel()
            self.assert_rows(with_original)
            self.open_item(original_id)
            self.assert_saved(expected["saved"])
        elif workflow == "create":
            self.save_and_verify(expected)
        else:
            raise ValueError(f"Unknown workflow: {workflow}")

    def cleanup(self) -> None:
        if self.baseline is None:
            return
        self.go_gradebook()
        candidates = self.row_ids() - self.baseline
        for item_id in sorted(candidates):
            self.open_item(item_id)
            owned = self.element("idnumber").get_property("value") == self.runtime_id
            self.cancel()
            if not owned:
                self.trace.append(f"Did not delete unowned new item {item_id}")
                continue
            self.click("row_menu", item_id=item_id)
            self.click("row_delete", item_id=item_id)
            self.click("confirm_delete")
            self.assert_until(lambda i=item_id: not self.present("item_row", item_id=i),
                              f"Cleanup did not remove owned item {item_id}")
            self.trace.append(f"Deleted owned item {item_id}")
        self.assert_rows(self.baseline)

    def capture(self, directory: Path, stem: str) -> list[str]:
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        for suffix in ("png", "html"):
            target = directory / f"{stem}.{suffix}"
            try:
                if suffix == "png":
                    self.driver.save_screenshot(str(target))
                else:
                    target.write_text(self.driver.page_source, encoding="utf-8")
                paths.append(str(target))
            except Exception as exc:
                self.trace.append(f"Evidence capture failed ({suffix}): {type(exc).__name__}")
        return paths
