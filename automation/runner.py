"""Run editable browser steps, optionally alongside existing Gradebook cases."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from automation.schema import COMMANDS, PHASES, VARIABLE, is_script, locator, resolve, script_data, validate_records
from automation.readiness import checked_settings, website_status
from gradebook.runner import BANGKOK, CsvResult, GradebookCase, new_run_id, write_results
from datetime import datetime


def variables_for(record, row, settings, run_id):
    values = dict(settings.get("variables", {}))
    values.update({key[len("TESTBOX_VAR_"):]: value for key, value in os.environ.items() if key.startswith("TESTBOX_VAR_")})
    values.update(script_data(record)["variables"])
    values.update(row)
    values.update(base_url=settings.get("base_url", ""), run_id=run_id,
                  case_id=record["case_id"], runtime_id=f"TB-{run_id}-{record['case_id']}")
    return values


def preflight(records, settings):
    """Validate references per dataset row before launching any browser."""
    checked_settings(settings)
    if not isinstance(settings.get("variables", {}), dict) or any(not isinstance(v, str) for v in settings.get("variables", {}).values()):
        raise ValueError("Shared variables must contain text values")
    validate_records(records)
    if not records:
        raise ValueError("Select at least one test case")
    problems = []
    for record in records:
        if not is_script(record):
            continue
        data = script_data(record, runnable=True)
        for row_number, row in enumerate(data["dataset"], 1):
            values = variables_for(record, row, settings, "preflight")
            for phase in PHASES:
                for index, step in enumerate(data["steps"], 1):
                    if not step["enabled"] or step["phase"] != phase:
                        continue
                    try:
                        target, value = resolve(step["target"], values), resolve(step["value"], values)
                        resolve(step["expected"], values)
                        if COMMANDS[step["command"]][0] and not target:
                            raise ValueError("Target resolves to an empty value")
                        if COMMANDS[step["command"]][0] and step["command"] not in {"open", "set_variable", "switch_window", "start_timer", "stop_timer"}:
                            _, selector = locator(target, settings.get("locators", {}))
                            resolve(selector, values)
                        if step["command"] in {"store_text", "store_value"}:
                            values[value] = "<runtime value>"
                        if step["command"] == "set_variable":
                            values[target] = value
                    except ValueError as exc:
                        problems.append(f"{record['case_id']}, data row {row_number}, step {index}: {exc}")
    if problems:
        raise ValueError("\n".join(problems))


class ScriptCase(unittest.TestCase):
    def __init__(self, record, row, row_index, browser, settings, output, run_id, level,
                 headless, shared_drivers, on_event):
        super().__init__("runTest")
        self.record, self.row, self.row_index = record, row, row_index
        self.data = script_data(record, runnable=True)
        self.case = SimpleNamespace(case_id=record["case_id"], title=record["title"],
                                    expected_result=record.get("expected_result", ""),
                                    expected={"steps": self.data["steps"]}, known_defect=record.get("known_defect", ""))
        self.browser, self.settings, self.output, self.run_id = browser, settings, output, run_id
        self.level, self.headless, self.shared_drivers, self.on_event = level, headless, shared_drivers, on_event
        self.runtime_id = f"TB-{run_id}-{record['case_id']}-{row_index}"
        self.evidence, self.capabilities, self.cleanup_error = [], {}, ""
        self.step_results, self.metrics, self.assertion_count = [], [], 0
        self.engine, self.driver, self.completed_main = None, None, False

    def id(self):
        return f"L{self.level}.{self.browser}.{self.case.case_id}.row{self.row_index + 1}"

    def __str__(self):
        return f"{self.id()}: {self.case.title}"

    def setUp(self):
        from gradebook.browser import close_browser, create_browser
        from automation.engine import StepEngine
        settings = {"window": [1440, 900], **self.settings}
        if self.shared_drivers is not None and self.browser in self.shared_drivers:
            self.driver = self.shared_drivers[self.browser]
            handles = self.driver.window_handles
            for handle in handles[1:]:
                self.driver.switch_to.window(handle)
                self.driver.close()
            self.driver.switch_to.window(handles[0])
            self.driver.switch_to.default_content()
            self.driver.delete_all_cookies()
            if urlsplit(self.driver.current_url).scheme in {"http", "https"}:
                self.driver.execute_script("localStorage.clear();sessionStorage.clear();")
            self.driver.get("about:blank")
        else:
            self.driver = create_browser(self.browser, settings, self.headless)
            if self.shared_drivers is not None:
                self.shared_drivers[self.browser] = self.driver
            else:
                self.addCleanup(close_browser, self.driver)
        self.capabilities = {k: self.driver.capabilities.get(k) for k in ("browserName", "browserVersion", "platformName")}
        self.capabilities["viewport"] = self.driver.execute_script("return {width:innerWidth,height:innerHeight,devicePixelRatio:devicePixelRatio}")
        self.capabilities["userAgent"] = self.driver.execute_script("return navigator.userAgent")
        if self.browser == "opera" and "OPR/" not in self.capabilities["userAgent"]:
            raise RuntimeError("Requested Opera GX, but this session does not identify as Opera")
        values = variables_for(self.record, self.row, settings, self.run_id)
        values["runtime_id"] = self.runtime_id
        self.engine = StepEngine(self.driver, settings, values,
                                 self.output / f"{self.browser}-{self.case.case_id}-row{self.row_index + 1}",
                                 on_event=lambda **event: self.on_event(case_id=self.case.case_id, browser=self.browser,
                                                                       row_index=self.row_index, **event))
        self.addCleanup(self.cleanup_steps)

    def runTest(self):
        self.engine.run_phase(self.data["steps"], "setup")
        self.engine.run_phase(self.data["steps"], "test")
        self.completed_main = True

    def cleanup_steps(self):
        try:
            self.engine.run_phase(self.data["steps"], "cleanup")
            if self.completed_main and self.engine.timers:
                raise ValueError("Timers were started but not stopped: " + ", ".join(self.engine.timers))
        except Exception:
            self.cleanup_error = traceback.format_exc()
            raise
        finally:
            self.step_results = list(self.engine.records)
            self.metrics, self.assertion_count = list(self.engine.metrics), self.engine.assertions
            self.evidence = [path for step in self.step_results for path in step.get("evidence", [])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Immutable JSON snapshot with records and settings")
    parser.add_argument("--browser", choices=["chrome", "edge", "opera", "both"], default="chrome")
    parser.add_argument("--level", type=int, choices=[1, 2], default=2)
    parser.add_argument("--legacy-config", type=Path)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--reuse-browser", action="store_true")
    parser.add_argument("--events", action="store_true")
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    try:
        project = json.loads(args.project.read_text(encoding="utf-8-sig"))
        records, settings = project["records"], project.get("settings", {})
        settings.setdefault("project_dir", str(args.project.resolve().parent))
        preflight(records, settings)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    browsers = ["chrome", "edge"] if args.browser == "both" else [args.browser]
    if args.list:
        for record in records:
            rows = len(script_data(record)["dataset"]) if is_script(record) else 1
            print(f"{record['case_id']}: {record['title']} ({rows} data rows x {len(browsers)} browsers)")
        return 0
    if settings.get("check_connection", True):
        try:
            print(website_status(settings.get("base_url", "")))
        except ValueError as exc:
            parser.error(str(exc))
    run_id = new_run_id()
    output = args.output.resolve() / ("automation-" + run_id)
    output.mkdir(parents=True, exist_ok=False)
    def emit(event, **values):
        if args.events:
            print("@@GRADEBOOK_EVENT " + json.dumps(dict(event=event, time=datetime.now(BANGKOK).isoformat(), **values), ensure_ascii=False), flush=True)
    drivers = {} if args.reuse_browser else None
    tests = []
    from gradebook.config import load_site
    from gradebook.data import parse_rows
    for browser in browsers:
        for record in records:
            if is_script(record):
                for index, row in enumerate(script_data(record)["dataset"]):
                    tests.append(ScriptCase(record, row, index, browser, settings, output, run_id,
                                            args.level, args.headless, drivers, emit))
            else:
                site = load_site(args.level, args.legacy_config if args.level == 2 else None)
                for key in ("base_url", "course_id", "window", "page_load_timeout", "command_timeout"):
                    if key in settings:
                        site[key] = settings[key]
                tests.append(GradebookCase(parse_rows([record])[0], args.level, browser, site, output,
                                          run_id, args.headless, emit, drivers))
    emit("run_start", total=len(tests), output=str(output), run_id=run_id)
    try:
        with (output / "unittest.log").open("w", encoding="utf-8") as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2,
                         resultclass=lambda *a, **k: CsvResult(*a, on_event=emit, stop_file=args.stop_file, **k)).run(unittest.TestSuite(tests))
    finally:
        if drivers:
            from gradebook.browser import close_browser
            for driver in drivers.values():
                close_browser(driver)
    stopped = result.testsRun < len(tests)
    metadata = dict(run_id=run_id, executed_at=datetime.now(BANGKOK).isoformat(), type="editable_steps",
                    level=args.level, headless=args.headless, reuse_browser=args.reuse_browser,
                    planned_executions=len(tests), completed_executions=result.testsRun, stopped=stopped,
                    python=platform.python_version(), source_project=str(args.project.resolve()),
                    site_base_url=settings.get("base_url", ""))
    write_results(result, output, metadata)
    successful = result.wasSuccessful() and not result.skipped and not stopped
    emit("run_end", successful=successful, stopped=stopped, output=str(output), total=result.testsRun)
    print(f"Ran {result.testsRun} checks; results: {output}")
    return 0 if successful else 1


if __name__ == "__main__":
    sys.exit(main())
