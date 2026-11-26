"""Portable JSON/CSV and a standalone dark HTML report with local evidence links."""

import csv
import html
import json
import shutil
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote


def text(value):
    if isinstance(value, (dict, list, bool)) or value is None:
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def escaped(value):
    return html.escape(text(value), quote=True)


def successful_report(document):
    records = document.get("results", [])
    metadata = document.get("metadata", {})
    completed = sum(r.get("status") != "NOT_RUN" for r in records)
    return bool(document.get("successful") and records and not metadata.get("stopped")
        and all(r.get("status") == "PASS" for r in records)
        and metadata.get("completed_executions", completed) == metadata.get("planned_executions", len(records)))


def planned_results(record):
    """Keep unexecuted planned steps visible in interrupted/failed runs."""
    actual = list(record.get("step_results", []))
    seen = {step.get("step_id") for step in actual}
    expected = record.get("expected_json", {})
    if not isinstance(expected, dict):
        return actual
    planned = expected.get("steps", [])
    if not isinstance(planned, list):
        return actual
    for index, step in enumerate(planned, 1):
        if not isinstance(step, dict):
            continue
        if step.get("id") not in seen:
            disabled = not step.get("enabled", True) or step.get("command") == "note"
            actual.append(dict(step_id=step.get("id", ""), index=index, phase=step.get("phase", "test"),
                               command=step.get("command", ""), target=step.get("target", ""),
                               expected=step.get("expected", ""), status="SKIP" if disabled else "NOT_RUN",
                               actual="Disabled/reference step" if disabled else "Not reached", duration_seconds=""))
    return actual


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: json.dumps(row.get(key), ensure_ascii=False) if isinstance(row.get(key), (dict, list))
                         else row.get(key, "") for key in columns} for row in rows)


def evidence_path(raw, output):
    path = Path(raw)
    if not path.is_absolute():
        path = output / path
    path = path.resolve()
    path.relative_to(output.resolve())
    return path


def evidence_links(paths, output):
    links = []
    for raw in paths:
        try:
            path = evidence_path(raw, output)
            relative = path.relative_to(output.resolve()).as_posix()
        except (ValueError, OSError):
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".html", ".txt"}:
            continue
        links.append(f'<a href="{html.escape(quote(relative, safe="/"), quote=True)}" target="_blank" rel="noopener">{html.escape(path.name)}</a>')
    return "<br>".join(links)


def report_html(document, output):
    metadata, records, counts = document["metadata"], document["results"], document["counts"]
    status = "STOPPED" if metadata.get("stopped") else "PASS" if document["successful"] else "FAIL / INCOMPLETE"
    sections = []
    for record in records:
        steps = planned_results(record)
        rows = []
        for step in steps:
            rows.append("<tr>" + "".join(f"<td><pre>{escaped(step.get(key, ''))}</pre></td>" for key in
                        ("index", "execution", "loop_path", "phase", "command", "target", "input_value", "expected", "actual", "status", "duration_seconds"))
                        + f"<td>{evidence_links(step.get('evidence', []), output)}</td></tr>")
        table = ('<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{name}</th>' for name in
                 ("#", "Exec", "Loop", "Phase", "Action", "Target", "Input", "Expected", "Actual", "Status", "Seconds", "Evidence"))
                 + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>') if rows else '<p>Legacy workflow: inspect unittest.log and the case trace in logs/ for action details.</p>'
        metrics = ''.join('<li><pre>' + escaped(metric) + '</pre></li>' for metric in record.get("metrics", []))
        row_number = int(record.get("row_index", 0)) + 1
        label = f"{record['case_id']} · data {row_number} · {record['browser']} · {record['title']}"
        if "repetition" in record:
            label += f" · L{record.get('level', '')} · repeat {record['repetition']}"
        sections.append(f'<details class="case" data-status="{escaped(record["status"])}"><summary>'
                        f'<span class="badge {escaped(record["status"])}">{escaped(record["status"])}</span> {escaped(label)}</summary>'
                        f'<p>Level {escaped(record.get("level", ""))} · {escaped(record.get("duration_seconds", ""))} seconds · '
                        f'Assertions: {escaped(record.get("assertion_count") if record.get("assertion_count") is not None else "legacy workflow")}</p>'
                        f'<h3>Case outcome</h3><pre>{escaped(record.get("actual", ""))}</pre>'
                        f'<h3>Steps</h3>{table}'
                        + (f'<h3>Measurements</h3><ul>{metrics}</ul>' if metrics else '')
                        + f'<h3>Cleanup</h3><pre>{escaped(record.get("cleanup_error") or "Completed / no cleanup error recorded")}</pre>'
                        + f'<p>{evidence_links(record.get("evidence", []), output)}</p></details>')
    nfr = document.get("nfr")
    nfr_section = ''
    if nfr:
        nfr_rows = []
        for group in nfr.get("groups", []):
            values = [group.get(key, "—") for key in ("level", "browser", "case_id", "data_row")]
            values.append(f"{group.get('pass_count', 0)}/{group.get('executions', 0)}")
            values += [f"{group[key]:.6f}" if isinstance(group.get(key), (float, int)) else "—"
                       for key in ("minimum_seconds", "median_seconds", "p95_seconds", "maximum_seconds", "limit_seconds")]
            values.append("PASS" if group.get("successful") else "FAIL / INCOMPLETE")
            nfr_rows.append('<tr>' + ''.join('<td>' + escaped(value) + '</td>' for value in values) + '</tr>')
        headers = ("Level", "Browser", "Case", "Data row", "PASS / Total", "Min s", "Median s", "P95 s", "Max s", "Limit s", "Outcome")
        nfr_section = ('<section><h2>Non-functional requirement · ' + escaped(nfr.get("kind", "")) + '</h2><p>'
            + escaped(nfr.get("acceptance", "")) + '</p><p class="meta">' + escaped(nfr.get("percentile_method", ""))
            + '</p><div class="scroll"><table><thead><tr>' + ''.join('<th>' + escaped(title) + '</th>' for title in headers)
            + '</tr></thead><tbody>' + ''.join(nfr_rows) + '</tbody></table></div><p><a href="nfr-summary.json">NFR summary JSON</a></p>'
            + ('<pre>' + escaped(nfr["infrastructure_errors"]) + '</pre>' if nfr.get("infrastructure_errors") else '') + '</section>')
    body = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Testbox Studio execution report</title><style>
body{{background:#202020;color:#e3e3e3;font:15px system-ui;margin:0;padding:25px}}h1{{color:#ea8a23}}h3{{font-size:15px}}
header,.case{{background:#303030;border:1px solid #191919;border-radius:5px;padding:16px;margin:12px 0}}
summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:13px ui-monospace,monospace}}
.badge{{display:inline-block;padding:4px 8px;margin-right:8px;background:#3d3d3d}}.PASS{{color:#9ac77b}}.FAIL,.ERROR{{color:#e58b8b}}.SKIP,.NOT_RUN{{color:#e5b76a}}
input,select,button{{background:#242424;color:#eee;border:1px solid #666;padding:8px;margin:4px}}a{{color:#8ab5ed}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:1000px}}td,th{{text-align:left;vertical-align:top;border:1px solid #555;padding:8px}}
th{{background:#3d3d3d}}td pre{{max-width:350px;min-width:65px}}.meta{{color:#aaa}}#filters{{position:sticky;top:0;background:#202020;padding:8px;z-index:1}}
</style><header><h1>Testbox Studio · {escaped(status)}</h1>
<p>{escaped(metadata.get('executed_at', ''))}</p>
<p>{escaped(counts)} · Planned: {escaped(metadata.get('planned_executions', len(records)))} · Completed: {escaped(metadata.get('completed_executions', sum(r['status'] != 'NOT_RUN' for r in records)))}</p>
<p class="meta">Mode: {'headless' if metadata.get('headless') else 'visible'} · Source: {escaped(metadata.get('source_project', metadata.get('source_csv', '')))}</p>
<p><a href="results.json">JSON</a> · <a href="results.csv">Case CSV</a> · <a href="steps.csv">Step CSV</a> · <a href="metrics.csv">Measurements CSV</a> · <a href="unittest.log">Unittest log</a></p>
<p class="meta">Case duration includes setup/cleanup. Named measurements follow the configured timer boundaries.
Interactive pauses and step delays affect elapsed measurements; review playback metadata before drawing performance conclusions.</p></header>
{nfr_section}<div id="filters"><input id="search" placeholder="Search case, browser, text…" aria-label="Search report">
<select id="status" aria-label="Filter status"><option value="">All statuses</option><option>PASS</option><option>FAIL</option><option>ERROR</option><option>SKIP</option><option>NOT_RUN</option></select>
<button id="expand">Expand visible</button><button id="collapse">Collapse all</button></div>
{''.join(sections)}
<script>
const cases=[...document.querySelectorAll('.case')],search=document.getElementById('search'),status=document.getElementById('status');
function filter(){{for(const row of cases)row.hidden=!!((status.value&&row.dataset.status!==status.value)||!row.textContent.toLowerCase().includes(search.value.toLowerCase()));}}
search.addEventListener('input',filter);status.addEventListener('change',filter);
document.getElementById('expand').onclick=()=>cases.forEach(row=>{{if(!row.hidden)row.open=true}});
document.getElementById('collapse').onclick=()=>cases.forEach(row=>row.open=false);
</script></html>'''
    return body


def write_report(document, output):
    document = {**document, "successful": successful_report(document)}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = [{**record, "data_row": int(record.get("row_index", 0)) + 1} for record in document["results"]]
    write_csv(output / "results.csv", ["case_id", "title", "level", "browser", "repetition", "row_index", "data_row", "status", "duration_seconds",
              "assertion_count", "expected", "actual", "known_defect", "runtime_id", "cleanup_error", "evidence"], rows)
    steps, metrics = [], []
    for record in rows:
        context = {key: record.get(key, "") for key in ("case_id", "level", "browser", "repetition", "row_index", "data_row")}
        steps.extend({**context, **step} for step in planned_results(record))
        metrics.extend({**context, **metric} for metric in record.get("metrics", []))
    write_csv(output / "steps.csv", ["case_id", "level", "browser", "repetition", "row_index", "data_row", "index", "execution", "loop_path", "step_id", "phase", "command", "target",
              "input_value", "expected", "actual", "status", "duration_seconds", "evidence"], steps)
    write_csv(output / "metrics.csv", ["case_id", "level", "browser", "repetition", "row_index", "data_row", "name", "elapsed_seconds", "maximum_seconds"], metrics)
    (output / "report.html").write_text(report_html(document, output), encoding="utf-8")


def zip_report(output, target):
    """Export outcomes and captured evidence with portable relative paths."""
    output, target = Path(output), Path(target)
    document = deepcopy(json.loads((output / "results.json").read_text(encoding="utf-8-sig")))
    attachments = {}
    for record in document["results"]:
        for item in [record, *record.get("step_results", [])]:
            portable = []
            for raw in item.get("evidence", []):
                try:
                    source = evidence_path(raw, output)
                    relative = source.relative_to(output.resolve()).as_posix()
                except (ValueError, OSError):
                    continue
                if source.is_file() and source.suffix.lower() in {".png", ".jpg", ".jpeg", ".html", ".txt"}:
                    attachments[relative] = source
                    portable.append(relative)
            item["evidence"] = portable
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative, source in attachments.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for name in ("unittest.log", "compatibility-summary.json", "nfr-summary.json"):
            if (output / name).is_file():
                shutil.copyfile(output / name, root / name)
        for source in (output / "logs").glob("*.txt"):
            if source.resolve().is_relative_to(output.resolve()):
                (root / "logs").mkdir(exist_ok=True)
                shutil.copyfile(source, root / "logs" / source.name)
        write_report(document, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sorted(root.rglob("*")):
                if source.is_file():
                    archive.write(source, source.relative_to(root).as_posix())
    return target
