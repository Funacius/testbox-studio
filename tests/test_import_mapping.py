"""Import foreign column schemas as explicit steps or lossless data tables."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.runner import preflight, variables_for
from automation.schema import script_data, script_record
from studio.importing import guess_header, headings, import_selection, map_dataset, map_steps, read_grids, suggest_mapping


class MappingTests(unittest.TestCase):
    def test_multiline_cases_header_and_custom_mapping(self):
        grid = [["Class report"], [], ["Test ID", "Test Case Name", "Action", "Selector", "Input", "Expected Result"],
                ["QUIZ 1", "Start quiz", "open", "http://example.test", "", ""],
                ["", "", "type", "id=answer", "  A  ", ""],
                ["", "", "assert_value", "id=answer", "", "  A  "],
                ["QUIZ_1", "Other case", "assert_visible", "id=ready", "", ""]]
        header = guess_header(grid)
        self.assertEqual(header, 2)
        mapping = suggest_mapping(headings(grid, header))
        records, drafts = map_steps(grid, header, mapping)
        self.assertEqual(drafts, 0)
        self.assertEqual([r["case_id"] for r in records], ["QUIZ_1", "QUIZ_1-2"])
        self.assertEqual(records[0]["original_case_id"], "QUIZ 1")
        steps = script_data(records[0])["steps"]
        self.assertEqual(steps[1]["value"], "  A  ")
        self.assertEqual(steps[2]["expected"], "  A  ")
        self.assertEqual(len(steps), 3)

    def test_manual_prose_is_not_silently_executable_or_reported_as_pass(self):
        grid = [["ID", "Steps", "Expected"], ["TC-1", "Click the course and start the quiz", "Quiz is ready"]]
        records, drafts = map_steps(grid, 0, suggest_mapping(grid[0]))
        self.assertEqual(drafts, 1)
        step = script_data(records[0])["steps"][0]
        self.assertEqual(step["command"], "note")
        self.assertFalse(step["enabled"])
        self.assertEqual(step["description"], grid[1][1])
        with self.assertRaisesRegex(ValueError, "enabled test step"):
            preflight(records, {})

    def test_dataset_columns_are_unique_and_exact_values_are_preserved(self):
        data, columns = map_dataset([["User name", "User-name", "123", "Expected"], ["   ", "0001", "", "=literal"]], 0)
        self.assertEqual(columns, {"User name": "User_name", "User-name": "User_name_2", "123": "column_123", "Expected": "Expected"})
        self.assertEqual(data[0], {"User_name": "   ", "User_name_2": "0001", "column_123": "", "Expected": "=literal"})

    def test_invalid_row_mapping_reports_location_without_partial_import(self):
        with self.assertRaisesRegex(ValueError, "Row 2.*missing Case ID"):
            map_steps([["ID", "Action"], ["", "open"]], 0, {"case_id": "ID", "command": "Action"})
        with self.assertRaisesRegex(ValueError, "duplicate column"):
            map_dataset([["username", "username"], ["a", "b"]], 0)

    def test_sheet_choice_and_formula_rejection_are_explicit(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.xlsx"
            workbook = openpyxl.Workbook()
            workbook.active.title = "Summary"
            workbook.active.append(["Total", "=1+1"])
            data = workbook.create_sheet("Assignment data")
            data.append(["content", "expected"])
            data.append(["0007", "   "])
            workbook.save(path)
            workbook.close()
            grids = read_grids(path)
            selected = next(g for g in grids if g["name"] == "Assignment data")
            result = import_selection(path, selected, 0, "Dataset", {})
            self.assertEqual(result["dataset"], [{"content": "0007", "expected": "   "}])
            with self.assertRaisesRegex(ValueError, "Formula at row 1"):
                import_selection(path, grids[0], 0, "Dataset", {})

    def test_dataset_values_override_default_credentials(self):
        record = script_record("DATA-1")
        with patch.dict("os.environ", {"TESTBOX_VAR_username": "default-user"}):
            variables = variables_for(record, {"username": "invalid-user", "password": ""}, {}, "run")
        self.assertEqual(variables["username"], "invalid-user")
        self.assertEqual(variables["password"], "")


if __name__ == "__main__":
    unittest.main()
