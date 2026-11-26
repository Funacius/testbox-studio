"""Reusable case templates; project URLs and locator aliases remain project settings."""

import json
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from automation.schema import is_script, new_step, script_data, script_record, validate_records
from studio.dialogs import FormDialog
from studio.theme import PANEL, dark_text


def builtins():
    blank = script_record("TEMPLATE")
    blank["title"] = "Blank browser test"
    smoke = script_record("TEMPLATE")
    smoke.update(title="Open page and verify body", expected_result="The configured page opens and its body is visible.",
        actions_json=json.dumps([new_step("open", target="${base_url}", phase="setup"), new_step("assert_visible", target="css=body")]))
    login = script_record("TEMPLATE")
    login.update(title="Data-driven login (local demo)", expected_result="Each data row has its own expected login message.",
        actions_json=json.dumps([new_step("open", target="${base_url}", phase="setup"),
            new_step("type", target="id=username", value="${username}"),
            new_step("type", target="id=password", value="${password}"),
            new_step("click", target="id=login"), new_step("assert_text", target="id=message", expected="${expected_message}")]),
        dataset_json=json.dumps([dict(username="demo", password="demo123", expected_message="Welcome demo"),
            dict(username="demo", password="wrong", expected_message="Invalid credentials")]),
        notes="Start tools/demo_site.py and set Base URL to http://127.0.0.1:9542. Adapt selectors and expected data for another site.")
    return {record["title"]: record for record in (blank, smoke, login)}


def checked_library(value):
    if not isinstance(value, dict) or any(not isinstance(name, str) or not name.strip() for name in value):
        raise ValueError("Templates must map nonempty names to case records")
    for record in value.values():
        validate_records([record])
    return deepcopy(value)


def instantiate(record, case_id, title=None):
    value = deepcopy(record)
    value.update(case_id=case_id, title=title or record["title"])
    if is_script(value):
        steps = script_data(value)["steps"]
        for step in steps:
            step["id"] = uuid4().hex
        value["actions_json"] = json.dumps(steps, ensure_ascii=False)
    validate_records([value])
    return value


class TemplateDialog(tk.Toplevel):
    def __init__(self, parent, library, current_record=None):
        self.library = checked_library(library)
        self.defaults = builtins()
        super().__init__(parent)
        self.withdraw()
        self.title("Case templates")
        self.configure(bg=PANEL)
        self.geometry("1050x720")
        self.transient(parent)
        self.result, self.current_record = None, deepcopy(current_record)
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Reusable case templates", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Create a new case from a template, or save the current case with its setup/test/cleanup and dataset.\nTemplates keep case content; configure URL and @locator aliases in the destination project.",
            style="Muted.TLabel", wraplength=1000).pack(anchor="w", pady=(6, 14))
        columns = ttk.Frame(body)
        columns.pack(fill="both", expand=True)
        self.list = ttk.Treeview(columns, show="tree", selectmode="browse", height=12)
        self.list.column("#0", width=300, minwidth=200)
        self.list.pack(side="left", fill="both", expand=False)
        scroll = ttk.Scrollbar(columns, orient="vertical", command=self.list.yview)
        scroll.pack(side="left", fill="y")
        self.list.configure(yscrollcommand=scroll.set)
        self.preview = dark_text(columns, height=12)
        self.preview.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.preview.configure(state="disabled")
        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(14, 0))
        for text, command in (("Save current as…", self.save_current), ("Delete saved", self.delete),
                              ("Import template…", self.import_template), ("Export selected…", self.export_template)):
            ttk.Button(controls, text=text, command=command).pack(side="left", padx=(0, 6))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply library", command=lambda: self.finish(False)).pack(side="right", padx=8)
        ttk.Button(buttons, text="Create case from selected", style="Primary.TButton", command=lambda: self.finish(True)).pack(side="right")
        self.list.bind("<<TreeviewSelect>>", lambda _: self.show())
        self.refresh()
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def refresh(self, select=None):
        self.list.delete(*self.list.get_children())
        self.entries = {}
        for prefix, values in (("Built-in", self.defaults), ("Saved", self.library)):
            for name, record in values.items():
                key = str(len(self.entries))
                self.entries[key] = (prefix, name, record)
                self.list.insert("", "end", iid=key, text=f"{prefix} · {name}")
                if select == (prefix, name):
                    self.list.selection_set(key)
        if not self.list.selection():
            self.list.selection_set("0")
        self.show()

    def selected(self):
        selection = self.list.selection()
        return self.entries[selection[0]] if selection else None

    def show(self):
        entry = self.selected()
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        if entry:
            record = entry[2]
            if is_script(record):
                data = script_data(record)
                summary = f"{entry[1]}\n\n{record.get('expected_result', '')}\n\n{len(data['dataset'])} data rows\n\n"
                summary += "\n".join(f"{i}. [{s['phase']}] {s['command']}  {s['target']}  {s['value']}  => {s['expected']}" for i, s in enumerate(data["steps"], 1))
                summary += "\n\n" + record.get("notes", "")
            else:
                summary = json.dumps(record, ensure_ascii=False, indent=2)
            self.preview.insert("1.0", summary)
        self.preview.configure(state="disabled")

    def save_current(self):
        if not self.current_record:
            messagebox.showinfo("Select a case", "Select a case in the workspace before opening templates.", parent=self)
            return
        dialog = FormDialog(self, "Save case template", [("name", "Template name", self.current_record["title"], None)])
        self.grab_set()
        if dialog.result:
            name = dialog.result["name"]
            if name in self.library and not messagebox.askyesno("Replace template", f"Replace saved template '{name}'?", parent=self):
                return
            self.library[name] = deepcopy(self.current_record)
            self.refresh(("Saved", name))

    def delete(self):
        entry = self.selected()
        if entry and entry[0] == "Saved":
            del self.library[entry[1]]
            self.refresh()

    def import_template(self):
        name = filedialog.askopenfilename(parent=self, title="Import case template", filetypes=[("Template JSON", "*.json")])
        if not name:
            return
        try:
            document = json.loads(Path(name).read_text(encoding="utf-8-sig"))
            if document.get("format") != "testbox-template-1":
                raise ValueError("Choose a Testbox case template JSON")
            template = checked_library({document["name"]: document["record"]})
            key = next(iter(template))
            if key in self.library and not messagebox.askyesno("Replace template", f"Replace saved template '{key}'?", parent=self):
                return
            self.library.update(template)
            self.refresh(("Saved", key))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Import template failed", str(exc), parent=self)

    def export_template(self):
        entry = self.selected()
        if not entry:
            return
        name = filedialog.asksaveasfilename(parent=self, title="Export case template", defaultextension=".json", initialfile="case-template.json", filetypes=[("Template JSON", "*.json")])
        if name:
            try:
                Path(name).write_text(json.dumps(dict(format="testbox-template-1", name=entry[1], record=entry[2]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Export template failed", str(exc), parent=self)

    def finish(self, create):
        entry = self.selected()
        self.result = dict(templates=deepcopy(self.library), record=deepcopy(entry[2]) if create and entry else None)
        self.destroy()
