import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from automation.reporting import planned_results, write_report, zip_report


class ReportingTests(unittest.TestCase):
    def document(self):
        return dict(metadata={"executed_at": "2026-11-25", "headless": True, "stopped": True, "planned_executions": 2},
                    successful=False, counts={"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 1},
                    results=[dict(case_id="CASE-1", title='<script>alert("x")</script>', browser="chrome", level=2,
                        row_index=1, status="SKIP", duration_seconds=1, actual="Stopped by user", cleanup_error="", evidence=[],
                        expected_json={"steps": [{"id": "one", "command": "open", "phase": "test", "enabled": True},
                                                  {"id": "two", "command": "assert_text", "phase": "test", "enabled": True}]},
                        step_results=[{"step_id": "one", "index": 1, "command": "open", "phase": "test", "status": "PASS", "actual": "Opened", "duration_seconds": .1}],
                        metrics=[{"name": "save", "elapsed_seconds": .2, "maximum_seconds": 1}])])

    def test_html_and_csv_preserve_incomplete_status_row_identity_and_unexecuted_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = self.document()
            write_report(document, root)
            page = (root / "report.html").read_text(encoding="utf-8")
            self.assertIn("Testbox Studio · STOPPED", page)
            self.assertNotIn('<script>alert("x")</script>', page)
            self.assertIn("&lt;script&gt;", page)
            self.assertIn("NOT_RUN", page)
            with (root / "results.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["data_row"], "2")
            with (root / "steps.csv").open(encoding="utf-8-sig", newline="") as stream:
                steps = list(csv.DictReader(stream))
            self.assertEqual([r["status"] for r in steps], ["PASS", "NOT_RUN"])
            self.assertEqual(steps[1]["data_row"], "2")

    def test_report_zip_makes_evidence_portable_and_excludes_input_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "run"
            output.mkdir()
            screenshot = output / "evidence" / "case 1.png"
            screenshot.parent.mkdir()
            screenshot.write_bytes(b"fixture evidence")
            (output / "input-snapshot.csv").write_text("private input", encoding="utf-8")
            document = self.document()
            document["results"][0]["evidence"] = [str(screenshot)]
            document["results"][0]["step_results"][0]["evidence"] = [str(screenshot)]
            write_report(document, output)
            target = zip_report(output, root / "report.zip")
            with zipfile.ZipFile(target) as archive:
                self.assertIsNone(archive.testzip())
                self.assertNotIn("input-snapshot.csv", archive.namelist())
                data = json.loads(archive.read("results.json"))
                self.assertEqual(data["results"][0]["evidence"], ["evidence/case 1.png"])
                self.assertIn('href="evidence/case%201.png"', archive.read("report.html").decode("utf-8"))
                self.assertEqual(archive.read("evidence/case 1.png"), b"fixture evidence")

    def test_legacy_expected_extensions_do_not_break_report_generation(self):
        record = {"step_results": [], "expected_json": {"steps": "legacy annotation"}}
        self.assertEqual(planned_results(record), [])
