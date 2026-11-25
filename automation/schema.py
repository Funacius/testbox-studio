"""Portable executable steps; source/manual steps remain separate reference data."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from uuid import uuid4

PHASES = ("setup", "test", "cleanup")
# command: (requires target, requires value, requires expected, help)
COMMANDS = {
    "note": (False, False, False, "Manual reference text; convert to an action before execution."),
    "open": (True, False, False, "Navigate to a URL or a path relative to base_url."),
    "click": (True, False, False, "Wait for an exposed, clickable element and click it."),
    "type": (True, False, False, "Replace a field's text, preserving whitespace and empty strings."),
    "type_exact": (True, False, False, "Replace text and require the field to retain the exact input; normalization/truncation is an execution error."),
    "select": (True, False, False, "Select a dropdown option by visible label."),
    "select_value": (True, False, False, "Select a dropdown option by its HTML value."),
    "check": (True, True, False, "Set a checkbox to true or false."),
    "wait_visible": (True, False, False, "Wait until an element is visible."),
    "wait_absent": (True, False, False, "Wait until no matching element is visible."),
    "assert_text": (True, False, False, "Assert exact visible text against Expected."),
    "assert_contains": (True, False, False, "Assert visible text contains Expected."),
    "assert_value": (True, False, False, "Assert the exact value property against Expected."),
    "assert_visible": (True, False, False, "Assert that an element becomes visible."),
    "assert_absent": (True, False, False, "Assert that an element becomes absent or hidden."),
    "assert_checked": (True, False, True, "Assert checkbox state: Expected is true or false."),
    "assert_enabled": (True, False, True, "Assert enabled state: Expected is true or false."),
    "assert_url": (False, False, True, "Assert the complete current URL against Expected."),
    "store_text": (True, True, False, "Read visible text into the variable named in Value."),
    "store_value": (True, True, False, "Read a field value into the variable named in Value."),
    "set_variable": (True, False, False, "Set the variable named in Target to Value."),
    "upload": (True, True, False, "Send a local file path to an input[type=file]."),
    "frame": (True, False, False, "Enter an iframe located by Target."),
    "default_content": (False, False, False, "Return to the top-level document."),
    "switch_window": (True, False, False, "Switch to a window by zero-based index or 'last'."),
    "accept_alert": (False, False, False, "Accept a JavaScript alert; Value optionally supplies prompt text."),
    "dismiss_alert": (False, False, False, "Dismiss a JavaScript alert."),
    "screenshot": (False, False, False, "Save a browser screenshot to this run's evidence folder."),
    "start_timer": (True, False, False, "Start a named user-observed elapsed-time measurement."),
    "stop_timer": (True, False, False, "Stop the named timer; Expected optionally gives a maximum in seconds."),
}
BY = {"id", "name", "css", "xpath", "link", "partial_link", "tag", "class"}
VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")


def is_script(record: dict) -> bool:
    return record.get("workflow") == "steps"


def new_step(command="open", **values) -> dict:
    return {"id": uuid4().hex, "enabled": True, "phase": "test", "command": command,
            "target": "", "value": "", "expected": "", "timeout": 15,
            "breakpoint": False, "description": "", **values}


def checked_step(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Every executable step must be an object")
    step = {**new_step(), **deepcopy(value)}
    if not isinstance(step["id"], str) or not step["id"]:
        raise ValueError("Every step needs an ID")
    for key in ("enabled", "breakpoint"):
        if not isinstance(step[key], bool):
            raise ValueError(f"Step {key} must be true or false")
    if step["phase"] not in PHASES:
        raise ValueError(f"Unknown step phase: {step['phase']}")
    if step["command"] not in COMMANDS:
        raise ValueError(f"Unknown command: {step['command']}")
    for key in ("target", "value", "expected", "description"):
        if not isinstance(step[key], str):
            raise ValueError(f"Step {key} must be text; preserve numbers as strings")
    try:
        timeout = float(step["timeout"])
    except (ValueError, TypeError) as exc:
        raise ValueError("Step timeout must be a positive number") from exc
    if isinstance(step["timeout"], bool) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise ValueError("Step timeout must be greater than 0 and at most 600 seconds")
    step["timeout"] = timeout
    target, field, expected, _ = COMMANDS[step["command"]]
    for required, key in ((target, "target"), (field, "value"), (expected, "expected")):
        if step["enabled"] and required and not step[key]:
            raise ValueError(f"{step['command']} requires {key}")
    return step


def object_json(record: dict, key: str, default):
    value = record.get(key, "")
    try:
        return json.loads(value) if isinstance(value, str) and value else deepcopy(default) if value == "" else deepcopy(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {key}: {exc}") from exc


def script_data(record: dict, runnable=False) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", str(record.get("case_id", ""))):
        raise ValueError("Case ID must use letters, digits, _ or - (up to 80 characters)")
    if not isinstance(record.get("title"), str) or not record["title"].strip():
        raise ValueError("A test case needs a name")
    raw_steps = object_json(record, "actions_json", [])
    if not isinstance(raw_steps, list):
        raise ValueError("actions_json must be an array of executable steps")
    steps = []
    for index, step in enumerate(raw_steps, 1):
        try:
            steps.append(checked_step(step))
        except ValueError as exc:
            raise ValueError(f"{record['case_id']}, step {index}: {exc}") from exc
    ids = [step["id"] for step in steps]
    if len(set(ids)) != len(ids):
        raise ValueError("Step IDs must be unique within a case")
    variables = object_json(record, "variables_json", {})
    rows = object_json(record, "dataset_json", [{}])
    if not isinstance(variables, dict) or any(not VARIABLE_NAME.fullmatch(str(k)) or not isinstance(v, str) for k, v in variables.items()):
        raise ValueError("Variables must map valid variable names to text values")
    if not isinstance(rows, list) or any(not isinstance(row, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in row.items()) for row in rows):
        raise ValueError("Dataset must be an array of objects containing text values")
    if runnable and (not rows or not any(s["enabled"] and s["phase"] == "test" and s["command"] != "note" for s in steps)):
        raise ValueError(f"{record['case_id']}: add a dataset row and an enabled test step before Run")
    return dict(steps=steps, variables=variables, dataset=rows)


def script_record(case_id: str) -> dict:
    return dict(case_id=case_id, title="New browser test", workflow="steps",
                item_name="", minimum="", maximum="", grade_type="",
                inputs_json="{}", expected_json="{}", expected_result="",
                actions_json="[]", dataset_json="[{}]", variables_json="{}",
                precondition="", notes="", known_defect="", source_sheet="", source_row="")


def validate_records(records: list[dict]) -> None:
    from gradebook.data import parse_rows
    if not isinstance(records, list) or not records:
        raise ValueError("The dataset has no test cases")
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Every test case must be an object")
        if record.get("case_id") in seen:
            raise ValueError(f"Duplicate case ID: {record.get('case_id')}")
        seen.add(record.get("case_id"))
        if is_script(record):
            script_data(record)
        else:
            parse_rows([record])


def resolve(value: str, variables: dict) -> str:
    """Substitute exact values; missing variables are errors, never empty defaults."""
    def replace(match):
        name = match[1]
        if name not in variables:
            raise ValueError(f"Variable is not defined: {name}")
        return str(variables[name])
    return VARIABLE.sub(replace, value)


def locator(target: str, locators: dict) -> tuple[str, str]:
    if target.startswith("@"):
        name = target[1:]
        if name not in locators:
            raise ValueError(f"Locator alias is not defined: {name}")
        entry = locators[name]
        if isinstance(entry, str):
            target = entry
        elif isinstance(entry, dict):
            target = f"{entry.get('by', '')}={entry.get('value', '')}"
        else:
            raise ValueError(f"Invalid locator alias: {name}")
    by, separator, selector = target.partition("=")
    if not separator or by not in BY or not selector:
        raise ValueError("Target needs id=..., css=..., xpath=... or @locator_alias")
    actual = {"css": "css selector", "link": "link text", "partial_link": "partial link text", "tag": "tag name", "class": "class name"}.get(by, by)
    return actual, selector
