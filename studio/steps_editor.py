"""Editable executable steps, with a local undo history and lossless text fields."""

from __future__ import annotations

import json
import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, ttk
from uuid import uuid4

from automation.schema import COMMANDS, PHASES, checked_step, new_step, script_data
from studio.theme import PANEL, MUTED, dark_text
from studio.table_editor import TableEditor


class StepDialog(tk.Toplevel):
    def __init__(self, parent, step):
        super().__init__(parent)
        self.title("Edit executable step")
        self.configure(bg=PANEL)
        self.transient(parent)
        self.result = None
        self.step = deepcopy(step)
        self.geometry("780x720")
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.fields = {}
        for row, (key, label, choices) in enumerate((
            ("command", "Action", tuple(COMMANDS)), ("phase", "Phase", PHASES),
            ("target", "Target / locator", None), ("timeout", "Timeout (seconds)", None),
            ("description", "Description", None))):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            var = tk.StringVar(self, str(step.get(key, "")))
            self.fields[key] = var
            widget = ttk.Combobox(body, textvariable=var, values=choices, state="readonly") if choices else ttk.Entry(body, textvariable=var)
            widget.grid(row=row, column=1, sticky="ew", pady=5)
        self.help_text = ttk.Label(body, text="", wraplength=710, style="Muted.TLabel")
        self.help_text.grid(row=5, column=0, columnspan=2, sticky="w", pady=8)
        self.fields["command"].trace_add("write", self._help)
        self._help()
        ttk.Label(body, text="Target examples: id=username, css=button[type=submit], xpath=//button, @login_button",
                  style="Muted.TLabel", wraplength=710).grid(row=6, column=0, columnspan=2, sticky="w", pady=5)
        self.texts = {}
        for row, key in ((7, "value"), (9, "expected")):
            ttk.Label(body, text=key.title() + " (exact text, including spaces)").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 3))
            text = dark_text(body, height=4)
            text.grid(row=row + 1, column=0, columnspan=2, sticky="nsew")
            text.insert("1.0", step.get(key, ""))
            body.rowconfigure(row + 1, weight=1)
            self.texts[key] = text
        self.enabled = tk.BooleanVar(self, step.get("enabled", True))
        self.breakpoint = tk.BooleanVar(self, step.get("breakpoint", False))
        options = ttk.Frame(body)
        options.grid(row=11, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Checkbutton(options, text="Enabled", variable=self.enabled).pack(side="left")
        ttk.Checkbutton(options, text="Breakpoint", variable=self.breakpoint).pack(side="left", padx=16)
        ttk.Button(options, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(options, text="Apply step", style="Primary.TButton", command=self.submit).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    def _help(self, *_):
        self.help_text.configure(text=COMMANDS[self.fields["command"].get()][3] + " Cleanup runs without pause or breakpoints.")

    def submit(self):
        try:
            value = {**self.step, **{key: var.get() for key, var in self.fields.items()},
                     **{key: text.get("1.0", "end-1c") for key, text in self.texts.items()},
                     "enabled": self.enabled.get(), "breakpoint": self.breakpoint.get()}
            self.result = checked_step(value)
        except ValueError as exc:
            messagebox.showerror("Invalid step", str(exc), parent=self)
            return
        self.destroy()


class StepsEditor(ttk.Frame):
    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.on_change = on_change
        self.steps, self.history, self.future = [], [], []
        self.drag_id = None
        ttk.Label(self, text="These are executable steps. Setup runs first; cleanup runs even after failure.",
                  wraplength=690, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        commands = ttk.Frame(self)
        commands.pack(fill="x", pady=(0, 7))
        for label, fn in (("＋ Step", self.add), ("Edit", self.edit), ("Copy", self.duplicate),
                          ("Delete", self.delete), ("↑", lambda: self.move(-1)),
                          ("↓", lambda: self.move(1)), ("On/off", self.toggle)):
            ttk.Button(commands, text=label, command=fn, style="Small.TButton").pack(side="left", padx=(0, 4))
        more = ttk.Frame(self)
        more.pack(fill="x", pady=(0, 8))
        ttk.Button(more, text="Undo steps", command=self.undo, style="Small.TButton").pack(side="left")
        ttk.Button(more, text="Redo steps", command=self.redo, style="Small.TButton").pack(side="left", padx=5)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("n", "on", "phase", "command", "target", "value", "expected"), show="headings", selectmode="browse")
        for key, label, width in (("n", "#", 35), ("on", "ON", 35), ("phase", "PHASE", 70),
                                   ("command", "ACTION", 130), ("target", "TARGET", 160),
                                   ("value", "VALUE", 140), ("expected", "EXPECTED", 150)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=30, stretch=key in {"target", "value", "expected"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda _: self.edit())
        self.tree.bind("<Delete>", lambda _: self.delete())
        self.tree.bind("<Control-z>", lambda _: (self.undo(), "break")[-1])
        self.tree.bind("<Control-y>", lambda _: (self.redo(), "break")[-1])
        self.tree.bind("<ButtonPress-1>", lambda e: setattr(self, "drag_id", self.tree.identify_row(e.y)), add=True)
        self.tree.bind("<ButtonRelease-1>", self.drop, add=True)
        self.tree.tag_configure("disabled", foreground=MUTED)

    def load(self, steps):
        self.steps = deepcopy(steps)
        self.history.clear()
        self.future.clear()
        self.refresh()

    def refresh(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for index, step in enumerate(self.steps, 1):
            self.tree.insert("", "end", iid=step["id"], values=(index, "✓" if step["enabled"] else "—", step["phase"],
                             ("● " if step.get("breakpoint") else "") + step["command"], step["target"], step["value"], step["expected"]),
                             tags=() if step["enabled"] else ("disabled",))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)

    def selected(self):
        selected = self.tree.selection()
        return next((i for i, s in enumerate(self.steps) if selected and s["id"] == selected[0]), None)

    def checkpoint(self):
        self.history.append(deepcopy(self.steps))
        self.history = self.history[-50:]
        self.future.clear()

    def changed(self, selected=None):
        self.refresh(selected)
        self.on_change()

    def add(self):
        dialog = StepDialog(self, new_step(target="${base_url}"))
        if dialog.result:
            self.checkpoint()
            index = self.selected()
            self.steps.insert(len(self.steps) if index is None else index + 1, dialog.result)
            self.changed(dialog.result["id"])

    def edit(self):
        index = self.selected()
        if index is None:
            return
        dialog = StepDialog(self, self.steps[index])
        if dialog.result:
            self.checkpoint()
            self.steps[index] = dialog.result
            self.changed(dialog.result["id"])

    def duplicate(self):
        index = self.selected()
        if index is not None:
            self.checkpoint()
            clone = {**deepcopy(self.steps[index]), "id": uuid4().hex}
            self.steps.insert(index + 1, clone)
            self.changed(clone["id"])

    def delete(self):
        index = self.selected()
        if index is not None:
            self.checkpoint()
            self.steps.pop(index)
            self.changed(self.steps[min(index, len(self.steps) - 1)]["id"] if self.steps else None)

    def move(self, direction):
        index = self.selected()
        if index is not None and 0 <= index + direction < len(self.steps):
            self.checkpoint()
            step = self.steps.pop(index)
            self.steps.insert(index + direction, step)
            self.changed(step["id"])

    def drop(self, event):
        target = self.tree.identify_row(event.y)
        if not self.drag_id or not target or target == self.drag_id:
            return
        before = [s["id"] for s in self.steps]
        if self.drag_id not in before or target not in before:
            return
        self.checkpoint()
        step = self.steps.pop(before.index(self.drag_id))
        self.steps.insert(before.index(target), step)
        self.changed(step["id"])
        self.drag_id = None

    def toggle(self):
        index = self.selected()
        if index is not None:
            self.checkpoint()
            self.steps[index]["enabled"] = not self.steps[index]["enabled"]
            self.changed(self.steps[index]["id"])

    def undo(self):
        if self.history:
            self.future.append(deepcopy(self.steps))
            self.steps = self.history.pop()
            self.changed()

    def redo(self):
        if self.future:
            self.history.append(deepcopy(self.steps))
            self.steps = self.future.pop()
            self.changed()


class ScriptDataEditor(ttk.Frame):
    """Case metadata and lossless advanced data, independent of Gradebook fields."""
    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.variables = {}
        for key, label in (("case_id", "Case ID"), ("title", "Name")):
            ttk.Label(self, text=label).pack(anchor="w", pady=(5, 3))
            var = tk.StringVar(self)
            self.variables[key] = var
            var.trace_add("write", lambda *_: on_change())
            ttk.Entry(self, textvariable=var).pack(fill="x")
        self.texts = {}
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, pady=(10, 0))
        self.dataset = TableEditor(tabs, on_change)
        self.case_variables = TableEditor(tabs, on_change, fixed_columns=("Variable", "Value"))
        details = ttk.Frame(tabs)
        tabs.add(self.dataset, text="Data rows")
        tabs.add(self.case_variables, text="Variables")
        tabs.add(details, text="Description")
        for key, label in (("expected_result", "Description / acceptance criteria"),):
            ttk.Label(details, text=label, style="Muted.TLabel", wraplength=650).pack(anchor="w", pady=(10, 4))
            text = dark_text(details, height=4)
            text.pack(fill="both", expand=True)
            def modified(_, widget=text):
                if widget.edit_modified():
                    widget.edit_modified(False)
                    on_change()
            text.bind("<<Modified>>", modified)
            self.texts[key] = text

    def load(self, record):
        for key, var in self.variables.items():
            var.set(record.get(key, ""))
        data = script_data(record)
        self.dataset.load_records(data["dataset"])
        self.case_variables.load_records([{"Variable": key, "Value": value} for key, value in data["variables"].items()])
        for key, text in self.texts.items():
            text.delete("1.0", "end")
            value = record.get(key, "")
            if key.endswith("_json"):
                value = json.dumps(json.loads(value), ensure_ascii=False, indent=2)
            text.insert("1.0", value)
            text.edit_modified(False)

    def draft(self, original, steps):
        record = deepcopy(original)
        record.update({key: var.get().strip() for key, var in self.variables.items()})
        record.update({key: text.get("1.0", "end-1c") for key, text in self.texts.items()})
        record["actions_json"] = json.dumps(steps, ensure_ascii=False)
        record["dataset_json"] = json.dumps(self.dataset.records(), ensure_ascii=False)
        variables = {}
        for row in self.case_variables.records():
            name = row["Variable"].strip()
            if name in variables:
                raise ValueError(f"Duplicate case variable: {name}")
            variables[name] = row["Value"]
        record["variables_json"] = json.dumps(variables, ensure_ascii=False)
        script_data(record)
        return record
