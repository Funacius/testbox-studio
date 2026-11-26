"""Final UI audit: empty projects, environment state, large imports and ownership."""

import csv
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from studio.app import Studio
from studio.background import BackgroundTask
from studio.importing import read_grids
from studio.model import Workspace


class FinalUiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.hidden = patch("tkinter.Tk.deiconify")
        self.hidden.start()
        self.app = Studio(self.root / "new.json")
        self.app.withdraw()

    def tearDown(self):
        self.app.destroy()
        self.hidden.stop()
        self.directory.cleanup()

    def test_empty_workspace_hides_gradebook_tabs_and_nfr_fields_explain_matrix(self):
        app = self.app
        for frame in (app.overview_tab, app.steps_tab, app.json_tab, app.script_data_tab, app.script_steps_tab):
            self.assertEqual(app.notebook.tab(frame, "state"), "hidden")
        self.assertIn("NOT SAVED", app.saved_label.cget("text"))
        self.assertEqual(str(app.apply_button.cget("state")), "disabled")
        app.run_vars["mode"].set("Compatibility NFR")
        self.assertEqual(str(app.run_widgets["browser"].cget("state")), "disabled")
        self.assertIn("NFR settings", app.run_labels["level"].cget("text"))
        app.run_vars["mode"].set("Functional")
        self.assertEqual(str(app.run_widgets["browser"].cget("state")), "readonly")

    def test_environment_undo_redo_and_switch_to_current_restore_visible_values(self):
        app = self.app
        app.workspace.settings = dict(base_url="http://default.test", browser="Chrome", environments={
            "Staging": dict(base_url="http://staging.test", browser="Edge", headless=False)})
        app.run_vars["password"].set("runtime-only")
        app._sync_settings_view()
        app.environment.set("Staging")
        app._select_environment()
        self.assertEqual(app.run_vars["base_url"].get(), "http://staging.test")
        app._undo()
        self.assertEqual(app.environment.get(), "(current)")
        self.assertEqual(app.run_vars["base_url"].get(), "http://default.test")
        app._redo()
        self.assertEqual(app.environment.get(), "Staging")
        self.assertEqual(app.run_vars["browser"].get(), "Edge")
        self.assertEqual(app.run_vars["password"].get(), "runtime-only")
        app.environment.set("(current)")
        app._select_environment()
        self.assertEqual(app.run_vars["base_url"].get(), "http://default.test")
        self.assertTrue(app.headless.get())

    def test_folder_case_management_persists_order_and_last_case_delete_clears_editor(self):
        app = self.app
        def dialog(result, action):
            with patch("studio.app.FormDialog", return_value=SimpleNamespace(result=result)):
                action()
        dialog({"name": "Folder A"}, app._new_folder)
        parent = app._primary()
        dialog({"name": "Case A", "workflow": "steps"}, app._new_case)
        case = app._primary()
        self.assertEqual(app.workspace.parent_uid(case), parent)
        dialog({"name": "Renamed case"}, app._rename)
        self.assertEqual(app.workspace.find(case)["record"]["title"], "Renamed case")
        app._duplicate()
        clone = app._primary()
        self.assertNotEqual(app.workspace.find(clone)["record"]["case_id"], app.workspace.find(case)["record"]["case_id"])
        app._reorder(-1)
        self.assertEqual(app.workspace.find(parent)["children"][0]["uid"], clone)
        dialog({"folder": "Workspace root"}, app._move_dialog)
        self.assertIsNone(app.workspace.parent_uid(clone))
        app._undo()
        self.assertEqual(app.workspace.parent_uid(clone), parent)
        app._redo()
        self.assertIsNone(app.workspace.parent_uid(clone))
        self.assertTrue(app._save())
        self.assertEqual(Workspace.load(app.workspace_path).to_dict(), app.workspace.to_dict())
        app.tree.selection_set(parent)
        app._show_node(parent)
        with patch("studio.app.messagebox.askyesno", return_value=True):
            app._delete()
        app.tree.selection_set(clone)
        app._show_node(clone)
        with patch("studio.app.messagebox.askyesno", return_value=True):
            app._delete()
        self.assertEqual(app.workspace.nodes, [])
        self.assertEqual(app.notebook.tab(app.script_data_tab, "state"), "hidden")
        self.assertEqual(app.notebook.tab(app.script_steps_tab, "state"), "hidden")
        self.assertEqual(str(app.apply_button.cget("state")), "disabled")
        app._undo()
        self.assertEqual(len(app.workspace.rows()), 1)
        self.assertEqual(app.notebook.tab(app.script_data_tab, "state"), "normal")

    def test_utf16_and_selected_legacy_encoding_preserve_exact_values(self):
        for encoding in ("utf-16", "utf-32", "utf-8-sig", "cp1258"):
            path = self.root / (encoding + ".csv")
            with path.open("w", encoding=encoding, newline="") as stream:
                csv.writer(stream).writerows([["name", "value"], ["Thái", "  0007  "]])
            actual = read_grids(path, "auto" if encoding != "cp1258" else encoding)[0]["rows"]
            self.assertEqual(actual[1], ["Thái", "  0007  "])
        canceled = threading.Event()
        canceled.set()
        with self.assertRaisesRegex(ValueError, "canceled"):
            read_grids(path, encoding, canceled)

    def test_large_dataset_pages_preserve_absolute_row_edits_and_undo(self):
        from studio.table_editor import TableEditor
        table = TableEditor(self.app, lambda: None)
        rows = [{"value": f"{i:05}"} for i in range(20123)]
        table.load_records(rows)
        self.assertEqual(len(table.tree.get_children()), 500)
        table.change_page(1)
        self.assertEqual(table.tree.get_children()[0], "500")
        table.set_cell(510, 0, "  0007  ")
        self.assertEqual(table.records()[510]["value"], "  0007  ")
        table.undo()
        self.assertEqual(table.records(), rows)
        table.change_page(100)
        self.assertEqual(len(table.tree.get_children()), 123)
        self.assertIn("20123", table.page_label.cget("text"))

    def test_background_loading_runs_tk_heartbeat_and_can_cancel(self):
        heartbeat = threading.Event()
        self.app.after(15, heartbeat.set)
        with patch("tkinter.Toplevel.deiconify"):
            job = BackgroundTask(self.app, "Read fixture", lambda canceled, _: heartbeat.wait(2))
        self.assertTrue(job.result)
        self.assertTrue(heartbeat.is_set())
        self.assertIsNone(job.error)
        def cancel_job():
            for child in self.app.winfo_children():
                if isinstance(child, BackgroundTask):
                    child.destroy()
        self.app.after(20, cancel_job)
        with patch("tkinter.Toplevel.deiconify"):
            job = BackgroundTask(self.app, "Cancel fixture", lambda canceled, _: canceled.wait(2))
        self.assertIsNone(job.result)
        self.assertTrue(job.cancelled.is_set())

    def test_large_csv_read_keeps_the_event_loop_active(self):
        from studio.import_wizard import load_grids
        path = self.root / "large.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows([["index", "value"], *[[str(i), "exact text " * 3] for i in range(20000)]])
        heartbeat = threading.Event()
        self.app.after(15, heartbeat.set)
        with patch("tkinter.Toplevel.deiconify"):
            grids = load_grids(self.app, path)
        self.assertTrue(heartbeat.is_set())
        self.assertEqual(len(grids[0]["rows"]), 20001)
        self.assertEqual(grids[0]["rows"][-1], ["19999", "exact text " * 3])

    def test_application_close_waits_for_recorder_owned_session(self):
        from studio.recorder_dialog import RecorderDialog
        from automation.schema import new_step
        class FakeSession:
            def __init__(self, settings):
                self.driver, self.mode = None, "idle"
                self.opened, self.closed = threading.Event(), threading.Event()
            def open(self, url):
                self.driver = object()
                self.opened.set()
                return new_step("open", target=url)
            def poll(self):
                return []
            def set_mode(self, mode):
                self.mode = mode
            def close(self):
                self.driver = None
                self.closed.set()
        session = FakeSession({})
        with patch("studio.recorder_dialog.RecorderSession", return_value=session), patch("tkinter.Toplevel.wait_window"), \
             patch("tkinter.Toplevel.grab_set"), patch("tkinter.Toplevel.deiconify"):
            dialog = RecorderDialog(self.app, {})
        dialog.enqueue("open", "http://fixture.test")
        deadline = time.monotonic() + 3
        while not session.opened.is_set() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertTrue(session.opened.is_set())
        with patch.object(self.app, "_confirm_discard", return_value=False) as confirm:
            self.app._close()
            deadline = time.monotonic() + 3
            while (dialog.winfo_exists() or not confirm.called) and time.monotonic() < deadline:
                self.app.update()
                time.sleep(.01)
            self.assertTrue(session.closed.is_set())
            self.assertFalse(dialog.winfo_exists())
            self.assertTrue(confirm.called)
