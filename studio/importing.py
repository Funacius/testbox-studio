"""Explicit spreadsheet mapping; unstructured manual steps become reviewable drafts."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from automation.schema import COMMANDS, new_step, script_record, validate_records
from studio.exchange import _module, _records, _source_workbook, _string

FIELDS = ("case_id", "title", "command", "target", "value", "expected", "phase", "timeout", "enabled", "description", "folder_path")
ALIASES = {"case_id": ("caseid", "testcaseid", "testid", "id"), "title": ("title", "name", "testcasename", "testcase"),
           "command": ("command", "action", "step", "steps", "teststeps", "teststep"),
           "target": ("target", "locator", "element", "selector"), "value": ("value", "input", "inputvalue", "testdata"),
           "expected": ("expected", "expectedresult", "expectedvalue"), "phase": ("phase",),
           "timeout": ("timeout", "timeoutseconds"), "enabled": ("enabled", "active"),
           "description": ("description", "notes"), "folder_path": ("folder", "folderpath", "suite")}


def read_grids(path: Path, encoding="auto", cancelled=None):
    """Return all sheets without silently picking a member's feature."""
    suffix = path.suffix.lower()
    def check_cancel():
        if cancelled is not None and cancelled.is_set():
            raise ValueError("Import canceled")
    check_cancel()
    if suffix == ".csv":
        if encoding == "auto":
            with path.open("rb") as stream:
                prefix = stream.read(4)
            encoding = "utf-32" if prefix in {b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"} else "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        csv.field_size_limit(max(csv.field_size_limit(), 10 * 1024 * 1024))
        with path.open(encoding=encoding, newline="") as stream:
            sample = stream.read(8192)
            stream.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = []
            for i, row in enumerate(csv.reader(stream, dialect)):
                if i % 256 == 0:
                    check_cancel()
                rows.append(row)
            return [dict(name=path.stem, rows=rows, formulas=[], csv_encoding=encoding)]
    if suffix == ".xlsx":
        workbook = _module("openpyxl").load_workbook(path, read_only=True, data_only=False)
        result = []
        try:
            for sheet in workbook:
                rows, formulas = [], []
                for i, row in enumerate(sheet):
                    if i % 256 == 0:
                        check_cancel()
                    rows.append([_string(cell.value) for cell in row])
                    formulas.extend((cell.row, cell.column) for cell in row if cell.data_type == "f")
                result.append(dict(name=sheet.title, rows=rows, formulas=formulas))
        finally:
            workbook.close()
        return result
    if suffix == ".xls":
        workbook = _module("xlrd").open_workbook(str(path), on_demand=True)
        try:
            result = []
            for sheet in workbook.sheets():
                rows = []
                for i in range(sheet.nrows):
                    if i % 256 == 0:
                        check_cancel()
                    rows.append([_string(v) for v in sheet.row_values(i)])
                result.append(dict(name=sheet.name, rows=rows, formulas=[]))
            return result
        finally:
            workbook.release_resources()
    raise ValueError("Choose a CSV, XLS or XLSX file")


def headings(grid, header):
    if header < 0 or header >= len(grid):
        raise ValueError("The selected header row does not exist")
    labels = [str(value).strip() for value in grid[header]]
    if not any(labels):
        raise ValueError("The selected header row is empty")
    populated = [v for v in labels if v]
    if len(set(populated)) != len(populated):
        raise ValueError("The selected header row has duplicate column names")
    return labels


def guess_header(grid):
    def score(row):
        keys = {re.sub(r"[^a-z0-9]", "", str(v).lower()) for v in row}
        return sum(bool(keys & set(values)) for values in ALIASES.values())
    candidates = list(enumerate(grid[:30]))
    if not candidates:
        raise ValueError("This sheet is empty")
    return max(candidates, key=lambda item: (score(item[1]), sum(bool(v) for v in item[1]), -item[0]))[0]


def suggest_mapping(labels):
    normalized = {re.sub(r"[^a-z0-9]", "", label.lower()): label for label in labels if label}
    return {field: next((normalized[name] for name in ALIASES.get(field, ()) if name in normalized), "") for field in FIELDS}


def values_after(grid, header):
    labels = headings(grid, header)
    for number, row in enumerate(grid[header + 1:], header + 2):
        if not any(value != "" and value is not None for value in row):
            continue
        yield number, {label: _string(row[index]) if index < len(row) else "" for index, label in enumerate(labels) if label}


def variable_columns(labels):
    result, used = {}, set()
    for label in labels:
        if not label:
            continue
        key = re.sub(r"[^A-Za-z0-9_]", "_", label).strip("_") or "column"
        if key[0].isdigit():
            key = "column_" + key
        base, count = key, 2
        while key in used:
            key = f"{base}_{count}"
            count += 1
        used.add(key)
        result[label] = key
    return result


def map_dataset(grid, header):
    names = variable_columns(headings(grid, header))
    data = [{names[key]: value for key, value in row.items()} for _, row in values_after(grid, header)]
    if not data:
        raise ValueError("No data rows were found after the header")
    return data, names


def map_steps(grid, header, mapping, continue_ids=True):
    labels = headings(grid, header)
    if not mapping.get("command"):
        raise ValueError("Map an Action / Command / manual Steps column")
    for field, label in mapping.items():
        if label and label not in labels:
            raise ValueError(f"Mapped column is missing: {field} -> {label}")
    cases, ids, current = {}, set(), None
    drafts = 0
    for number, row in values_after(grid, header):
        get = lambda key: row.get(mapping.get(key, ""), "")
        source_id = get("case_id").strip()
        if not mapping.get("case_id"):
            source_id = "IMPORTED-001"
        if source_id:
            current = source_id
        elif not continue_ids or current is None:
            raise ValueError(f"Row {number}: missing Case ID; enable continuation for multi-row cases")
        if current not in cases:
            normalized = re.sub(r"[^A-Za-z0-9_-]", "_", current).strip("_")[:70] or "IMPORTED"
            base, count = normalized, 2
            while normalized in ids:
                normalized = f"{base}-{count}"
                count += 1
            ids.add(normalized)
            record = script_record(normalized)
            record.update(title=get("title").strip() or current, original_case_id=current,
                          source_row=str(number), folder_path=get("folder_path"), notes="Imported steps require review before execution.")
            cases[current] = dict(record=record, actions=[], source=[])
        case = cases[current]
        command = get("command").strip()
        if not command:
            continue
        phase = get("phase").strip().lower() or "test"
        enabled = get("enabled").strip().lower()
        if enabled not in {"", "true", "false", "1", "0", "yes", "no"}:
            raise ValueError(f"Row {number}: Enabled must be true/false, yes/no or 1/0")
        known = command.lower() in COMMANDS
        step = new_step(command.lower() if known else "note", target=get("target"), value=get("value"),
                        expected=get("expected"), description=get("description") if known else command,
                        enabled=known and enabled not in {"false", "0", "no"}, phase=phase,
                        timeout=get("timeout").strip() or 15)
        if not known:
            drafts += 1
        case["actions"].append(step)
        case["source"].append(dict(action=command, expected=get("expected"), source_row=number))
    records = []
    for case in cases.values():
        record = case["record"]
        record["actions_json"] = json.dumps(case["actions"], ensure_ascii=False)
        record["steps_json"] = json.dumps(case["source"], ensure_ascii=False)
        records.append(record)
    if not records:
        raise ValueError("No test cases were found")
    validate_records(records)
    return records, drafts


def import_selection(path, sheet, header, mode, mapping, continue_ids=True):
    if mode == "Project 2 Gradebook":
        if sheet["name"] != "003 - Moodle Grading":
            raise ValueError("Select the 003 - Moodle Grading sheet for this original-workbook adapter")
        return dict(kind="cases", records=_source_workbook(path), drafts=0)
    formulas = [(r, c) for r, c in sheet.get("formulas", []) if r > header]
    if formulas:
        row, col = formulas[0]
        raise ValueError(f"Formula at row {row}, column {col}. Export calculated values as literal text before import.")
    if mode == "Testbox export":
        return dict(kind="cases", records=_records(sheet["rows"][header:], sheet["name"]), drafts=0)
    if mode == "Dataset":
        data, columns = map_dataset(sheet["rows"], header)
        return dict(kind="dataset", dataset=data, columns=columns)
    records, drafts = map_steps(sheet["rows"], header, mapping, continue_ids)
    return dict(kind="cases", records=records, drafts=drafts)
