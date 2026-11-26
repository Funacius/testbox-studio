"""Verify both original 36-case suites, retaining the known database-error FAIL."""

import csv
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default="studio-gradebook-regression.json")
    parser.add_argument("--keep-going", action="store_true", help="Collect the other level after an unexpected error")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from tools.verify_studio import source_hashes
    timestamp = datetime.now(timezone(timedelta(hours=7)))
    directory = ROOT / "results" / ("studio-gradebook-regression-" + timestamp.strftime("%Y%m%d-%H%M%S"))
    directory.mkdir(parents=True, exist_ok=False)
    historical = json.loads((ROOT / "artifacts/verification-summary.json").read_text(encoding="utf-8"))["datasets"]
    before = source_hashes()
    suites = []
    stop_file = directory / "stop.request"
    for level in (1, 2):
        path = ROOT / f"level{level}/data/gradebook_cases.csv"
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != historical[f"level{level}"]["sha256"]:
            raise ValueError(f"Level {level} source dataset differs from the original verified dataset")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        expected_ids = {f"TC-003-{i:03}" for i in range(1, 37)}
        if {r["case_id"] for r in rows} != expected_ids or len(rows) != 36:
            raise ValueError("The original 36-case selection must be retained")
        command = [sys.executable, "-u", "-m", "gradebook.runner", "--level", str(level), "--data", str(path),
            "--browser", "chrome", "--headless", "--reuse-browser", "--events", "--stop-file", str(stop_file), "--output", str(directory / f"level{level}")]
        completed = 0
        with (directory / f"level{level}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for line in process.stdout:
                log.write(line)
                log.flush()
                if line.startswith("@@GRADEBOOK_EVENT "):
                    event = json.loads(line[len("@@GRADEBOOK_EVENT "):])
                    if event["event"] == "case_end":
                        completed += 1
                        if completed % 6 == 0 or event["status"] != "PASS":
                            print(f"Level {level}: {completed}/36 | {event['case_id']} {event['status']}", flush=True)
                        expected_status = "FAIL" if event["case_id"] == "TC-003-036" else "PASS"
                        if not args.keep_going and event["status"] != expected_status:
                            stop_file.write_text("Stop after cleanup: unexpected outcome requires investigation.\n", encoding="utf-8")
            code = process.wait()
            process.stdout.close()
        report = next((directory / f"level{level}").glob("*/results.json"))
        document = json.loads(report.read_text(encoding="utf-8"))
        failed = [r for r in document["results"] if r["status"] != "PASS"]
        known = next((r for r in failed if r["case_id"] == "TC-003-036"), {})
        html = "\n".join(Path(name).read_text(encoding="utf-8", errors="replace") for name in known.get("evidence", []) if name.endswith(".html") and Path(name).is_file())
        oracle = json.loads(next(r for r in rows if r["case_id"] == "TC-003-036")["expected_json"])
        matches = code == 1 and document["counts"] == {"PASS": 35, "FAIL": 1, "ERROR": 0, "SKIP": 0} and len(document["results"]) == 36 \
            and len(failed) == 1 and known.get("status") == "FAIL" and known.get("expected_json") == oracle \
            and "Error writing to database" in html and all(not r.get("cleanup_error") for r in document["results"])
        suites.append(dict(level=level, report=report.relative_to(ROOT).as_posix(), counts=document["counts"],
            source_sha256=checksum, expected_outcomes_matched=matches, known_defect_reproduced="Error writing to database" in html,
            cleanup_errors=[r["case_id"] for r in document["results"] if r.get("cleanup_error")],
            capabilities=document["results"][0].get("capabilities", {})))
        print(f"Level {level}: expected outcomes {'matched' if matches else 'NOT matched'}", flush=True)
        if stop_file.exists():
            break
    after = source_hashes()
    # UI/import work may continue while the browser suites run. Match the backend
    # used by these suites, and keep both snapshots rather than claiming all
    # development sources were frozen.
    backend_unchanged = all(before[name] == after.get(name) for name in before if name.startswith(("gradebook/", "automation/")))
    successful = backend_unchanged and len(suites) == 2 and all(s["expected_outcomes_matched"] for s in suites)
    artifact = dict(scope="Native Gradebook Level 1/2: all original cases, data/oracles unchanged; TC-003-036 remains FAIL",
        executed_at=timestamp.isoformat(), successful=successful, backend_unchanged=backend_unchanged, suites=suites,
        source_sha256_before=before, source_sha256_after=after,
        note="Verification success means 35 PASS + the retained known FAIL per level, not an all-PASS Moodle application.")
    (ROOT / "artifacts" / args.artifact).write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"successful": successful, "backend_unchanged": backend_unchanged, "output": str(directory)}))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
