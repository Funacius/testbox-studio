"""Execute declared browser steps without application-specific field names."""

from __future__ import annotations

import math
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from automation.schema import checked_step, locator, resolve
from automation.playback import ExecutionStopped
from automation.privacy import credential_values, redact


class StepEngine:
    def __init__(self, driver, settings, variables=None, output=None, on_event=None, control=None):
        self.driver = driver
        self.settings = settings
        self.variables = dict(settings.get("variables", {}))
        self.variables.update(variables or {})
        self.variables.setdefault("base_url", settings.get("base_url", ""))
        self.output = Path(output or "results")
        self.on_event = on_event or (lambda **event: None)
        self.control = control
        self.records = []
        self.timers = {}
        self.metrics = []
        self.assertions = 0
        self.secret_values = credential_values(self.variables)

    def emit(self, event, **values):
        self.on_event(event=event, **redact(values, self.secret_values))

    def wait(self, timeout):
        return WebDriverWait(self.driver, timeout, poll_frequency=.1)

    def target(self, text):
        by, selector = locator(text, self.settings.get("locators", {}))
        return by, resolve(selector, self.variables)

    def element(self, text, timeout):
        return self.wait(timeout).until(lambda _: self.unique(text, visible=True))

    def unique(self, text, visible=False, clickable=False):
        try:
            elements = self.driver.find_elements(*self.target(text))
            if visible or clickable:
                elements = [e for e in elements if e.is_displayed()]
            if len(elements) > 1:
                raise ValueError(f"Locator matches {len(elements)} elements; use a unique selector: {text}")
            if not elements or clickable and not elements[0].is_enabled():
                return False
            self.highlight(elements[0])
            return elements[0]
        except StaleElementReferenceException:
            return False

    def absent(self, target):
        try:
            return all(not e.is_displayed() for e in self.driver.find_elements(*self.target(target)))
        except StaleElementReferenceException:
            return False

    def run_phase(self, steps, phase):
        errors = []
        for index, source in enumerate(steps, 1):
            step = checked_step(source)
            if step["phase"] != phase:
                continue
            if not step["enabled"] or step["command"] == "note":
                self.records.append(dict(step_id=step["id"], index=index, phase=phase,
                                         command=step["command"], status="SKIP", actual="Reference note" if step["command"] == "note" else "Disabled by user", duration_seconds=0))
                continue
            if self.control and phase != "cleanup":
                self.control(step)
            began = time.perf_counter()
            record = dict(step_id=step["id"], index=index, phase=phase, command=step["command"],
                          target=step["target"], expected=step["expected"], description=step["description"], status="RUNNING")
            self.emit("step_start", **record, message=step["description"] or f"{step['command']} {step['target']}")
            try:
                record["input_value"] = resolve(step["value"], self.variables)
                record["expected"] = resolve(step["expected"], self.variables)
                actual = self.execute(step)
                self.secret_values.update(credential_values(self.variables))
                record.update(status="PASS", actual=actual)
                if step["command"] == "screenshot":
                    record["evidence"] = [actual]
            except Exception as exc:
                record.update(status="FAIL" if isinstance(exc, AssertionError) else "ERROR", actual=f"{type(exc).__name__}: {exc}")
                self.capture(record, index)
                errors.append(exc)
            record["duration_seconds"] = round(time.perf_counter() - began, 6)
            record = redact(record, self.secret_values)
            self.records.append(record)
            self.emit("step_end", **record)
            if errors and phase != "cleanup":
                raise errors[-1]
            delay = float(self.settings.get("slow_ms", 0)) / 1000
            if delay and phase != "cleanup":
                time.sleep(min(delay, 10))
        if errors:
            raise RuntimeError("Cleanup did not complete: " + "; ".join(str(e) for e in errors))

    def capture(self, record, index):
        evidence = self.output / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        stem = f"step-{index:03}-{record['step_id'][:12]}"
        paths = []
        for suffix in ("png", "html"):
            path = evidence / f"{stem}.{suffix}"
            try:
                if suffix == "png":
                    self.driver.save_screenshot(str(path))
                else:
                    path.write_text(self.driver.page_source, encoding="utf-8")
                paths.append(str(path))
            except Exception:
                pass
        record["evidence"] = paths

    @staticmethod
    def boolean(value):
        if value.lower() not in {"true", "false"}:
            raise ValueError("Checkbox/enabled state must be true or false")
        return value.lower() == "true"

    def assertion(self, condition, timeout, description):
        self.assertions += 1
        try:
            self.wait(timeout).until(condition)
        except TimeoutException as exc:
            raise AssertionError(description) from exc

    def execute(self, step):
        cmd = step["command"]
        target, value, expected = (resolve(step[k], self.variables) for k in ("target", "value", "expected"))
        timeout = step["timeout"]
        if cmd == "open":
            url = urljoin(self.variables.get("base_url", "").rstrip("/") + "/", target)
            if urlsplit(url).scheme not in {"http", "https", "file", "data"}:
                raise ValueError("Open requires an http(s), file or data URL")
            self.driver.get(url)
            return "Navigation completed"
        if cmd == "click":
            element = self.wait(timeout).until(lambda _: self.unique(target, clickable=True))
            self.highlight(element)
            element.click()
            return "Clicked element"
        if cmd in {"type", "type_exact"}:
            field = self.element(target, timeout)
            if field.get_attribute("type") == "password" and value:
                self.secret_values.add(value)
            self.highlight(field)
            field.clear()
            if value:
                field.send_keys(value)
            actual = field.get_property("value")
            if cmd == "type_exact" and actual != value:
                raise RuntimeError("Field did not receive the exact input value")
            return dict(message="Entered input value", requested_length=len(value), stored_length=len(actual or ""), browser_normalized=actual != value)
        if cmd in {"select", "select_value"}:
            field = self.element(target, timeout)
            self.highlight(field)
            select = Select(field)
            if cmd == "select":
                select.select_by_visible_text(value)
                if select.first_selected_option.text.strip() != value:
                    raise RuntimeError("Dropdown did not retain the selected label")
            else:
                select.select_by_value(value)
                if select.first_selected_option.get_attribute("value") != value:
                    raise RuntimeError("Dropdown did not retain the selected value")
            return select.first_selected_option.text if cmd == "select" else field.get_property("value")
        if cmd == "check":
            field = self.wait(timeout).until(lambda _: self.unique(target, clickable=True))
            desired = self.boolean(value)
            self.highlight(field)
            if field.is_selected() != desired:
                field.click()
            self.wait(timeout).until(lambda _: self.element(target, timeout).is_selected() == desired)
            return f"Checkbox set to {desired}"
        if cmd in {"wait_visible", "assert_visible"}:
            if cmd.startswith("assert_"):
                self.assertion(lambda _: self.unique(target, visible=True), timeout, f"Element was not visible: {target}")
            else:
                self.element(target, timeout)
            return "Element is visible"
        if cmd in {"wait_absent", "assert_absent"}:
            condition = lambda _: self.absent(target)
            if cmd.startswith("assert_"):
                self.assertion(condition, timeout, f"Element remained visible: {target}")
            else:
                self.wait(timeout).until(condition)
            return "Element is absent or hidden"
        if cmd in {"assert_text", "assert_contains", "assert_value", "assert_checked", "assert_enabled"}:
            actual = [None]
            def condition(_):
                try:
                    element = self.unique(target, visible=True)
                    if not element:
                        return False
                    if cmd == "assert_value":
                        actual[0] = element.get_property("value")
                    elif cmd in {"assert_checked", "assert_enabled"}:
                        actual[0] = element.is_selected() if cmd == "assert_checked" else element.is_enabled()
                        return actual[0] == self.boolean(expected)
                    else:
                        actual[0] = element.text
                    return expected in actual[0] if cmd == "assert_contains" else actual[0] == expected
                except (NoSuchElementException, StaleElementReferenceException):
                    return False
            try:
                self.assertion(condition, timeout, f"{cmd} failed for {target}")
            except AssertionError as exc:
                # The output belongs to the asserted page state, not typed secrets.
                raise AssertionError(f"{cmd}: expected {expected!r}, actual {actual[0]!r}") from exc
            return actual[0]
        if cmd == "assert_url":
            self.assertion(lambda _: self.driver.current_url == expected, timeout, f"URL did not match {expected!r}")
            return self.driver.current_url
        if cmd in {"store_text", "store_value"}:
            from automation.schema import VARIABLE_NAME
            if not VARIABLE_NAME.fullmatch(value):
                raise ValueError("Value must be a valid variable name")
            element = self.element(target, timeout)
            self.variables[value] = element.text if cmd == "store_text" else element.get_property("value")
            return f"Stored variable {value}"
        if cmd == "set_variable":
            from automation.schema import VARIABLE_NAME
            if not VARIABLE_NAME.fullmatch(target):
                raise ValueError("Target must be a valid variable name")
            self.variables[target] = value
            return f"Set variable {target}"
        if cmd == "upload":
            value = self.settings.get("upload_assets", {}).get(value, value)
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = Path(self.settings.get("project_dir", ".")) / path
            if not path.is_file():
                raise ValueError(f"Upload file does not exist: {path}")
            self.wait(timeout).until(lambda _: self.unique(target)).send_keys(str(path.resolve()))
            return "File selected"
        if cmd == "frame":
            frame = self.wait(timeout).until(lambda _: self.unique(target))
            self.wait(timeout).until(EC.frame_to_be_available_and_switch_to_it(frame))
            return "Entered frame"
        if cmd == "default_content":
            self.driver.switch_to.default_content()
            return "Returned to top-level document"
        if cmd == "switch_window":
            if target != "last" and (not target.isdecimal()):
                raise ValueError("Window target must be an index or last")
            index = -1 if target == "last" else int(target)
            minimum = int(value) if value else index + 1 if index >= 0 else 2
            if minimum <= 0:
                raise ValueError("Minimum window count must be positive")
            self.wait(timeout).until(lambda _: len(self.driver.window_handles) >= max(minimum, index + 1))
            self.driver.switch_to.window(self.driver.window_handles[index])
            return "Switched window"
        if cmd == "close_window":
            self.driver.close()
            return "Closed window"
        if cmd in {"accept_alert", "dismiss_alert"}:
            alert = self.wait(timeout).until(EC.alert_is_present())
            if value:
                alert.send_keys(value)
            alert.accept() if cmd == "accept_alert" else alert.dismiss()
            return "Handled JavaScript alert"
        if cmd == "screenshot":
            directory = self.output / "evidence"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"screenshot-{step['id']}.png"
            if not self.driver.save_screenshot(str(path)):
                raise RuntimeError("Browser could not save screenshot")
            return str(path)
        if cmd == "start_timer":
            if target in self.timers:
                raise ValueError(f"Timer already running: {target}")
            self.timers[target] = time.perf_counter()
            return f"Started timer {target}"
        if cmd == "stop_timer":
            if target not in self.timers:
                raise ValueError(f"Timer was not started: {target}")
            elapsed = time.perf_counter() - self.timers.pop(target)
            limit = float(expected) if expected else None
            if limit is not None and (not math.isfinite(limit) or limit <= 0):
                raise ValueError("Timer limit must be a positive finite number in seconds")
            metric = dict(name=target, elapsed_seconds=round(elapsed, 6), maximum_seconds=limit)
            self.metrics.append(metric)
            if limit is not None:
                self.assertions += 1
                if elapsed > limit:
                    raise AssertionError(f"Timer {target}: {elapsed:.6f}s exceeded {limit}s")
            return metric
        raise ValueError(f"Unsupported command: {cmd}")

    def highlight(self, element):
        if self.settings.get("highlight"):
            self.driver.execute_script("const p=window.__testboxActiveOutline,e=arguments[0];if(p&&p[0]===e)return;"
                "if(p){try{p[0].style.outline=p[1]}catch(x){}}window.__testboxActiveOutline=[e,e.style.outline];"
                "e.style.outline='3px solid #ea8a23';", element)
