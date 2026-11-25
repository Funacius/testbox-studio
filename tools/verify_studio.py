"""Verify the developing Studio, optionally retaining real demo reports and previews."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [p for folder in ("automation", "studio", "gradebook", "tests", "tools") for p in (ROOT / folder).glob("*.py")]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def retained_demo():
    from automation.runner import main
    from studio.importing import map_dataset, map_steps, read_grids, suggest_mapping
    from tools.demo_site import DemoHandler
    grid = read_grids(ROOT / "examples/login-steps.csv")[0]["rows"]
    records, _ = map_steps(grid, 0, suggest_mapping(grid[0]))
    data, _ = map_dataset(read_grids(ROOT / "examples/login-data.csv")[0]["rows"], 0)
    records[0]["dataset_json"] = json.dumps(data)
    mismatch = {**records[0], "case_id": "DEMO-MISMATCH", "title": "Intentional oracle mismatch · development fixture",
                "dataset_json": json.dumps([{**data[0], "expected_message": "Expected mismatch for report verification"}])}
    steps = json.loads(mismatch["actions_json"])
    steps[-1]["timeout"] = .3
    mismatch["actions_json"] = json.dumps(steps)
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    directory = ROOT / "results" / ("studio-demo-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    directory.mkdir(parents=True, exist_ok=False)
    project = directory / "project.json"
    project.write_text(json.dumps(dict(records=[records[0], mismatch], settings={"base_url": f"http://127.0.0.1:{server.server_port}"}), ensure_ascii=False), encoding="utf-8")
    try:
        with (directory / "live.log").open("w", encoding="utf-8") as stream, contextlib.redirect_stdout(stream):
            status = main(["--project", str(project), "--headless", "--events", "--output", str(directory)])
        report = next(directory.glob("*/results.json"))
        document = json.loads(report.read_text(encoding="utf-8"))
        if status != 1 or document["counts"] != {"PASS": 3, "FAIL": 1, "ERROR": 0, "SKIP": 0}:
            raise AssertionError("The retained demo did not preserve its three valid cases and intentional oracle failure")
        return report.parent
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def screenshots(output):
    captures = []
    for view, name in (("steps", "studio-steps-preview.png"), ("locators", "studio-locators-preview.png"), ("report", "studio-report-preview.png"), ("nfr", "studio-nfr-preview.png")):
        path = ROOT / "artifacts" / name
        args = [sys.executable, str(ROOT / "tools/capture_studio_preview.py"), "--view", view, "--output", str(path)]
        if view == "report":
            args += ["--report", str(output)]
        subprocess.run(args, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        captures.append(path.relative_to(ROOT).as_posix())
    from gradebook.browser import close_browser, create_browser
    from selenium.webdriver.support.ui import Select
    driver = create_browser("chrome", {"window": [1440, 1200]}, headless=True)
    try:
        driver.get((output / "report.html").as_uri())
        Select(driver.find_element("id", "status")).select_by_visible_text("FAIL")
        visible = driver.execute_script("return [...document.querySelectorAll('.case')].filter(e=>!e.hidden).length")
        if visible != 1:
            raise AssertionError("HTML report status filtering did not select the one expected failure")
        driver.execute_script("document.querySelector('.case:not([hidden])').open=true")
        path = ROOT / "artifacts/studio-html-report-preview.png"
        driver.save_screenshot(str(path))
        captures.append(path.relative_to(ROOT).as_posix())
    finally:
        close_browser(driver)
    return captures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true", help="Include real Chrome fixture tests")
    parser.add_argument("--demo", action="store_true", help="Retain a demo run with a deliberate failure to verify reporting")
    parser.add_argument("--capture", action="store_true", help="Capture owned GUI windows and the actual HTML report (Windows)")
    parser.add_argument("--artifact", default="studio-development-verification.json")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    if args.browser:
        os.environ["TESTBOX_BROWSER_TESTS"] = "1"
    records = []
    class EvidenceResult(unittest.TextTestResult):
        def addSuccess(self, test):
            super().addSuccess(test)
            records.append(dict(test=test.id(), status="PASS"))
        def addFailure(self, test, err):
            super().addFailure(test, err)
            records.append(dict(test=test.id(), status="FAIL", detail=self._exc_info_to_string(err, test)))
        def addError(self, test, err):
            super().addError(test, err)
            records.append(dict(test=test.id(), status="ERROR", detail=self._exc_info_to_string(err, test)))
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            records.append(dict(test=test.id(), status="SKIP", detail=reason))
    before = source_hashes()
    started = time.perf_counter()
    log = ROOT / "results/studio-development-tests.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=EvidenceResult).run(unittest.defaultTestLoader.discover("tests"))
    demo, captures, extra_error = None, [], ""
    try:
        if result.wasSuccessful() and args.demo:
            demo = retained_demo()
        if result.wasSuccessful() and args.capture:
            if not demo:
                raise ValueError("Use --demo with --capture")
            captures = screenshots(demo)
    except Exception as exc:
        extra_error = f"{type(exc).__name__}: {exc}"
    after = source_hashes()
    successful = result.wasSuccessful() and (not args.browser or not result.skipped) and before == after and not extra_error
    document = dict(scope="Development tests for the implemented roadmap features; pending features are not certified.",
        executed_at=datetime.now(timezone(timedelta(hours=7))).isoformat(), tests_run=result.testsRun,
        counts={status: sum(r["status"] == status for r in records) for status in ("PASS", "FAIL", "ERROR", "SKIP")},
        successful=successful, source_unchanged_during_verification=before == after,
        duration_seconds=round(time.perf_counter() - started, 3), source_sha256=after, results=records,
        retained_demo=demo.relative_to(ROOT).as_posix() if demo else None,
        demo_note="The retained demo intentionally has 3 PASS and 1 FAIL to exercise reporting; it is not a Moodle result." if demo else None,
        previews=captures, extra_error=extra_error)
    (ROOT / "artifacts" / args.artifact).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: document[key] for key in ("tests_run", "counts", "successful", "retained_demo", "previews", "extra_error")}))
    if not successful:
        print(log.read_text(encoding="utf-8")[-12000:])
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
