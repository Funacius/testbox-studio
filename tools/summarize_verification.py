"""Summarize completed final runs without treating known failures as passes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SAMPLE = {"TC-003-011", "TC-003-012", "TC-003-007", "TC-003-018", "TC-003-029"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig").lstrip("\ufeff"))


def live_events(path: Path):
    raw = path.read_bytes()
    text = raw.decode("utf-16" if raw.startswith(b"\xff\xfe") else "utf-8-sig", errors="replace")
    return [json.loads(line.split("@@GRADEBOOK_EVENT ", 1)[1])
            for line in text.splitlines() if "@@GRADEBOOK_EVENT " in line]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / "results/final-headless")
    parser.add_argument("--log-prefix", default="final-headless")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/verification-summary.json")
    args = parser.parse_args()
    groups = {}
    for path in sorted(args.runs.glob("*/results.json")):
        doc = read_json(path)
        meta, records = doc["metadata"], doc["results"]
        if not records:
            continue
        kind = meta["type"]
        browsers = {r["browser"] for r in records}
        if kind == "compatibility":
            key, expected = "compatibility", {(b, c) for b in ("chrome", "edge") for c in EXPECTED_SAMPLE}
        elif browsers == {"opera"}:
            key, expected = "opera", {("opera", c) for c in EXPECTED_SAMPLE}
        elif browsers == {"chrome"}:
            key = f"level{records[0]['level']}"
            expected = {("chrome", f"TC-003-{n:03}") for n in range(1, 37)}
        else:
            continue
        groups.setdefault(key, {"expected": expected, "runs": []})["runs"].append((path, doc))
    suites, csv_rows = {}, []
    for key, group in groups.items():
        attempts = {}
        sources = []
        runs = sorted(group["runs"], key=lambda run: run[1]["metadata"]["executed_at"])
        for path, doc in runs:
            source = path.resolve().relative_to(ROOT).as_posix()
            sources.append(dict(result_file=source, metadata=doc["metadata"], counts=doc["counts"]))
            for record in doc["results"]:
                pair = record["browser"], record["case_id"]
                attempts.setdefault(pair, []).append(dict(**record, result_file=source,
                    executed_at=doc["metadata"]["executed_at"]))
        # A targeted rerun replaces only that case's final outcome. All previous
        # attempts remain visible below, including infrastructure errors.
        records = [history[-1] for _, history in sorted(attempts.items())]
        expected = group["expected"]
        observed = set(attempts)
        count = Counter(r["status"] for r in records)
        events = [event for log in sorted((ROOT / "results").glob(f"{args.log_prefix}-{key}*-live.log"))
                  for event in live_events(log)]
        fallbacks = sum("fallback" in e.get("message", "").lower() for e in events)
        logged_runs = {e["run_id"] for e in events if e["event"] == "run_start"}
        histories = [dict(browser=b, case_id=c, attempts=history)
                     for (b, c), history in sorted(attempts.items()) if len(history) > 1]
        suites[key] = dict(
            executed_at=runs[-1][1]["metadata"]["executed_at"], sources=sources,
            expected_executions=len(expected), actual_executions=len(records),
            total_attempts=sum(len(h) for h in attempts.values()), retry_history=histories,
            coverage_complete=observed == expected and count["ERROR"] == count["SKIP"] == 0,
            counts={s: count[s] for s in ("PASS", "FAIL", "ERROR", "SKIP")},
            headless=all(doc["metadata"]["headless"] for _, doc in runs), native_fallback_events=fallbacks,
            event_logs_complete=all(doc["metadata"]["run_id"] in logged_runs for _, doc in runs),
            interaction_fallbacks_enabled=any(doc["metadata"].get("interaction_fallbacks_enabled", False) for _, doc in runs),
            browser_capabilities={r["browser"]: r["capabilities"] for r in records},
            failures=[dict(case_id=r["case_id"], browser=r["browser"], status=r["status"],
                           known_defect=r["known_defect"], actual=r["actual"], evidence=r["evidence"])
                      for r in records if r["status"] != "PASS"],
            cleanup_errors=[dict(case_id=r["case_id"], error=r["cleanup_error"])
                            for r in records if r["cleanup_error"]],
        )
        csv_rows.extend(dict(suite=key, case_id=r["case_id"], title=r["title"], browser=r["browser"],
                             status=r["status"], known_defect=r["known_defect"],
                             attempt_count=len(attempts[r["browser"], r["case_id"]]),
                             duration_seconds=r["duration_seconds"], actual=r["actual"],
                             result_file=r["result_file"]) for r in records)
    missing = {"level1", "level2", "compatibility", "opera"} - suites.keys()
    if missing:
        parser.error(f"Final stages have not all completed: {sorted(missing)}")
    datasets = {}
    for level in (1, 2):
        path = ROOT / f"level{level}/data/gradebook_cases.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            count = len(list(csv.DictReader(stream)))
        datasets[f"level{level}"] = dict(rows=count, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    baseline = read_json(ROOT / "results/baseline-environment.json")
    after = read_json(ROOT / "results/after-environment.json")
    result = dict(
        generated_at=datetime.now(timezone(timedelta(hours=7))).isoformat(),
        environment=after, baseline_manual_item_count=len(baseline["manual_items"]),
        after_manual_item_count=len(after["manual_items"]),
        manual_item_baseline_restored=baseline["manual_items"] == after["manual_items"],
        datasets=datasets, suites=suites,
        all_planned_coverage_complete=all(s["coverage_complete"] for s in suites.values()),
        all_native_interactions=all(s["event_logs_complete"] and s["native_fallback_events"] == 0 and not s["interaction_fallbacks_enabled"] for s in suites.values()),
        all_assertions_passed=all(s["counts"]["FAIL"] == s["counts"]["ERROR"] == s["counts"]["SKIP"] == 0 for s in suites.values()),
        exploratory_runs="Earlier diagnostics and the browser-password-dialog-interrupted run are excluded; their local logs are retained.",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases_path = args.output.with_name("verification-cases.csv")
    with cases_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    for key, suite in suites.items():
        print(key, suite["counts"], "coverage", suite["coverage_complete"], "fallbacks", suite["native_fallback_events"])
    print("Manual-item baseline restored:", result["manual_item_baseline_restored"])
    print("Summary:", args.output)


if __name__ == "__main__":
    main()
