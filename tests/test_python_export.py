"""Verify portable exports consume their CSV/config, outside the source repository."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from automation.export_runtime import load_project
from automation.exporting import csv_text, export_python
from automation.schema import new_step, script_data, script_record


def sample():
    record = script_record("EXPORT-01")
    record["title"] = "Portable data-driven test"
    record["actions_json"] = json.dumps([
        new_step("open", target="${base_url}", phase="setup"),
        new_step("type", target="id=name", value="${name}"),
        new_step("click", target="id=save"),
        new_step("assert_text", target="id=message", expected="${expected}", timeout=.3),
        new_step("assert_value", target="id=saved", expected="saved", timeout=.3),
        new_step("click", target="id=reset", phase="cleanup")])
    record["dataset_json"] = json.dumps([{"name": "0007", "expected": "0007"}])
    return record


def extract(path, folder):
    with zipfile.ZipFile(path) as archive:
        archive.extractall(folder)


class PythonExportTests(unittest.TestCase):
    def test_levels_runtime_and_csv_preserve_inputs_expected_and_source(self):
        record = sample()
        before = json.dumps(record)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = export_python(root / "suite.zip", [record], {"base_url": "https://example.invalid"})
            extract(root / "suite.zip", root / "outside")
            self.assertEqual(result["levels"], [1, 2])
            self.assertTrue((root / "outside/runtime/automation/engine.py").is_file())
            self.assertFalse((root / "outside/studio").exists())
            self.assertFalse((root / "outside/runtime/automation/exporting.py").exists())
            for level in (1, 2):
                loaded = load_project(root / "outside", level)
                data = script_data(loaded["records"][0], runnable=True)
                self.assertEqual(data["dataset"][0]["name"], "0007")
                self.assertEqual(data["dataset"][0]["step_5_expected"], "saved")
                self.assertEqual(data["steps"][4]["expected"], "${step_5_expected}")
                self.assertTrue(data["steps"][1]["target"].startswith("@export_"))
            self.assertEqual(before, json.dumps(record))

    def test_sparse_rows_preserve_empty_vs_absent_defaults_and_zero_columns(self):
        record = sample()
        record["dataset_json"] = '[{}, {"name":""}]'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_python(root / "suite.zip", [record], {"variables": {"name": "default"}})
            extract(root / "suite.zip", root / "suite")
            rows = script_data(load_project(root / "suite", 2)["records"][0])["dataset"]
            self.assertNotIn("name", rows[0])
            self.assertEqual(rows[1]["name"], "")
            record["actions_json"] = json.dumps([new_step("assert_visible", target="id=ready")])
            record["dataset_json"] = '[{}, {}]'
            export_python(root / "blank.zip", [record], {}, levels=(2,))
            extract(root / "blank.zip", root / "blank")
            rows = script_data(load_project(root / "blank", 2)["records"][0])["dataset"]
            self.assertEqual(rows, [{}, {}])

    def test_uploads_are_packaged_and_missing_file_does_not_replace_previous_zip(self):
        record = sample()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.txt").write_text("0007  ", encoding="utf-8")
            record["actions_json"] = json.dumps([new_step("upload", target="id=file", value="input.txt")])
            export_python(root / "suite.zip", [record], {}, project_dir=root)
            extract(root / "suite.zip", root / "suite")
            project = load_project(root / "suite", 2)
            asset = project["settings"]["upload_assets"]["input.txt"]
            self.assertEqual((root / "suite" / asset).read_text(encoding="utf-8"), "0007  ")
            before = (root / "suite.zip").read_bytes()
            (root / "input.txt").unlink()
            with self.assertRaisesRegex(ValueError, "does not exist"):
                export_python(root / "suite.zip", [record], {}, project_dir=root)
            self.assertEqual(before, (root / "suite.zip").read_bytes())

    def test_legacy_csv_is_exact_and_listing_works_without_source_repo(self):
        from studio.model import template_record
        legacy = template_record("TC-003-001", "create")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_python(root / "suite.zip", [legacy], {})
            extract(root / "suite.zip", root / "suite")
            for level in (1, 2):
                project = load_project(root / "suite", level)
                self.assertEqual(project["records"], [legacy])
                result = subprocess.run([sys.executable, str(root / f"suite/level{level}/test_cases.py"), "--list"],
                    cwd=root, env={**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8"},
                    capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(legacy["case_id"], result.stdout)


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for portable real-browser verification")
class PortableBrowserTests(unittest.TestCase):
    def test_exported_levels_read_changed_csv_and_config_and_support_unittest_discovery(self):
        import threading
        from http.server import ThreadingHTTPServer
        from tests.test_generic_browser import Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                suite = root / "standalone"
                export_python(root / "suite.zip", [sample()], {"base_url": f"http://127.0.0.1:{server.server_port}"})
                extract(root / "suite.zip", suite)
                environment = {**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8", "TESTBOX_HEADLESS": "1"}
                def run(level, output):
                    result = subprocess.run([sys.executable, str(suite / f"level{level}/test_cases.py"), "--headless", "--output", str(root / output)],
                        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=70)
                    report = json.loads(next((root / output).glob("*/results.json")).read_text(encoding="utf-8"))
                    # The traceback/runtime metadata must belong to the export, not
                    # to an accidental import from the development repository.
                    self.assertNotIn(str(Path(__file__).resolve().parents[1]), result.stdout + result.stderr)
                    return result.returncode, report
                for level in (1, 2):
                    code, report = run(level, f"pass{level}")
                    self.assertEqual(code, 0, report)
                    self.assertEqual(report["counts"]["PASS"], 1)
                csv_path = suite / "data/case-EXPORT-01.csv"
                from automation.export_runtime import read_csv
                data = read_csv(csv_path)
                data[0]["step_5_expected"] = "wrong expected"
                csv_path.write_text(csv_text(data, list(data[0])), encoding="utf-8")
                for level in (1, 2):
                    code, report = run(level, f"fail{level}")
                    self.assertEqual(code, 1)
                    self.assertEqual(report["counts"]["FAIL"], 1)
                    self.assertIn("wrong expected", report["results"][0]["actual"])
                    self.assertIn(str(suite / "runtime"), report["results"][0]["actual"])
                # Restore CSV, then break only the Level 2 locator without editing
                # any exported Python. This must affect Level 2, not Level 1.
                data[0]["step_5_expected"] = "saved"
                csv_path.write_text(csv_text(data, list(data[0])), encoding="utf-8")
                config_path = suite / "level2/config/site.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config["locators"]["export_EXPORT-01_4"] = "id=missing"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                code, report = run(2, "changed-locator")
                self.assertEqual(code, 1)
                self.assertEqual(report["counts"]["FAIL"], 1)
                discovery = subprocess.run([sys.executable, "-m", "unittest", "level1.test_cases", "-v"],
                    cwd=suite, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=70)
                self.assertEqual(discovery.returncode, 0, discovery.stdout + discovery.stderr)
                self.assertIn("Ran 1 test", discovery.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_exported_upload_uses_copied_asset_after_original_removed(self):
        import threading
        from http.server import ThreadingHTTPServer
        from tests.test_generic_browser import Handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "upload.txt"
                source.write_text("sample", encoding="utf-8")
                record = sample()
                record["actions_json"] = json.dumps([new_step("open", target="${base_url}"),
                    new_step("upload", target="id=file", value="${file}"),
                    new_step("assert_text", target="id=filename", expected="upload.txt")])
                record["dataset_json"] = '[{"file":"upload.txt"}]'
                export_python(root / "suite.zip", [record], {"base_url": f"http://127.0.0.1:{server.server_port}"}, project_dir=root)
                extract(root / "suite.zip", root / "suite")
                source.unlink()
                result = subprocess.run([sys.executable, str(root / "suite/level2/test_cases.py"), "--headless"],
                    cwd=root, env={**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8"}, capture_output=True,
                    text=True, encoding="utf-8", timeout=70)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
