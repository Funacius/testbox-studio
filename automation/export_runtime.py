"""Runtime loader shared by generated Level 1/2 Selenium/unittest suites."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"CSV needs unique headers: {path}")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"CSV row has a different number of cells from its header: {path}")
        return rows


def package_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Package file must stay inside the exported folder: {name}")
    return path


def load_project(root, level):
    root = Path(root).resolve()
    if level == 1:
        path = root / "level1/program.py"
        spec = importlib.util.spec_from_file_location("_testbox_export_program", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        definitions, settings = module.CASES, module.SETTINGS
    else:
        definitions = json.loads((root / "level2/cases.json").read_text(encoding="utf-8-sig"))
        settings = json.loads((root / "level2/config/site.json").read_text(encoding="utf-8-sig"))
    shared = read_csv(root / "data/shared_variables.csv")
    if any(set(row) != {"Variable", "Value"} or not row["Variable"] for row in shared):
        raise ValueError("Shared variable CSV requires Variable,Value columns and nonempty variable names")
    if len({row["Variable"] for row in shared}) != len(shared):
        raise ValueError("Shared variable CSV contains duplicate variable names")
    settings["variables"] = {row["Variable"]: row["Value"] for row in shared}
    settings["project_dir"] = str(root)
    for name in settings.get("upload_assets", {}).values():
        if not package_file(root, name).is_file():
            raise ValueError(f"Exported upload asset does not exist: {name}")
    records = []
    for entry in definitions:
        if "legacy_data" in entry:
            rows = read_csv(package_file(root, entry["legacy_data"]))
            if len(rows) != 1 or rows[0].get("case_id") != entry["case_id"]:
                raise ValueError(f"Native Gradebook data must retain its single case ID: {entry['case_id']}")
            records.extend(rows)
            continue
        record = dict(entry["record"])
        rows = read_csv(package_file(root, entry["data"]))
        presence = entry.get("presence_column")
        dataset = []
        for row in rows:
            marker = row.pop(presence, "") if presence else ""
            if marker:
                keys = json.loads(marker)
                if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)) or not set(keys) <= set(row):
                    raise ValueError(f"Invalid sparse dataset metadata in {entry['data']}")
                row = {key: value for key, value in row.items() if key in keys}
            dataset.append(row)
        record["dataset_json"] = json.dumps(dataset, ensure_ascii=False)
        records.append(record)
    return dict(records=records, settings=settings)


def cli(root, level, argv=None):
    from automation.runner import main
    parser = argparse.ArgumentParser(description="Exported Selenium/unittest suite: CSV-driven inputs and expected results")
    parser.add_argument("--browser", choices=["chrome", "edge", "opera", "both"], default="chrome")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--base-url")
    parser.add_argument("--output", type=Path, default=Path(root) / "results" / f"level{level}")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--events", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    try:
        project = load_project(root, level)
        if args.case:
            unknown = set(args.case) - {r["case_id"] for r in project["records"]}
            if unknown:
                raise ValueError("Unknown case IDs: " + ", ".join(sorted(unknown)))
            project["records"] = [r for r in project["records"] if r["case_id"] in args.case]
        if args.base_url is not None:
            project["settings"]["base_url"] = args.base_url
        # A temporary snapshot is only an internal runtime detail; CSV is re-read
        # every invocation, and all file paths resolve against the exported root.
        with tempfile.TemporaryDirectory(prefix="testbox-batch-") as directory:
            snapshot = Path(directory) / "project.json"
            snapshot.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
            command = ["--project", str(snapshot), "--level", str(level), "--browser", args.browser, "--output", str(args.output)]
            legacy = Path(root) / "level2/config/gradebook.json"
            if level == 2 and legacy.is_file():
                command += ["--legacy-config", str(legacy)]
            for name in ("headless", "events", "list"):
                if getattr(args, name):
                    command.append("--" + name)
            return main(command)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


def discovery_suite(root, level):
    """Standard unittest discovery path, with browser creation delayed to setUp."""
    from automation.runner import build_tests, preflight
    from gradebook.runner import new_run_id
    project = load_project(root, level)
    preflight(project["records"], project["settings"])
    output = Path(root) / "results" / (f"unittest-level{level}-" + new_run_id())
    output.mkdir(parents=True, exist_ok=False)
    legacy = Path(root) / "level2/config/gradebook.json"
    tests = build_tests(project["records"], project["settings"], [os.environ.get("TESTBOX_BROWSER", "chrome")],
        output, new_run_id(), level, os.environ.get("TESTBOX_HEADLESS") == "1", None, lambda *a, **kw: None,
        legacy_config=legacy if legacy.is_file() else None)
    return unittest.TestSuite(tests)
