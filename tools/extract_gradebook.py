"""Extract Feature 003 from the Project 2 workbook without opening Moodle.

The workbook is the source of inputs and expected results. This deliberately
strict parser supports its English manual-step format, not arbitrary prose.
Unknown steps abort extraction instead of silently losing test coverage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "Pro2/CC01.G03-krecorder/Testcase-CC01.G03.xlsx"
SHEET = "003 - Moodle Grading"


def read_cases(path: Path, sheet: str) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        cases: list[dict] = []
        current = None
        for row_no, cells in enumerate(workbook[sheet].iter_rows(values_only=True), 1):
            values = ["" if x is None else str(x) for x in cells[:8]]
            values += [""] * (8 - len(values))
            if re.fullmatch(r"TC-003-\d{3}", values[0]):
                current = dict(case_id=values[0], title=values[1],
                               description=values[2], precondition=values[3],
                               notes=values[7], source_row=row_no, steps=[])
                cases.append(current)
            if current and values[5]:
                current["steps"].append(dict(row=row_no, action=values[5],
                                             expected=values[6]))
        expected_ids = [f"TC-003-{n:03}" for n in range(1, 37)]
        if [c["case_id"] for c in cases] != expected_ids:
            raise ValueError("Expected exactly TC-003-001 through TC-003-036, in order")
        return cases
    finally:
        workbook.close()


def convert(case: dict, relation_message: str) -> dict:
    inputs = {"fields": {}, "selects": {}, "checks": {}, "dates": {}}
    expected = {"saved": {"fields": {}, "selects": {}, "checks": {}, "dates": {}}}
    workflow = "create"
    name_entries = []
    for step in case["steps"]:
        action, result = step["action"], step["expected"]
        match = re.fullmatch(r"Enter Item name = '(.*)' and ID number = (.+)\.", action)
        if match:
            name_entries.append((match[1], match[2]))
            continue
        match = re.fullmatch(r"Enter exactly (three ASCII spaces|256 uppercase X characters).*ID number = (.+)\.", action)
        if match:
            name_entries.append((" " * 3 if match[1].startswith("three") else "X" * 256, match[2]))
            continue
        match = re.fullmatch(r"Select Grade type Value; clear and enter Minimum grade '(.*)' and Maximum grade '(.*)'\.", action)
        if match:
            inputs["grade_type"] = "Value"
            # The duplicate scenario repeats these same values on its second form.
            bounds = {"grademin": match[1], "grademax": match[2]}
            if "grademin" in inputs["fields"] and any(inputs["fields"][k] != v for k, v in bounds.items()):
                raise ValueError(f"{case['case_id']}: different bounds in repeated form")
            inputs["fields"].update(bounds)
            continue
        match = re.fullmatch(r"Select Grade type Scale and choose (.+)\.", action)
        if match:
            inputs["grade_type"] = "Scale"
            inputs["scale"] = match[1]
            continue
        if action == "Select Grade type Text.":
            inputs["grade_type"] = "Text"
            continue
        match = re.fullmatch(r"Enter (iteminfo|gradepass|aggregationcoef2) = '(.*)'\.", action)
        if match:
            inputs["fields"][match[1]] = match[2]
            continue
        match = re.fullmatch(r"Set (display|decimals) to option value (\d+)\.", action)
        if match:
            inputs["selects"][match[1]] = match[2]
            continue
        match = re.fullmatch(r"Enable (hidden|locked|weightoverride|aggregationcoef)\.", action)
        if match:
            inputs["checks"][match[1]] = True
            continue
        match = re.fullmatch(r"Click Save changes and inspect validation next to (\w+)\.", action)
        if match:
            workflow = "validation"
            marker = "a visible inline message says: "
            if marker not in result:
                raise ValueError(f"{case['case_id']}: missing exact validation message")
            expected["error"] = {"field": match[1], "text": result.split(marker, 1)[1]}
            continue
        match = re.fullmatch(r"Submit invalid bounds \[.*\], verify the visible relation error, then correct Min=(.+) and Max=(.+) on the same form\.", action)
        if match:
            workflow = "recover"
            inputs["recovery"] = {"grademin": match[1], "grademax": match[2]}
            expected["error"] = {"field": "grademin", "text": relation_message}
            continue
        if action == "Inspect the complete Grade type option list.":
            workflow = "cancel"
            if result != "Exactly Value, Scale and Text are offered; None is absent.":
                raise ValueError("Grade-type option expectations changed; review extractor")
            expected["grade_type_options"] = ["Value", "Scale", "Text"]
            continue
        if action == "Submit a second item with the same ID number.":
            workflow = "duplicate"
            match = re.fullmatch(r"Visible ID number feedback says (.*); the duplicate is not saved\.", result)
            if not match:
                raise ValueError("Duplicate-ID expectation changed")
            expected["error"] = {"field": "idnumber", "text": match[1]}
            continue
        if action.startswith("Enable Hidden until and Lock after. Set both to "):
            match = re.fullmatch(r"Enable Hidden until and Lock after\. Set both to (\d+) December (\d+), (\d+):(\d+), Asia/Bangkok\.", action)
            if not match:
                raise ValueError("Date step format changed; review extractor")
            day, year, hour, minute = match.groups()
            date = dict(day=day, month="12", year=year, hour=hour, minute=str(int(minute)))
            inputs["dates"] = {"hiddenuntil": date, "locktime": date.copy()}
            expected["hidden_disabled"] = True
            continue
        if action == "Inspect decimal places after choosing Letter display.":
            expected["decimals_disabled"] = True
            continue
        # These are implemented by the shared create/verify/cleanup workflow.
        if action.startswith(("Open Gradebook setup", "Open the full New grade item form",
                              "Click Save changes. After redirecting", "Click Cancel to leave",
                              "Click Cancel and return", "Cancel to return to setup;",
                              "Open the original item by its recorded ID.",
                              "Recheck ", "Inspect both enabled date-time values after reopening.")):
            continue
        raise ValueError(f"{case['case_id']} row {step['row']}: unsupported action: {action}")

    if not name_entries or "grade_type" not in inputs:
        raise ValueError(f"{case['case_id']}: incomplete inputs")
    inputs["fields"].update(itemname=name_entries[0][0], idnumber=name_entries[0][1])
    if workflow == "duplicate":
        if len(name_entries) != 2 or name_entries[0][1] != name_entries[1][1]:
            raise ValueError("Duplicate-ID case must use the same ID on two forms")
        inputs["duplicate_name"] = name_entries[1][0]
    elif len(name_entries) != 1:
        raise ValueError("Unexpected second item-name entry")

    saved = expected["saved"]
    saved["grade_type"] = inputs["grade_type"]
    saved["fields"] = inputs["fields"].copy()
    saved["selects"] = inputs["selects"].copy()
    saved["checks"] = inputs["checks"].copy()
    saved["dates"] = inputs["dates"].copy()
    if "scale" in inputs:
        saved["scale"] = inputs["scale"]
    if workflow == "recover":
        saved["fields"].update(inputs["recovery"])
    if case["title"] == "Normalize an empty Minimum grade to zero":
        saved["fields"]["grademin"] = "0"
    # This CSV column is the oracle read by assertions at runtime.
    return dict(case_id=case["case_id"], title=case["title"], workflow=workflow,
                item_name=inputs["fields"]["itemname"],
                minimum=inputs["fields"].get("grademin", ""),
                maximum=inputs["fields"].get("grademax", ""),
                grade_type=inputs["grade_type"],
                inputs_json=json.dumps(inputs, ensure_ascii=False),
                expected_json=json.dumps(expected, ensure_ascii=False),
                expected_result="\n".join(f"{n}. {s['expected']}" for n, s in enumerate(case["steps"], 1)),
                precondition=case["precondition"], notes=case["notes"],
                known_defect="F003-D01" if "F003-D01" in case["notes"] else "",
                source_sheet=SHEET, source_row=case["source_row"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--sheet", default=SHEET)
    args = parser.parse_args()
    source = args.source.resolve()
    cases = read_cases(source, args.sheet)
    relation_messages = {s["expected"].split("a visible inline message says: ", 1)[1]
                         for c in cases for s in c["steps"]
                         if s["action"].endswith("validation next to grademin.")
                         and "minimum must be lower" in s["expected"]}
    if len(relation_messages) != 1:
        raise ValueError("Cannot identify one relation-error message in workbook")
    converted = [convert(c, next(iter(relation_messages))) for c in cases]
    for level in ("level1", "level2"):
        target = ROOT / level / "data/gradebook_cases.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(converted[0]))
            writer.writeheader()
            writer.writerows(converted)
    provenance = ROOT / "data"
    provenance.mkdir(exist_ok=True)
    (provenance / "excel_snapshot.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (provenance / "source_manifest.json").write_text(json.dumps({
        "source_workbook": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sheet": args.sheet, "case_count": len(cases), "owner": "Bùi Quốc Thái",
        "execution_status_at_extraction": "NOT RUN", "source": "Excel manual steps and expected results",
        "mapping_notes": [
            "Structured saved-field assertions expand the workbook's reopen-and-verify instructions.",
            "Recovery error wording is taken from relation-validation cases in the same sheet.",
            "Run IDs namespace the source ID number at execution; names and bounds stay unchanged.",
            "Empty minimum normalization is specified by TC-003-022's title.",
        ]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(converted)} cases to Level 1 and Level 2; no browser or tests started.")


if __name__ == "__main__":
    main()
