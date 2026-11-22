"""Read CSV without stripping significant whitespace or coercing numbers."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    workflow: str
    inputs: dict
    expected: dict
    expected_result: str
    precondition: str
    known_defect: str


def load_cases(path: Path) -> list[Case]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return parse_rows(rows)


def parse_rows(rows: list[dict]) -> list[Case]:
    """Validate in memory too, so the desktop editor uses the runner's schema."""
    if not rows:
        raise ValueError("The dataset has no test cases")
    cases = []
    seen = set()
    for row in rows:
        case_id = row["case_id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", case_id):
            raise ValueError(f"Invalid case ID: {case_id!r}. Use letters, digits, _ and - (up to 80 characters).")
        if case_id in seen:
            raise ValueError(f"Duplicate case ID: {case_id}")
        seen.add(case_id)
        if row["workflow"] not in {"create", "validation", "cancel", "recover", "duplicate"}:
            raise ValueError(f"Unsupported workflow in {case_id}")
        inputs, expected = json.loads(row["inputs_json"]), json.loads(row["expected_json"])
        if not isinstance(inputs, dict) or not isinstance(expected, dict):
            raise ValueError(f"Inputs and expected results must be JSON objects: {case_id}")
        for key in ("fields", "selects", "checks", "dates"):
            if not isinstance(inputs.get(key), dict):
                raise ValueError(f"inputs_json.{key} must be an object: {case_id}")
        if row["grade_type"] not in {"Value", "Scale", "Text"}:
            raise ValueError(f"Unsupported grade type: {case_id}")
        if row["grade_type"] != "Value":
            inputs["fields"].pop("grademin", None)
            inputs["fields"].pop("grademax", None)
        if row["grade_type"] == "Scale" and not inputs.get("scale"):
            raise ValueError(f"A scale name is required: {case_id}")
        if row["workflow"] in {"create", "recover", "duplicate"}:
            saved = expected.get("saved", {})
            if not isinstance(saved, dict) or not all(isinstance(saved.get(k), dict) for k in ("fields", "selects", "checks", "dates")):
                raise ValueError(f"A complete expected_json.saved object is required: {case_id}")
            if saved.get("grade_type") not in {"Value", "Scale", "Text"}:
                raise ValueError(f"Expected saved grade_type is missing: {case_id}")
        if row["workflow"] in {"validation", "recover", "duplicate"}:
            error = expected.get("error", {})
            if error.get("field") not in {"grademin", "grademax", "scaleid", "gradepass", "idnumber"} or not error.get("text"):
                raise ValueError(f"An inline error field and text are required: {case_id}")
        if row["workflow"] == "recover" and not inputs.get("recovery"):
            raise ValueError(f"Recovery fields are required: {case_id}")
        if row["workflow"] == "duplicate" and not inputs.get("duplicate_name"):
            raise ValueError(f"Duplicate item name is required: {case_id}")
        if row["workflow"] == "cancel" and not expected.get("grade_type_options"):
            raise ValueError(f"Expected grade type options are required: {case_id}")
        # Readable columns are authoritative for the common data-driven inputs.
        inputs["fields"]["itemname"] = row["item_name"]
        inputs["grade_type"] = row["grade_type"]
        if inputs["grade_type"] == "Value":
            inputs["fields"].update(grademin=row["minimum"], grademax=row["maximum"])
        if not row["expected_result"] or not expected:
            raise ValueError(f"Missing expected results in {case_id}")
        cases.append(Case(case_id, row["title"], row["workflow"], inputs, expected,
                          row["expected_result"], row["precondition"], row["known_defect"]))
    return cases
