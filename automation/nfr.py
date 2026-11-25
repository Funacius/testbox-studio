"""Run compatibility or elapsed-time requirements through exported Level 1/2 suites."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from automation.exporting import export_python
from automation.reporting import write_report
from automation.schema import is_script, new_step, script_data, validate_records
from gradebook.runner import BANGKOK, new_run_id


def checked_nfr(config, records, kind):
    if not isinstance(config, dict):
        raise ValueError("NFR settings must be an object")
    config = deepcopy(config)
    levels = config.setdefault("levels", [1, 2])
    browsers = config.setdefault("browsers", ["chrome", "edge"] if kind == "compatibility" else ["chrome"])
    repeats = config.setdefault("repetitions", 1 if kind == "compatibility" else 3)
    if not isinstance(levels, list) or not levels or any(type(n) is not int or n not in (1, 2) for n in levels) or len(set(levels)) != len(levels):
        raise ValueError("NFR levels must contain Level 1, Level 2 or both, without duplicates")
    if not isinstance(browsers, list) or not browsers or any(b not in {"chrome", "edge", "opera"} for b in browsers) or len(set(browsers)) != len(browsers):
        raise ValueError("Choose distinct NFR browsers from chrome, edge and opera")
    if kind == "compatibility" and len(browsers) < 2:
        raise ValueError("Compatibility requires at least two different browsers")
    if type(repeats) is not int or not 1 <= repeats <= 30:
        raise ValueError("NFR repetitions must be an integer between 1 and 30")
    measurements = config.setdefault("measurements", {})
    if not isinstance(measurements, dict):
        raise ValueError("NFR measurements must be keyed by case ID")
    if kind == "elapsed":
        for record in records:
            if not is_script(record):
                raise ValueError(f"{record['case_id']}: elapsed NFR requires an editable steps case with explicit measurement boundaries")
            rule = measurements.get(record["case_id"], {})
            if not isinstance(rule, dict):
                raise ValueError(f"{record['case_id']}: invalid measurement rule")
            steps = script_data(record, runnable=True)["steps"]
            positions = {s["id"]: i for i, s in enumerate(steps) if s["enabled"] and s["phase"] == "test" and s["command"] != "note"}
            if rule.get("start") not in positions or rule.get("end") not in positions or positions[rule["start"]] > positions[rule["end"]]:
                raise ValueError(f"{record['case_id']}: choose enabled test steps in order as measurement start/end")
            try:
                maximum = float(rule.get("maximum_seconds", ""))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{record['case_id']}: set a positive time limit in seconds") from exc
            if isinstance(rule.get("maximum_seconds"), bool) or not math.isfinite(maximum) or not 0 < maximum <= 3600:
                raise ValueError(f"{record['case_id']}: time limit must be greater than 0 and at most 3600 seconds")
            rule["maximum_seconds"] = maximum
    return config


def measured_records(records, config):
    """Insert timers into the run snapshot, preserving the authored program."""
    result = deepcopy(records)
    for record in result:
        steps = script_data(record)["steps"]
        rule = config["measurements"][record["case_id"]]
        name = "nfr_elapsed_" + record["case_id"]
        while any(s["target"] == name and s["command"] in {"start_timer", "stop_timer"} for s in steps):
            name += "_"
        rule["timer_name"] = name
        actions = []
        for step in steps:
            if step["id"] == rule["start"]:
                actions.append(new_step("start_timer", target=name, description="NFR measurement starts immediately before the selected action"))
            actions.append(step)
            if step["id"] == rule["end"]:
                actions.append(new_step("stop_timer", target=name, expected=str(rule["maximum_seconds"]),
                    description="NFR measurement ends after the selected readiness/assertion step"))
        record["actions_json"] = json.dumps(actions, ensure_ascii=False)
    return result


def summarize(records, config, kind, planned, interrupted=False):
    groups = {}
    for record in records:
        key = (record["level"], record["browser"], record["case_id"], record.get("row_index", 0))
        group = groups.setdefault(key, dict(level=key[0], browser=key[1], case_id=key[2], data_row=key[3] + 1,
            executions=0, pass_count=0, samples=[]))
        group["executions"] += 1
        group["pass_count"] += record["status"] == "PASS"
        if kind == "elapsed":
            metrics = [m for m in record.get("metrics", []) if m.get("name") == config["measurements"][record["case_id"]].get("timer_name")]
            if len(metrics) == 1:
                group["samples"].append(metrics[0]["elapsed_seconds"])
    for group in groups.values():
        values = sorted(group.pop("samples"))
        if values:
            group.update(samples_seconds=values, minimum_seconds=min(values), median_seconds=statistics.median(values),
                p95_seconds=values[math.ceil(.95 * len(values)) - 1], maximum_seconds=max(values),
                limit_seconds=config["measurements"][group["case_id"]]["maximum_seconds"])
        group["successful"] = group["executions"] == config["repetitions"] and group["pass_count"] == config["repetitions"] and (kind != "elapsed" or
            len(values) == config["repetitions"] and all(math.isfinite(value) and 0 <= value <= group["limit_seconds"] for value in values))
    success = not interrupted and bool(records) and len(records) == planned and all(g["successful"] for g in groups.values())
    return dict(kind=kind, successful=success, levels=config["levels"], browsers=config["browsers"],
        repetitions=config["repetitions"], planned_executions=planned, completed_executions=len(records),
        acceptance="Every functional assertion must pass in every selected browser/level/iteration; elapsed mode additionally requires every measurement within its per-case limit.",
        percentile_method="nearest-rank p95 (ceil(0.95*n)); small samples are descriptive, not a load-test benchmark",
        groups=list(groups.values()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--kind", choices=["compatibility", "elapsed"], required=True)
    parser.add_argument("--legacy-config", type=Path)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--events", action="store_true")
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args(argv)
    try:
        project = json.loads(args.project.read_text(encoding="utf-8-sig"))
        records, settings = project["records"], project.get("settings", {})
        validate_records(records)
        config = checked_nfr(settings.get("nfr", {}), records, args.kind)
        if args.kind == "elapsed" and float(settings.get("slow_ms", 0)) != 0:
            raise ValueError("Set step delay to 0 for elapsed NFR; interactive playback is not used for measurements")
        if args.kind == "elapsed":
            records = measured_records(records, config)
        planned = sum(len(script_data(r)["dataset"]) if is_script(r) else 1 for r in records) * len(config["levels"]) * len(config["browsers"]) * config["repetitions"]
        legacy = json.loads(args.legacy_config.read_text(encoding="utf-8")) if args.legacy_config else None
        run_id = new_run_id()
        output = args.output.resolve() / ("nfr-" + run_id)
        output.mkdir(parents=True, exist_ok=False)
        package = output / "suite"
        export_python(output / "python-suite.zip", records, settings, levels=config["levels"],
            project_dir=settings.get("project_dir", args.project.resolve().parent), legacy_site=legacy)
        with zipfile.ZipFile(output / "python-suite.zip") as archive:
            archive.extractall(package)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    def emit(event, **details):
        if args.events:
            print("@@GRADEBOOK_EVENT " + json.dumps(dict(event=event, time=datetime.now(BANGKOK).isoformat(), **details), ensure_ascii=False), flush=True)
    emit("run_start", total=planned, output=str(output), run_id=run_id)
    results, failures, logs = [], [], []
    stopped = False
    for level in config["levels"]:
        for browser in config["browsers"]:
            for repetition in range(1, config["repetitions"] + 1):
                if args.stop_file and args.stop_file.exists():
                    stopped = True
                    break
                child_dir = output / "runs" / f"level{level}-{browser}-repeat{repetition}"
                child_dir.mkdir(parents=True)
                command = [sys.executable, "-u", str(package / f"level{level}/test_cases.py"), "--browser", browser,
                    "--output", str(child_dir), "--events"]
                if args.headless:
                    command.append("--headless")
                if args.stop_file:
                    command += ["--stop-file", str(args.stop_file.resolve())]
                with (child_dir / "console.log").open("w", encoding="utf-8") as stream:
                    process = subprocess.Popen(command, cwd=package, env={**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8"},
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                    for line in process.stdout:
                        stream.write(line)
                        if line.startswith("@@GRADEBOOK_EVENT "):
                            event = json.loads(line[len("@@GRADEBOOK_EVENT "):])
                            if event["event"] not in {"run_start", "run_end"}:
                                event.update(level=level, repetition=repetition)
                                kind = event.pop("event")
                                event.pop("time", None)
                                emit(kind, **event)
                    code = process.wait()
                    process.stdout.close()
                report = next(child_dir.glob("*/results.json"), None)
                if report:
                    doc = json.loads(report.read_text(encoding="utf-8"))
                    results.extend({**record, "repetition": repetition} for record in doc["results"])
                    stopped |= doc["metadata"].get("stopped", False)
                    logs.append((report.parent / "unittest.log").read_text(encoding="utf-8"))
                    if code and doc.get("successful"):
                        failures.append(f"Level {level}/{browser}/repeat {repetition}: process exited {code} despite successful report")
                else:
                    failures.append(f"Level {level}/{browser}/repeat {repetition}: process exited {code} without report; inspect {child_dir.relative_to(output)}/console.log")
                if args.stop_file and args.stop_file.exists():
                    stopped = True
    summary = summarize(results, config, args.kind, planned, stopped)
    successful = summary["successful"] and not failures
    summary.update(successful=successful, infrastructure_errors=failures)
    metadata = dict(run_id=run_id, executed_at=datetime.now(BANGKOK).isoformat(), type="nfr_" + args.kind,
        levels=config["levels"], browsers=config["browsers"], repetitions=config["repetitions"], headless=args.headless,
        planned_executions=planned, completed_executions=len(results), stopped=stopped,
        source_project=str(args.project.resolve()), slow_ms=settings.get("slow_ms", 0), pause_seconds=0,
        level_execution="Level 1 runs exported Python definitions; Level 2 reads external JSON definitions.")
    (output / "nfr-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "unittest.log").write_text("\n\n".join(logs + failures), encoding="utf-8")
    write_report(dict(metadata=metadata, successful=successful, counts={status: sum(r["status"] == status for r in results)
        for status in ("PASS", "FAIL", "ERROR", "SKIP")}, results=results, nfr=summary), output)
    emit("run_end", successful=successful, stopped=stopped, output=str(output), total=len(results))
    print(f"NFR {'PASS' if successful else 'FAIL / INCOMPLETE'}: {output}")
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
