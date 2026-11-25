"""Lossless CSV / XLS / XLSX exchange, including folder order and source steps."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

from automation.schema import validate_records as parse_rows

CORE_COLUMNS = ["case_id", "title", "workflow", "item_name", "minimum", "maximum",
                "grade_type", "inputs_json", "expected_json", "expected_result",
                "precondition", "notes", "known_defect", "source_sheet", "source_row"]
EXTRA_COLUMNS = ["folder_path", "folder_path_json", "order", "steps_json"]
REQUIRED = set(CORE_COLUMNS[:10])


def _module(name: str):
    try:
        return __import__(name)
    except ImportError as exc:
        raise ValueError(f"Missing {name}. Install app dependencies with: python -m pip install -r requirements.txt") from exc


def _string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _records(grid: list[list], label: str) -> list[dict]:
    header_row = next((i for i, row in enumerate(grid[:30])
                       if REQUIRED <= {str(x).strip() for x in row if x is not None}), None)
    if header_row is None:
        raise ValueError(f"{label}: no data-driven header found. Required columns: {', '.join(sorted(REQUIRED))}")
    headers = [str(x).strip() if x is not None else "" for x in grid[header_row]]
    populated = [h for h in headers if h]
    if len(set(populated)) != len(populated):
        raise ValueError(f"{label}: duplicate column headings")
    records = []
    for index, values in enumerate(grid[header_row + 1:], header_row + 2):
        if not any(value not in (None, "") for value in values):
            continue
        row = {key: _string(values[n]) if n < len(values) else ""
               for n, key in enumerate(headers) if key}
        for key in CORE_COLUMNS:
            row.setdefault(key, "")
        try:
            parse_rows([row])
            if row.get("steps_json"):
                steps = json.loads(row["steps_json"])
                if not isinstance(steps, list) or any(not isinstance(s, dict) or "action" not in s or "expected" not in s for s in steps):
                    raise ValueError("steps_json must be a list of action/expected objects")
            if row.get("folder_path_json"):
                path = json.loads(row["folder_path_json"])
                if not isinstance(path, list) or any(not isinstance(s, str) or not s.strip() for s in path):
                    raise ValueError("folder_path_json must be a list of folder names")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{label}, row {index}: {exc}") from exc
        records.append(row)
    # Cross-row ID uniqueness is checked before anything is added to the workspace.
    parse_rows(records)
    return records


def _source_workbook(path: Path) -> list[dict]:
    from tools.extract_gradebook import SHEET, convert, read_cases
    cases = read_cases(path, SHEET)
    messages = {s["expected"].split("a visible inline message says: ", 1)[1]
                for c in cases for s in c["steps"]
                if s["action"].endswith("validation next to grademin.")
                and "minimum must be lower" in s["expected"]}
    if len(messages) != 1:
        raise ValueError("The Project 2 workbook's relation-error wording needs review")
    rows = [convert(c, next(iter(messages))) for c in cases]
    for row, case in zip(rows, cases):
        row["steps_json"] = json.dumps(case["steps"], ensure_ascii=False)
    return [{k: _string(v) for k, v in row.items()} for row in rows]


def read_table(path: Path, sheet_name: str | None = None) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(8192)
            stream.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            return _records(list(csv.reader(stream, dialect)), path.name)
    if suffix == ".xlsx":
        workbook = _module("openpyxl").load_workbook(path, read_only=True, data_only=False)
        try:
            if not sheet_name and "003 - Moodle Grading" in workbook.sheetnames:
                workbook.close()
                return _source_workbook(path)
            sheets = [workbook[sheet_name]] if sheet_name else list(workbook)
            errors = []
            for sheet in sheets:
                grid = []
                for row in sheet:
                    if any(cell.data_type == "f" for cell in row):
                        raise ValueError(f"{sheet.title}: formulas are not supported as test data; use literal text values")
                    grid.append([cell.value for cell in row])
                try:
                    return _records(grid, sheet.title)
                except ValueError as exc:
                    errors.append(str(exc))
            raise ValueError("\n".join(errors))
        finally:
            workbook.close()
    if suffix == ".xls":
        workbook = _module("xlrd").open_workbook(str(path), on_demand=True)
        try:
            sheets = [workbook.sheet_by_name(sheet_name)] if sheet_name else workbook.sheets()
            errors = []
            for sheet in sheets:
                try:
                    return _records([sheet.row_values(i) for i in range(sheet.nrows)], sheet.name)
                except ValueError as exc:
                    errors.append(str(exc))
            raise ValueError("\n".join(errors))
        finally:
            workbook.release_resources()
    raise ValueError("Choose a .csv, .xls or .xlsx data file")


def write_table(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("There are no test cases to export")
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".xls", ".xlsx"}:
        raise ValueError("Export extension must be .csv, .xls or .xlsx")
    columns = list(dict.fromkeys(CORE_COLUMNS + EXTRA_COLUMNS + [k for r in rows for k in r]))
    records = [{key: _string(row.get(key, "")) for key in columns} for row in rows]
    if suffix != ".csv" and any(len(v) > 32767 for row in records for v in row.values()):
        raise ValueError("Excel cells are limited to 32,767 characters; export this dataset as CSV")
    if suffix == ".xls" and (len(records) > 65535 or len(columns) > 256):
        raise ValueError("This dataset exceeds XLS row/column limits; choose XLSX or CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(suffix=suffix, dir=path.parent)
    os.close(descriptor)
    temp = Path(temporary)
    try:
        if suffix == ".csv":
            with temp.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(records)
        elif suffix == ".xlsx":
            module = _module("openpyxl")
            from openpyxl.styles import Alignment, Font, PatternFill
            workbook = module.Workbook()
            sheet = workbook.active
            sheet.title = "Test cases"
            for i, values in enumerate([columns] + [[r[k] for k in columns] for r in records], 1):
                for j, value in enumerate(values, 1):
                    cell = sheet.cell(i, j, value)
                    cell.data_type = "s"  # Preserve text, including leading '=' and zeroes.
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                    if i == 1:
                        cell.font = Font(bold=True, color="FFFFFF")
                        cell.fill = PatternFill("solid", fgColor="25324A")
            sheet.freeze_panes = "D2"
            sheet.auto_filter.ref = sheet.dimensions
            for col in sheet.columns:
                sheet.column_dimensions[col[0].column_letter].width = 28
            workbook.save(temp)
            workbook.close()
        else:
            module = _module("xlwt")
            workbook = module.Workbook(encoding="utf-8")
            sheet = workbook.add_sheet("Test cases")
            for i, values in enumerate([columns] + [[r[k] for k in columns] for r in records]):
                for j, value in enumerate(values):
                    sheet.write(i, j, value)
            sheet.set_panes_frozen(True)
            sheet.set_horz_split_pos(1)
            workbook.save(str(temp))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
