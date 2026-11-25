"""Persistence, migration and validation contracts for editable browser tests."""

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from automation.runner import preflight
from automation.schema import checked_step, locator, new_step, resolve, script_data, script_record
from studio.exchange import read_table, write_table
from studio.model import Workspace, folder, testcase

ROOT = Path(__file__).resolve().parents[1]


class GenericModelTests(unittest.TestCase):
    def example(self):
        record = script_record("LOGIN-01")
        record["title"] = "Login boundary data"
        record["actions_json"] = json.dumps([new_step("open", target="${base_url}"),
            new_step("type", target="@name", value="${name}"),
            new_step("assert_value", target="@name", expected="${name}")])
        record["dataset_json"] = json.dumps([{"name": "   "}, {"name": "0007"}])
        return record

    def test_old_workspace_migrates_without_rewriting_cases_or_sources(self):
        seed = Workspace.seed()
        old = {"version": 1, "name": seed.name, "nodes": deepcopy(seed.nodes)}
        migrated = Workspace.from_dict(old)
        self.assertEqual(migrated.nodes, old["nodes"])
        self.assertEqual(len(migrated.rows()), 36)
        self.assertEqual(migrated.to_dict()["version"], 2)
        self.assertEqual(Workspace.from_dict(migrated.to_dict()).nodes, old["nodes"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.project.json"
            original = json.dumps(old, ensure_ascii=False).encode("utf-8")
            path.write_bytes(original)
            migrated.save(path)
            self.assertEqual(path.with_name("old.project.v1.backup.json").read_bytes(), original)
            self.assertEqual(Workspace.load(path).nodes, old["nodes"])

    def test_mixed_workspace_and_file_exchange_preserve_executable_and_manual_steps(self):
        workspace = Workspace.seed()
        generic = self.example()
        workspace.add(testcase(generic, [{"action": "Manual source", "expected": "Reference only"}]))
        workspace.settings = {"base_url": "http://example.test", "locators": {"name": "id=name"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            workspace.save(path)
            loaded = Workspace.load(path)
            self.assertEqual(loaded.to_dict(), workspace.to_dict())
            for suffix in (".csv", ".xls", ".xlsx"):
                with self.subTest(suffix=suffix):
                    table = Path(directory) / ("cases" + suffix)
                    write_table(table, workspace.rows())
                    imported = Workspace("Imported")
                    imported.import_rows(read_table(table), None)
                    rows = imported.rows()
                    self.assertEqual(len(rows), 37)
                    actual = next(r for r in rows if r["case_id"] == "LOGIN-01")
                    self.assertEqual(actual["actions_json"], generic["actions_json"])
                    self.assertEqual(script_data(actual)["dataset"], [{"name": "   "}, {"name": "0007"}])
                    self.assertEqual(json.loads(actual["steps_json"])[0]["action"], "Manual source")

    def test_data_variable_failure_identifies_case_row_and_step(self):
        record = self.example()
        record["dataset_json"] = '[{"name":"valid"},{}]'
        with self.assertRaisesRegex(ValueError, r"LOGIN-01, data row 2, step 2: Variable is not defined: name"):
            preflight([record], {"base_url": "http://example.test", "locators": {"name": "id=name"}})

    def test_alias_variables_empty_values_and_missing_names(self):
        self.assertEqual(resolve("${value}", {"value": "   "}), "   ")
        self.assertEqual(resolve("${value}", {"value": ""}), "")
        self.assertEqual(locator("@user", {"user": {"by": "css", "value": "#user"}}), ("css selector", "#user"))
        with self.assertRaisesRegex(ValueError, "not defined"):
            resolve("${missing}", {})
        with self.assertRaisesRegex(ValueError, "not defined"):
            locator("@missing", {})

    def test_disabled_draft_step_and_invalid_timeout(self):
        checked_step(new_step("click", enabled=False))
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                checked_step(new_step("click", target="id=button", timeout=timeout))

    def test_empty_case_can_be_saved_but_cannot_run(self):
        record = script_record("TC-EMPTY")
        script_data(record)
        with self.assertRaisesRegex(ValueError, "enabled test step"):
            preflight([record], {})

    def test_duplicate_ids_are_renamed_without_replacing_steps(self):
        record = self.example()
        workspace = Workspace()
        workspace.import_rows([record], None)
        count, renamed = workspace.import_rows([record], None)
        self.assertEqual((count, renamed), (1, 1))
        rows = workspace.rows()
        self.assertNotEqual(rows[0]["case_id"], rows[1]["case_id"])
        self.assertEqual(rows[1]["original_case_id"], record["case_id"])
        self.assertEqual(rows[0]["actions_json"], rows[1]["actions_json"])


if __name__ == "__main__":
    unittest.main()
