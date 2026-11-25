"""Small spreadsheet editor preserving empty strings, whitespace and column order."""

import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, ttk

from automation.schema import VARIABLE_NAME
from studio.dialogs import FormDialog
from studio.theme import PANEL, dark_text


class CellDialog(tk.Toplevel):
    def __init__(self, parent, value, title):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=PANEL)
        self.transient(parent)
        self.geometry("650x360")
        self.result = None
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Exact text · empty strings and spaces are preserved", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.text = dark_text(frame)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", value)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Apply cell", command=self.submit, style="Primary.TButton").pack(side="right", padx=7)
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Control-Return>", lambda _: self.submit())
        self.text.focus_set()
        self.grab_set()
        self.wait_window()

    def submit(self):
        self.result = self.text.get("1.0", "end-1c")
        self.destroy()


class TableEditor(ttk.Frame):
    def __init__(self, parent, on_change, fixed_columns=None):
        super().__init__(parent)
        self.on_change = on_change
        self.fixed_columns = fixed_columns
        self.columns, self.rows = list(fixed_columns or []), []
        self.history, self.future = [], []
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))
        for label, fn in (("＋ Row", self.add_row), ("Copy row", self.copy_row), ("Delete row", self.delete_row),
                          ("↑", lambda: self.move_row(-1)), ("↓", lambda: self.move_row(1))):
            ttk.Button(toolbar, text=label, command=fn, style="Small.TButton").pack(side="left", padx=(0, 4))
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 6))
        if not fixed_columns:
            for label, fn in (("＋ Column", self.add_column), ("Rename column", self.rename_column), ("Delete column", self.delete_column)):
                ttk.Button(controls, text=label, command=fn, style="Small.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(controls, text="Undo", command=self.undo, style="Small.TButton").pack(side="left")
        ttk.Button(controls, text="Redo", command=self.redo, style="Small.TButton").pack(side="left", padx=4)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, show="headings", selectmode="browse", height=6)
        self.tree.grid(row=0, column=0, sticky="nsew")
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll.grid(row=1, column=0, sticky="ew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.column_index = None
        self.tree.bind("<Button-1>", self.remember_column)
        self.tree.bind("<Double-1>", self.edit_cell)
        ttk.Label(self, text="Double-click a cell to edit. Select a cell before renaming or deleting its column.",
                  style="Muted.TLabel", wraplength=670).pack(anchor="w", pady=6)
        self.refresh()

    def load_records(self, records):
        self.columns = list(self.fixed_columns or dict.fromkeys(key for row in records for key in row))
        self.rows = [[row.get(key, "") for key in self.columns] for row in records]
        self.history.clear()
        self.future.clear()
        self.column_index = None
        self.refresh()

    def records(self):
        return [dict(zip(self.columns, row)) for row in self.rows]

    def checkpoint(self):
        self.history.append((deepcopy(self.columns), deepcopy(self.rows)))
        self.history = self.history[-50:]
        self.future.clear()

    def refresh(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        keys = ["n", *[f"c{i}" for i in range(len(self.columns))]]
        self.tree.configure(columns=keys)
        self.tree.heading("n", text="#")
        self.tree.column("n", width=40, stretch=False)
        for index, name in enumerate(self.columns):
            key = f"c{index}"
            self.tree.heading(key, text=name)
            self.tree.column(key, width=180, stretch=True, minwidth=90)
        for index, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(index), values=[index + 1, *row])
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))

    def selected_row(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def changed(self, selected=None):
        self.refresh(selected)
        self.on_change()

    def remember_column(self, event):
        column = self.tree.identify_column(event.x)
        self.column_index = int(column[1:]) - 2 if column and column != "#1" else None

    def edit_cell(self, event):
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not row or not column or column == "#1":
            return
        index = int(column[1:]) - 2
        self.column_index = index
        dialog = CellDialog(self, self.rows[int(row)][index], f"Row {int(row) + 1} · {self.columns[index]}")
        if dialog.result is not None:
            self.set_cell(int(row), index, dialog.result)

    def set_cell(self, row, column, value):
        if not isinstance(value, str):
            raise ValueError("Cell values must be text")
        self.checkpoint()
        self.rows[row][column] = value
        self.changed(row)

    def add_row(self):
        self.checkpoint()
        self.rows.append([""] * len(self.columns))
        self.changed(len(self.rows) - 1)

    def copy_row(self):
        row = self.selected_row()
        if row is not None:
            self.checkpoint()
            self.rows.insert(row + 1, list(self.rows[row]))
            self.changed(row + 1)

    def delete_row(self):
        row = self.selected_row()
        if row is not None:
            self.checkpoint()
            self.rows.pop(row)
            self.changed(min(row, len(self.rows) - 1))

    def move_row(self, direction):
        row = self.selected_row()
        if row is not None and 0 <= row + direction < len(self.rows):
            self.checkpoint()
            self.rows.insert(row + direction, self.rows.pop(row))
            self.changed(row + direction)

    def column_name(self, old=""):
        dialog = FormDialog(self, "Variable column", [("name", "Column name, used as ${name}", old or "value", None)])
        if not dialog.result:
            return None
        name = dialog.result["name"]
        if not VARIABLE_NAME.fullmatch(name) or name in self.columns and name != old:
            messagebox.showerror("Invalid column", "Use a unique variable name: letters, digits, _, . or -; start with a letter or _.", parent=self)
            return None
        return name

    def add_column(self):
        name = self.column_name()
        if name:
            self.checkpoint()
            self.columns.append(name)
            for row in self.rows:
                row.append("")
            self.changed()

    def rename_column(self):
        index = self.column_index
        if index is None or not 0 <= index < len(self.columns):
            return
        name = self.column_name(self.columns[index])
        if name:
            self.checkpoint()
            self.columns[index] = name
            self.changed()

    def delete_column(self):
        index = self.column_index
        if index is None or not 0 <= index < len(self.columns):
            return
        if not messagebox.askyesno("Delete column", f"Delete {self.columns[index]} and its data?", parent=self):
            return
        self.checkpoint()
        self.columns.pop(index)
        for row in self.rows:
            row.pop(index)
        self.column_index = None
        self.changed()

    def undo(self):
        if self.history:
            self.future.append((deepcopy(self.columns), deepcopy(self.rows)))
            self.columns, self.rows = self.history.pop()
            self.changed()

    def redo(self):
        if self.future:
            self.history.append((deepcopy(self.columns), deepcopy(self.rows)))
            self.columns, self.rows = self.future.pop()
            self.changed()
