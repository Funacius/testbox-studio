"""Exercise actual Tk editing and snapshot paths without opening browser windows."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.schema import new_step, script_record
from studio.app import Studio
from studio.model import Workspace, testcase


class FinishedProcess:
    stdout = None
    def __init__(self):
        self.stdout = io.StringIO("")
    def poll(self):
        return 0
    def wait(self):
        return 0


class StudioEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "workspace.json"
        workspace = Workspace.seed()
        self.record = script_record("DEMO-01")
        self.record["actions_json"] = json.dumps([new_step("open", target="${base_url}"),
            new_step("assert_visible", target="id=ready")])
        self.uid = workspace.add(testcase(self.record))
        workspace.settings = {"base_url": "http://127.0.0.1:9999", "locators": {}, "variables": {}}
        workspace.save(self.path)
        self.hidden = patch("tkinter.Tk.deiconify")
        self.hidden.start()
        self.app = Studio(self.path)
        self.app.withdraw()
        self.errors = patch("studio.app.messagebox.showerror", side_effect=lambda title, text, **kw: self.fail(f"{title}: {text}"))
        self.errors.start()

    def tearDown(self):
        self.app.destroy()
        self.errors.stop()
        self.hidden.stop()
        self.directory.cleanup()

    def test_edit_duplicate_reorder_toggle_and_save_actual_steps(self):
        app = self.app
        app._show_node(self.uid)
        self.assertEqual(app.notebook.tab(app.script_steps_tab, "state"), "normal")
        self.assertEqual(app.notebook.tab(app.script_data_tab, "state"), "normal")
        editor = app.steps_editor
        editor.tree.selection_set(editor.steps[0]["id"])
        editor.duplicate()
        copied = editor.steps[1]["id"]
        editor.move(1)
        self.assertEqual(editor.steps[2]["id"], copied)
        editor.toggle()
        self.assertFalse(editor.steps[2]["enabled"])
        editor.undo()
        self.assertTrue(editor.steps[2]["enabled"])
        app.script_editor.variables["title"].set("Edited generic test")
        self.assertTrue(app._commit())
        expected = json.loads(app.workspace.find(self.uid)["record"]["actions_json"])
        self.assertEqual(expected, editor.steps)
        self.assertEqual(app.workspace.find(self.uid)["record"]["title"], "Edited generic test")
        self.assertTrue(app._save())
        reloaded = Workspace.load(self.path)
        self.assertEqual(json.loads(reloaded.find(self.uid)["record"]["actions_json"]), expected)
        legacy = next(n for n, _ in app.workspace.walk() if n["kind"] == "case" and n["uid"] != self.uid)
        app._show_node(legacy["uid"])
        self.assertEqual(app.notebook.tab(app.overview_tab, "state"), "normal")
        self.assertEqual(app.notebook.tab(app.steps_tab, "state"), "normal")
        self.assertEqual(app.notebook.tab(app.json_tab, "state"), "normal")
        self.assertEqual(app.notebook.tab(app.script_steps_tab, "state"), "hidden")

    def test_run_uses_current_immutable_steps_and_keeps_credentials_in_environment(self):
        app = self.app
        app._show_node(self.uid)
        app.tree.selection_set(self.uid)
        app.run_vars["username"].set("local-user")
        app.run_vars["password"].set("temporary-secret")
        app.steps_editor.tree.selection_set(app.steps_editor.steps[1]["id"])
        app.steps_editor.toggle()
        with patch("studio.app.subprocess.Popen", return_value=FinishedProcess()) as process, \
             patch("studio.app.website_status", return_value="Fixture ready"):
            app._run()
        args = process.call_args.args[0]
        self.assertIn("automation.runner", args)
        snapshot = Path(args[args.index("--project") + 1])
        doc = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertFalse(json.loads(doc["records"][0]["actions_json"])[1]["enabled"])
        self.assertNotIn("temporary-secret", snapshot.read_text(encoding="utf-8"))
        self.assertEqual(process.call_args.kwargs["env"]["TESTBOX_VAR_password"], "temporary-secret")
        self.assertEqual(app.run_total, 1)

    def test_python_export_commits_selected_edits_and_excludes_run_credentials(self):
        import zipfile
        app = self.app
        app._show_node(self.uid)
        app.tree.selection_set(self.uid)
        app.script_editor.variables["title"].set("Export current edited title")
        app.run_vars["username"].set("run-only-user")
        app.run_vars["password"].set("run-only-secret")
        fake = type("Dialog", (), {"result": {"scope": "Selection", "levels": "Both levels"}})()
        destination = Path(self.directory.name) / "export.zip"
        with patch("studio.app.FormDialog", return_value=fake), \
             patch("studio.app.filedialog.asksaveasfilename", return_value=str(destination)), \
             patch("studio.app.messagebox.showinfo"), \
             patch("studio.app.subprocess.Popen") as browser:
            app._export_python()
        browser.assert_not_called()
        self.assertTrue(destination.is_file())
        with zipfile.ZipFile(destination) as archive:
            text = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
            self.assertIn("Export current edited title", text)
            self.assertNotIn("run-only-secret", text)
            self.assertNotIn("run-only-user", text)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["cases"], [self.record["case_id"]])
            self.assertEqual(manifest["levels"], [1, 2])

    def test_dataset_and_variables_grid_apply_and_undo_exact_values(self):
        app = self.app
        app._show_node(self.uid)
        table = app.script_editor.dataset
        table.load_records([{"username": "   ", "expected": "empty"}])
        table.set_cell(0, 0, "0007")
        table.undo()
        self.assertEqual(table.records()[0]["username"], "   ")
        table.redo()
        table.add_row()
        variables = app.script_editor.case_variables
        variables.load_records([{"Variable": "message", "Value": "  exact  "}])
        app._editor_changed()
        self.assertTrue(app._commit())
        record = app.workspace.find(self.uid)["record"]
        self.assertEqual(json.loads(record["dataset_json"]), [{"username": "0007", "expected": "empty"}, {"username": "", "expected": ""}])
        self.assertEqual(json.loads(record["variables_json"]), {"message": "  exact  "})

    def test_dataset_import_targets_selected_case_and_preserves_its_steps(self):
        app = self.app
        app._show_node(self.uid)
        app.tree.selection_set(self.uid)
        original_steps = app.workspace.find(self.uid)["record"]["actions_json"]
        imported = dict(kind="dataset", dataset=[{"content": "   "}, {"content": "0007"}], use_selected=True,
                        profile=("assignment", {"header": 0, "mode": "Dataset", "mapping": {}}))
        fake = type("Dialog", (), {"result": imported})()
        with patch("studio.app.filedialog.askopenfilename", return_value="sample.csv"), \
             patch("studio.app.ImportWizard", return_value=fake), \
             patch("studio.app.messagebox.askyesno", return_value=True):
            app._import()
        record = app.workspace.find(self.uid)["record"]
        self.assertEqual(record["actions_json"], original_steps)
        self.assertEqual(json.loads(record["dataset_json"]), imported["dataset"])
        self.assertIn("assignment", app.workspace.settings["import_profiles"])

    def test_import_wizard_builds_a_foreign_steps_file_without_gradebook_columns(self):
        from studio.import_wizard import ImportWizard
        path = Path(__file__).resolve().parents[1] / "examples/login-steps.csv"
        with patch("tkinter.Toplevel.wait_window"), patch("tkinter.Toplevel.grab_set"):
            dialog = ImportWizard(self.app, path)
        try:
            self.assertEqual(dialog.mode.get(), "Steps table")
            dialog.show_preview()
            self.assertIn("1 cases", dialog.preview.get("1.0", "end-1c"))
            result = dialog.build()
            self.assertEqual(result["records"][0]["case_id"], "DEMO-LOGIN")
            self.assertEqual(len(json.loads(result["records"][0]["actions_json"])), 5)
        finally:
            dialog.destroy()

    def test_unreachable_website_blocks_browser_start_with_readable_error(self):
        app = self.app
        app._show_node(self.uid)
        app.tree.selection_set(self.uid)
        with patch("studio.app.website_status", side_effect=ValueError("Start the local website")), \
             patch("studio.app.messagebox.showerror") as error, patch("studio.app.subprocess.Popen") as process:
            app._run()
        process.assert_not_called()
        self.assertIn("Start the local website", error.call_args.args[1])
        self.assertIsNone(app.last_output)

    def test_selected_environment_applies_and_persists_without_credentials(self):
        app = self.app
        app.workspace.settings["environments"] = {"Staging": {"base_url": "http://127.0.0.1:8765", "browser": "Edge", "headless": False,
                                                            "window": [1280, 800], "variables": {"course": "7"}}}
        app.environment.set("Staging")
        app._select_environment()
        self.assertEqual(app.run_vars["base_url"].get(), "http://127.0.0.1:8765")
        self.assertEqual(app.run_vars["browser"].get(), "Edge")
        self.assertFalse(app.headless.get())
        self.assertEqual(app._effective_settings()["window"], [1280, 800])
        self.assertEqual(app._effective_settings()["variables"]["course"], "7")
        self.assertTrue(app._save())
        self.assertEqual(Workspace.load(self.path).settings["active_environment"], "Staging")

    def test_playback_controls_write_versioned_commands_and_stop_request(self):
        app = self.app
        app._show_node(self.uid)
        app.tree.selection_set(self.uid)
        app.start_paused.set(True)
        process = FinishedProcess()
        process.poll = lambda: None
        with patch("studio.app.subprocess.Popen", return_value=process) as launch, \
             patch("studio.app.website_status", return_value="ready"):
            app._run()
        self.assertIn("--control-file", launch.call_args.args[0])
        self.assertEqual(json.loads(app.playback_path.read_text())["command"], "pause")
        app._playback("next")
        self.assertEqual(json.loads(app.playback_path.read_text()), {"command": "next", "sequence": 1})
        app._stop()
        self.assertTrue(app.stop_file.exists())
        self.assertEqual(json.loads(app.playback_path.read_text()), {"command": "stop", "sequence": 2})
        app.process = None

    def test_locator_library_is_saved_to_the_selected_environment(self):
        app = self.app
        app.workspace.settings["environments"] = {"Staging": {"base_url": "http://127.0.0.1:8765"}}
        app.environment.set("Staging")
        app._select_environment()
        library = {"username": {"by": "id", "value": "username"}}
        dialog = type("Dialog", (), {"result": library})()
        with patch("studio.app.LocatorLibraryDialog", return_value=dialog):
            app._locator_library()
        self.assertEqual(app._effective_settings()["locators"], library)
        self.assertEqual(app.workspace.settings["environments"]["Staging"]["locators"], library)

    def test_general_case_hides_gradebook_controls_and_report_viewer_shows_unexecuted_steps(self):
        from automation.reporting import write_report
        from studio.report_viewer import ReportViewer
        app = self.app
        app._show_node(self.uid)
        self.assertEqual(app.run_widgets["course_id"].winfo_manager(), "")
        record = dict(case_id="R-1", title="Stopped", browser="chrome", level=2, row_index=1, status="SKIP", actual="Stopped by user",
                      duration_seconds=.1, cleanup_error="", evidence=[], expected_json={"steps": [{"id": "unreached", "command": "click", "target": "id=save"}]}, step_results=[])
        output = Path(self.directory.name) / "report"
        write_report(dict(metadata={"stopped": True}, successful=False, counts={"SKIP": 1}, results=[record]), output)
        viewer = ReportViewer(app, output, lambda path: None)
        try:
            first = viewer.cases.get_children()[0]
            self.assertEqual(viewer.cases.item(first, "values")[2], "2")
            self.assertEqual(viewer.current_steps[0]["status"], "NOT_RUN")
            viewer.filter.set("PASS")
            viewer.refresh()
            self.assertFalse(viewer.cases.get_children())
        finally:
            viewer.destroy()


if __name__ == "__main__":
    unittest.main()
