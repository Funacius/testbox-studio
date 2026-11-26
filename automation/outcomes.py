"""Represent every planned dataset/matrix cell, including work never started."""

from copy import deepcopy


def identity(record):
    return tuple(record.get(key, default) for key, default in (("level", 0), ("browser", ""), ("case_id", ""), ("row_index", 0), ("repetition", 1)))


def report_plan(expected):
    expected = deepcopy(expected)
    if isinstance(expected, dict) and isinstance(expected.get("steps"), list):
        # A report's plan retains oracles and step identity, not literal input
        # values from a source snapshot that might never have been entered.
        for step in expected["steps"]:
            step.pop("value", None)
    return expected


def not_run(case_id, title, level, browser, row_index, expected, expected_result="", known_defect="", repetition=1):
    return dict(case_id=case_id, title=title, level=level, browser=browser, row_index=row_index,
        repetition=repetition, status="NOT_RUN", duration_seconds=0, assertion_count=0,
        expected=expected_result, expected_json=report_plan(expected),
        actual="This planned execution was not started. See run status and infrastructure details.",
        known_defect=known_defect, runtime_id="", cleanup_error="Not started", evidence=[], capabilities={}, step_results=[], metrics=[])


def complete_test_results(records, tests):
    by_key = {identity(record): record for record in records}
    result = []
    for test in tests:
        planned = not_run(test.case.case_id, test.case.title, test.level, test.browser, getattr(test, "row_index", 0),
            test.case.expected, test.case.expected_result, test.case.known_defect)
        result.append(by_key.get(identity(planned), planned))
    return result


def complete_matrix(records, source_records, levels, browsers, repetitions):
    import json
    from automation.schema import is_script, script_data
    by_key = {identity(record): record for record in records}
    result = []
    for level in levels:
        for browser in browsers:
            for repetition in range(1, repetitions + 1):
                for record in source_records:
                    data = script_data(record) if is_script(record) else None
                    expected = {"steps": data["steps"]} if data else json.loads(record["expected_json"])
                    for row_index in range(len(data["dataset"]) if data else 1):
                        planned = not_run(record["case_id"], record["title"], level, browser, row_index, expected,
                            record.get("expected_result", ""), record.get("known_defect", ""), repetition)
                        result.append(by_key.get(identity(planned), planned))
    return result


def status_counts(records):
    result = {status: sum(r["status"] == status for r in records) for status in ("PASS", "FAIL", "ERROR", "SKIP")}
    pending = sum(r["status"] == "NOT_RUN" for r in records)
    if pending:
        result["NOT_RUN"] = pending
    return result
