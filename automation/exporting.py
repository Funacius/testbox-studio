"""Build portable Selenium/unittest submissions without the desktop application."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import pprint
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from automation.schema import COMMANDS, VARIABLE, VARIABLE_NAME, is_script, script_data, validate_records
from automation.readiness import checked_settings

ROOT = Path(__file__).resolve().parents[1]
SETTING_KEYS = {"base_url", "locators", "window", "timeout", "page_load_timeout", "command_timeout",
                "page_load_strategy", "poll_frequency", "opera_chromium_version", "highlight", "slow_ms",
                "check_connection", "course_id"}
VALUE_COMMANDS = {"type", "type_exact", "select", "select_value", "check", "upload", "accept_alert", "switch_window"}
EXPECTED_COMMANDS = {"assert_text", "assert_contains", "assert_value", "assert_checked", "assert_enabled", "assert_url", "stop_timer"}
ELEMENT_COMMANDS = {name for name, info in COMMANDS.items() if info[0]} - {
    "open", "set_variable", "switch_window", "start_timer", "stop_timer"}


def csv_text(rows, columns):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + stream.getvalue()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def compile_project(records, settings, project_dir):
    """Lift literal inputs/oracles into CSV while retaining variable precedence."""
    validate_records(records)
    checked_settings(settings)
    if any(not VARIABLE_NAME.fullmatch(str(key)) or not isinstance(value, str) for key, value in settings.get("variables", {}).items()):
        raise ValueError("Shared variables must map valid names to text values")
    program, datasets, locators = [], {}, deepcopy(settings.get("locators", {}))
    assets, uploads, warnings = {}, {}, []
    for original in records:
        record = deepcopy(original)
        case_id = record["case_id"]
        if not is_script(record):
            columns = list(record)
            datasets[f"data/case-{case_id}.csv"] = csv_text([record], columns)
            program.append(dict(case_id=case_id, workflow=record["workflow"], legacy_data=f"data/case-{case_id}.csv"))
            continue
        data = script_data(record, runnable=True)
        rows = [{**data["variables"], **row} for row in data["dataset"]]
        used = set(settings.get("variables", {})) | set(data["variables"])
        used |= {key for row in rows for key in row}
        used |= {m[1] for step in data["steps"] for field in ("target", "value", "expected") for m in VARIABLE.finditer(step[field])}
        used |= {step["target"] for step in data["steps"] if step["command"] == "set_variable"}
        used |= {step["value"] for step in data["steps"] if step["command"] in {"store_text", "store_value"}}
        # Retain sparse-row semantics: absent keys fall back to shared/env defaults;
        # an explicitly empty cell overrides them. Dense tables need no metadata.
        for index, step in enumerate(data["steps"], 1):
            command = step["command"]
            if command in ELEMENT_COMMANDS and step["target"] and not step["target"].startswith("@"):
                alias = f"export_{case_id}_{index}"
                while alias in locators:
                    alias += "_"
                locators[alias] = step["target"]
                step["target"] = "@" + alias
            for field, commands in (("value", VALUE_COMMANDS), ("expected", EXPECTED_COMMANDS)):
                literal = step[field]
                if command not in commands or VARIABLE.search(literal) or (field == "expected" and command == "stop_timer" and not literal):
                    continue
                variable = f"step_{index}_{field}"
                while variable in used:
                    variable += "_"
                used.add(variable)
                for row in rows:
                    row[variable] = literal
                step[field] = "${" + variable + "}"
            if command == "upload" and step["enabled"]:
                for row in rows:
                    from automation.schema import resolve
                    try:
                        source_value = resolve(step["value"], {**settings.get("variables", {}), **row})
                    except ValueError:
                        warnings.append(f"{case_id}, step {index}: upload path supplied at runtime; provide that file on the target machine.")
                        continue
                    source = Path(source_value).expanduser()
                    source = source if source.is_absolute() else Path(project_dir) / source
                    if not source.is_file():
                        raise ValueError(f"{case_id}, step {index}: upload file does not exist: {source}")
                    if source.stat().st_size > 20 * 1024 * 1024:
                        raise ValueError(f"{case_id}: upload file exceeds 20 MiB; supply it at runtime using an environment variable instead")
                    payload = source.read_bytes()
                    name = f"assets/{hashlib.sha256(payload).hexdigest()[:16]}/{source.name}"
                    assets[name] = payload
                    uploads[source_value] = name
        columns = list(dict.fromkeys(key for row in rows for key in row))
        presence = "__testbox_present"
        while presence in used:
            presence += "_"
        sparse = any(set(row) != set(columns) for row in rows)
        if sparse:
            rows = [{**row, presence: json.dumps(list(row))} for row in rows]
            columns.append(presence)
        # A zero-column CSV needs a row marker to retain its number of iterations.
        if not columns:
            rows = [{presence: "[]"} for _ in rows]
            columns = [presence]
            sparse = True
        dataset = f"data/case-{case_id}.csv"
        datasets[dataset] = csv_text(rows, columns)
        record.update(actions_json=json_text(data["steps"]), dataset_json="[]", variables_json="{}")
        program.append(dict(record=record, data=dataset, presence_column=presence if sparse else None))
    config = {k: deepcopy(v) for k, v in settings.items() if k in SETTING_KEYS}
    config["locators"] = locators
    config["upload_assets"] = uploads
    datasets["data/shared_variables.csv"] = csv_text(
        [{"Variable": k, "Value": v} for k, v in settings.get("variables", {}).items()], ["Variable", "Value"])
    return program, config, datasets, assets, list(dict.fromkeys(warnings))


ENTRY = '''"""Exported Selenium/unittest suite. Data and expected values are read from CSV."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))
from automation.export_runtime import cli, discovery_suite

LEVEL = {level}

def load_tests(loader, tests, pattern):
    return discovery_suite(ROOT, LEVEL)

if __name__ == "__main__":
    raise SystemExit(cli(ROOT, LEVEL))
'''

GUIDE = '''# Exported Testbox Selenium/unittest suite

Requires Python 3.12+, a supported installed browser, and a reachable test site.
This ZIP includes its Python runtime; Testbox Studio and the original repository
are not required. Selenium Manager may need internet to obtain a matching driver.

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe level1/test_cases.py --headless
.\\.venv\\Scripts\\python.exe level2/test_cases.py --headless
```

Use --browser chrome|edge|opera|both, --base-url URL, --output DIR, --list,
--case CASE-ID (repeatable), or omit --headless for a visible temporary browser.
Only levels included during export are available. CLI runs use unittest and write
JSON/CSV/HTML reports with evidence. Standard discovery is also supported:
`python -m unittest level1.test_cases -v` (visible browser by default; set
TESTBOX_HEADLESS=1 for background discovery). Discovery uses unittest's own
reporting; use test_cases.py directly for the full HTML/CSV report.

- Level 1: URLs, locators and action definitions live in level1/program.py.
  Edit that Python file to change the test program.
- Level 2: action definitions live in level2/cases.json and site items in
  level2/config/site.json. Changes to those files require no Python edits.
- Each data/case-CASE-ID.csv is read at run time, including input and expected values.
  Literal step inputs/oracles appear in step_N_value / step_N_expected columns.
  You can edit or add data rows. Keep text values, empty strings and spaces exact.
- data/shared_variables.csv supplies defaults. Precedence is shared defaults,
  TESTBOX_VAR_name environment variables, then per-row values. Reserved base_url,
  run_id, case_id and runtime_id are set by the runner.
- Sparse datasets have an internal __testbox_present column listing keys present
  in that row. Keep it to distinguish missing from explicitly empty cells; leave
  blank on a new row to use all the data columns on that row.
- Upload files present at export are copied into assets/. Runtime/environment
  upload paths must exist on the target machine. See manifest.json for warnings.
- Native Gradebook cases retain their original fields and expected JSON in CSV;
  they still need Moodle, its fixture and an editing teacher. Level 1 uses
  level1/settings.py; Level 2 uses level2/config/gradebook.json.
- Run-configuration credentials are not copied by the GUI export. Values already
  saved in your dataset or project variables ARE included; review data before
  sharing. You can supply credentials through TESTBOX_VAR_username/password
  (general steps) or MOODLE_USERNAME/PASSWORD (native Gradebook).
- Slow playback and interactive pauses affect elapsed timers. Case duration is
  not a response-time benchmark. Exported batch runs ignore step breakpoints.

The package preserves assertions. An intentionally invalid expected value must
produce FAIL; do not replace expected data just to turn a failing case green.
'''


def export_python(path, records, settings, *, levels=(1, 2), project_dir=None, legacy_site=None):
    """Stage everything first, then atomically publish a reviewable ZIP."""
    levels = tuple(sorted(set(levels)))
    if not levels or any(type(level) is not int or level not in (1, 2) for level in levels):
        raise ValueError("Choose Level 1, Level 2 or both")
    program, config, datasets, assets, warnings = compile_project(records, settings, project_dir or ROOT)
    has_legacy = any(not is_script(record) for record in records)
    if has_legacy and legacy_site is None:
        from gradebook.config import load_site
        legacy_site = load_site(2)
    if has_legacy:
        legacy_site = deepcopy(legacy_site)
        for key in ("base_url", "course_id", "window", "page_load_timeout", "command_timeout"):
            if key in settings:
                legacy_site[key] = settings[key]
    files = {"README.md": GUIDE, "requirements.txt": "selenium==4.53.0\n", **datasets, **assets}
    for package in ("automation", "gradebook"):
        for source in sorted((ROOT / package).glob("*.py")):
            if source.name == "exporting.py":
                continue
            files[f"runtime/{package}/{source.name}"] = source.read_bytes()
    for level in levels:
        files[f"level{level}/__init__.py"] = ""
        files[f"level{level}/test_cases.py"] = ENTRY.format(level=level)
        if level == 1:
            files["level1/program.py"] = ('"""Level 1: edit URLs, locator aliases and action definitions here."""\n\n'
                + "SETTINGS = " + pprint.pformat(config, sort_dicts=False, width=100) + "\n\n"
                + "CASES = " + pprint.pformat(program, sort_dicts=False, width=100) + "\n")
            if has_legacy:
                files["level1/settings.py"] = "SITE = " + pprint.pformat(legacy_site, sort_dicts=False, width=100) + "\n"
        else:
            files["level2/cases.json"] = json_text(program)
            files["level2/config/site.json"] = json_text(config)
            if has_legacy:
                files["level2/config/gradebook.json"] = json_text(legacy_site)
    files["manifest.json"] = json_text(dict(format=1, application="Testbox Studio", levels=list(levels),
        cases=[r["case_id"] for r in records], warnings=warnings,
        files={name: hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest() for name, value in sorted(files.items())}))
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".testbox-export-") as directory:
        staged = Path(directory) / "suite.zip"
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in sorted(files.items()):
                archive.writestr(name, value)
        staged.replace(destination)
    return dict(path=str(destination), cases=len(records), levels=list(levels), warnings=warnings, files=len(files))
