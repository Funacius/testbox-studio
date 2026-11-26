"""Owned Chrome recorder/picker, using native interaction events and reviewable steps."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from automation.schema import checked_step, new_step


def decode_console(message, prefix):
    """Decode Chrome's quoted console argument, rather than unescaping by replacement."""
    start = message.find('"' + prefix)
    if start < 0:
        return None
    argument, _ = json.JSONDecoder().raw_decode(message[start:])
    if not isinstance(argument, str) or not argument.startswith(prefix):
        return None
    result = json.loads(argument[len(prefix):])
    return result if isinstance(result, dict) else None


class RecordingBuffer:
    def __init__(self, occupied=()):
        self.steps, self.variables, self.occupied = [], {}, set(occupied)
        self.last_input = None

    def add(self, step):
        step = checked_step(step)
        self.steps.append(step)
        self.last_input = None
        return step

    def input_variable(self, value):
        index = 1
        while f"recorded_input_{index}" in self.occupied:
            index += 1
        name = f"recorded_input_{index}"
        self.occupied.add(name)
        self.variables[name] = value
        return name

    def ingest(self, event):
        if event.get("event") == "warning":
            return self.add(new_step("note", enabled=False, description="Recorder review required: " + str(event.get("message", ""))))
        if event.get("event") != "step":
            return None
        command, target = event.get("command"), event.get("target")
        if command not in {"click", "type", "select_value", "check", "upload", "press_key"} or not isinstance(target, str):
            raise ValueError("Recorder produced an unsupported action")
        value = event.get("value", "")
        if not isinstance(value, str):
            raise ValueError("Recorded input must be text")
        if command == "type" and not event.get("sensitive"):
            if self.last_input and self.last_input[0] == target:
                variable = self.last_input[1]
                self.variables[variable] = value
                return self.steps[-1]
            variable = self.input_variable(value)
            step = self.add(new_step(command, target=target, value="${" + variable + "}"))
            self.last_input = (target, variable)
            return step
        if event.get("sensitive") and command == "type":
            value = "${password}"
        if self.steps and command in {"check", "select_value", "type"} and self.steps[-1]["command"] == command and self.steps[-1]["target"] == target and self.steps[-1]["value"] == value:
            return self.steps[-1]
        return self.add(new_step(command, target=target, value=value))


class RecorderSession:
    def __init__(self, settings=None, *, headless=False):
        self.settings, self.headless = deepcopy(settings or {}), headless
        self.driver, self.script_id, self.mode = None, None, "idle"
        self.prefix = "__TESTBOX_" + uuid4().hex + "__"
        self.script = Path(__file__).with_name("recorder.js").read_text(encoding="utf-8")

    def source(self, mode):
        return self.script.replace("__TESTBOX_PREFIX__", json.dumps(self.prefix)).replace("__TESTBOX_MODE__", json.dumps(mode))

    def open(self, url):
        from urllib.parse import urlsplit
        if urlsplit(url).scheme not in {"http", "https", "file"}:
            raise ValueError("Recorder URL must use http://, https:// or file://")
        if self.driver is not None:
            try:
                if not self.driver.window_handles:
                    raise ValueError("Recorder window was closed")
            except Exception:
                try:
                    self.close()
                except Exception:
                    self.driver = None
        if self.driver is None:
            from gradebook.browser import create_browser
            self.driver = create_browser("chrome", {**self.settings, "browser_logging": True,
                "command_timeout": 15, "page_load_timeout": 15}, self.headless)
            self.set_mode("idle")
        self.driver.get(url)
        return new_step("open", target=url)

    def set_mode(self, mode):
        if mode not in {"idle", "record", "pick"}:
            raise ValueError("Unknown recorder mode")
        if self.driver is None:
            raise ValueError("Open a recorder browser first")
        if self.script_id:
            self.driver.execute_cdp_cmd("Page.removeScriptToEvaluateOnNewDocument", {"identifier": self.script_id})
        self.script_id = self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": self.source(mode)})["identifier"]
        self.driver.execute_script(self.source(mode))
        self.driver.execute_script("return window.__testboxRecorder.setMode(arguments[0])", mode)
        self.mode = mode

    def poll(self):
        if self.driver is None:
            return []
        events = []
        for entry in self.driver.get_log("browser"):
            try:
                event = decode_console(entry.get("message", ""), self.prefix)
            except (ValueError, TypeError):
                continue
            if event is not None:
                events.append(event)
        if any(event.get("event") == "picked" for event in events):
            self.set_mode("idle")
        return events

    def close(self):
        if self.driver is not None:
            from gradebook.browser import close_browser
            try:
                close_browser(self.driver)
            finally:
                self.driver = None
