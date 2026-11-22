"""One unittest per CSV row, with evidence, cleanup and machine-readable results."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from gradebook.config import ROOT, load_site
from gradebook.data import Case, load_cases

BANGKOK = timezone(timedelta(hours=7))
COMPATIBILITY_IDS = ["TC-003-011", "TC-003-012", "TC-003-007", "TC-003-018", "TC-003-029"]


def new_run_id() -> str:
    return datetime.now(BANGKOK).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]


def check_date_precondition(case: Case) -> None:
    for parts in case.inputs.get("dates", {}).values():
        target = datetime(**{k: int(v) for k, v in parts.items()}, tzinfo=BANGKOK)
        if target <= datetime.now(BANGKOK):
            raise unittest.SkipTest(f"Source future-date precondition expired: {target.isoformat()}")


class GradebookCase(unittest.TestCase):
    def __init__(self, case: Case, level: int, browser: str, site: dict,
                 output: Path, run_id: str, headless: bool = False, on_event=None):
        super().__init__("runTest")
        self.case = case
        self.level = level
        self.browser = browser
        self.site = site
        self.output = output
        self.run_id = run_id
        self.headless = headless
        self.driver = None
        self.page = None
        self.evidence: list[str] = []
        case_token = hashlib.sha256(case.case_id.encode()).hexdigest()[:10]
        self.runtime_id = f"P3F003-{run_id[-8:]}-{case_token}"
        self.capabilities = {}
        self.cleanup_error = ""
        self.on_event = on_event

    def notify(self, kind: str, **details):
        if self.on_event:
            self.on_event(kind, case_id=self.case.case_id, browser=self.browser, **details)

    def id(self):
        return f"L{self.level}.{self.browser}.{self.case.case_id}"

    def __str__(self):
        return f"{self.id()}: {self.case.title}"

    def shortDescription(self):
        return self.case.title

    def setUp(self):
        check_date_precondition(self.case)
        # Import lazily: extracting/listing data never needs Selenium or a browser.
        from gradebook.browser import create_browser
        from gradebook.page import GradebookPage
        self.notify("step", message=f"Start {self.browser} browser")
        self.driver = create_browser(self.browser, self.site, self.headless)
        self.addCleanup(self.driver.quit)
        self.capabilities = {k: self.driver.capabilities.get(k) for k in ("browserName", "browserVersion", "platformName")}
        self.page = GradebookPage(self.driver, self.site, self,
                                  on_step=lambda message: self.notify("step", message=message))
        self.addCleanup(self.cleanup_owned_items)
        try:
            self.page.login(os.environ.get("MOODLE_USERNAME", "teacher01"),
                            os.environ.get("MOODLE_PASSWORD", "1234"))
            self.page.begin_case(self.runtime_id)
        except Exception:
            self.capture_failure("setup")
            raise

    def capture_failure(self, suffix: str):
        if self.page:
            self.evidence.extend(self.page.capture(self.output / "evidence", f"{self.id()}-{suffix}"))

    def cleanup_owned_items(self):
        try:
            self.page.cleanup()
        except Exception:
            self.cleanup_error = traceback.format_exc()
            self.capture_failure("cleanup")
            raise
        finally:
            directory = self.output / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{self.id()}.txt").write_text("\n".join(self.page.trace) + "\n", encoding="utf-8")

    def runTest(self):
        try:
            self.page.execute(self.case.workflow, self.case.inputs, self.case.expected)
        except Exception:
            # Capture the original failure page before cleanup navigates away.
            self.capture_failure("failure")
            raise


class CsvResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        self.on_event = kwargs.pop("on_event", None)
        self.stop_file = kwargs.pop("stop_file", None)
        super().__init__(*args, **kwargs)
        self.records = []
        self.pending = {}

    def startTest(self, test):
        super().startTest(test)
        self.pending[id(test)] = dict(status="PASS", details=[], start=time.perf_counter())
        if self.on_event:
            self.on_event("case_start", case_id=test.case.case_id, browser=test.browser, title=test.case.title)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        record = self.pending[id(test)]
        if record["status"] != "ERROR":
            record["status"] = "FAIL"
        record["details"].append(self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.pending[id(test)]["status"] = "ERROR"
        self.pending[id(test)]["details"].append(self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.pending[id(test)]["status"] = "SKIP"
        self.pending[id(test)]["details"].append(reason)

    def stopTest(self, test):
        record = self.pending.pop(id(test))
        self.records.append(dict(case_id=test.case.case_id, title=test.case.title,
                                 level=test.level, browser=test.browser,
                                 status=record["status"],
                                 duration_seconds=round(time.perf_counter() - record["start"], 6),
                                 expected=test.case.expected_result,
                                 expected_json=test.case.expected,
                                 actual="\n".join(record["details"]) or "All assertions and cleanup completed",
                                 known_defect=test.case.known_defect, runtime_id=test.runtime_id,
                                 cleanup_error=test.cleanup_error,
                                 evidence=test.evidence, capabilities=test.capabilities))
        if self.on_event:
            self.on_event("case_end", **self.records[-1])
        if self.stop_file and self.stop_file.exists():
            self.stop()
        super().stopTest(test)


def write_results(result: CsvResult, output: Path, metadata: dict) -> None:
    import csv
    output.mkdir(parents=True, exist_ok=True)
    document = {"metadata": metadata, "successful": result.wasSuccessful() and not result.skipped and not metadata.get("stopped", False),
                "counts": {status: sum(r["status"] == status for r in result.records)
                           for status in ("PASS", "FAIL", "ERROR", "SKIP")},
                "results": result.records}
    (output / "results.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["case_id", "title", "level", "browser", "status", "duration_seconds",
               "expected", "actual", "known_defect", "runtime_id", "cleanup_error", "evidence"]
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({**r, "evidence": json.dumps(r["evidence"], ensure_ascii=False)} for r in result.records)


def build_parser(default_level: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Feature 003 data-driven unittest cases")
    parser.add_argument("--level", type=int, choices=[1, 2], default=default_level)
    parser.add_argument("--data", type=Path, help="Defaults to the selected level's CSV")
    parser.add_argument("--config", type=Path, help="Level 2 site JSON")
    parser.add_argument("--browser", choices=["chrome", "edge", "both"], default="chrome")
    parser.add_argument("--cases", nargs="+", help="Exact case IDs; omit for the whole CSV")
    parser.add_argument("--base-url")
    parser.add_argument("--course-id")
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    parser.add_argument("--headless", action="store_true", help="Development only; official runs use a visible browser")
    parser.add_argument("--list", action="store_true", help="List CSV cases only; no tests or browser")
    parser.add_argument("--events", action="store_true", help="Emit structured live events for the desktop app")
    parser.add_argument("--stop-file", type=Path, help="Stop after current case and its cleanup when this file exists")
    return parser


def main(default_level: int = 1, argv=None, compatibility: bool = False) -> int:
    parser = build_parser(default_level)
    args = parser.parse_args(argv)
    if compatibility and (args.level != 2 or args.headless or args.cases or args.browser not in {"chrome", "both"}):
        parser.error("Compatibility uses Level 2, both visible browsers and its fixed five-case selection")
    if args.config and args.level != 2:
        parser.error("--config belongs to Level 2")
    path = args.data or ROOT / f"level{args.level}/data/gradebook_cases.csv"
    cases = load_cases(path)
    requested = COMPATIBILITY_IDS if compatibility else args.cases
    if requested:
        available = {c.case_id: c for c in cases}
        if len(set(requested)) != len(requested):
            parser.error("Duplicate IDs in --cases")
        missing = set(requested) - available.keys()
        if missing:
            parser.error(f"Unknown case IDs: {sorted(missing)}")
        cases = [available[c] for c in requested]
    browsers = ["chrome", "edge"] if compatibility or args.browser == "both" else [args.browser]
    if args.list:
        for browser in browsers:
            for case in cases:
                print(f"L{args.level} {browser} {case.case_id} [{case.workflow}] {case.title}")
        return 0
    if not importlib.util.find_spec("selenium"):
        parser.error("Selenium is not installed. Run: python -m pip install -r requirements.txt")
    site = load_site(args.level, args.config)
    if args.base_url:
        site["base_url"] = args.base_url
    if args.course_id:
        site["course_id"] = args.course_id
    run_id = new_run_id()
    output = args.output.resolve() / (("compatibility-" if compatibility else f"level{args.level}-") + run_id)
    output.mkdir(parents=True, exist_ok=False)
    def emit(kind, **details):
        if args.events:
            event = dict(event=kind, time=datetime.now(BANGKOK).isoformat(), **details)
            try:
                print("@@GRADEBOOK_EVENT " + json.dumps(event, ensure_ascii=False), flush=True)
            except OSError:
                pass
    planned = len(browsers) * len(cases)
    emit("run_start", total=planned, output=str(output), run_id=run_id)
    suite = unittest.TestSuite(GradebookCase(case, args.level, browser, site, output, run_id, args.headless, emit)
                               for browser in browsers for case in cases)
    with (output / "unittest.log").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2,
                    resultclass=lambda *a, **kw: CsvResult(*a, on_event=emit, stop_file=args.stop_file, **kw)).run(suite)
    metadata = dict(run_id=run_id, executed_at=datetime.now(BANGKOK).isoformat(),
                    type="compatibility" if compatibility else "functional",
                    python=platform.python_version(), platform=platform.platform(), selenium=version("selenium"),
                    source_csv=str(path.resolve()), site_base_url=site["base_url"],
                    course_id=site["course_id"], headless=args.headless, window=site["window"])
    metadata["planned_executions"] = planned
    metadata["completed_executions"] = result.testsRun
    metadata["stopped"] = result.testsRun < planned
    write_results(result, output, metadata)
    successful = result.wasSuccessful() and not result.skipped and result.testsRun == planned
    if compatibility:
        # A skipped case is incomplete compatibility coverage, not a passing NFR.
        summary = dict(requirement_id="NF-003-COMPAT", status="PASS" if successful else "FAIL",
                       required_cases=COMPATIBILITY_IDS, browsers=browsers,
                       expected_runs=10, actual_runs=len(result.records),
                       limitation="Chrome and Edge both use Chromium; no Firefox/Safari conclusion")
        (output / "compatibility-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Ran {result.testsRun} checks; results: {output}")
    print(f"PASS={sum(r['status']=='PASS' for r in result.records)}, FAIL={len(result.failures)}, ERROR={len(result.errors)}, SKIP={len(result.skipped)}")
    emit("run_end", successful=successful, stopped=result.testsRun < planned, output=str(output), total=result.testsRun)
    return 0 if successful else 1


if __name__ == "__main__":
    sys.exit(main())
