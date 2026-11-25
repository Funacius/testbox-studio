"""Small themed dialogs for names, destinations and JSON settings."""

import json
import tkinter as tk
from tkinter import messagebox, ttk

from studio.theme import BG, MUTED, PANEL, TEXT, dark_text


class FormDialog(tk.Toplevel):
    def __init__(self, parent, title, fields, description=""):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=PANEL)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.variables = {}
        body = ttk.Frame(self, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, font=("Segoe UI Semibold", 15)).pack(anchor="w", pady=(0, 8))
        if description:
            ttk.Label(body, text=description, style="Muted.TLabel", wraplength=470).pack(anchor="w", pady=(0, 14))
        first = None
        for key, label, value, options in fields:
            ttk.Label(body, text=label, style="Muted.TLabel").pack(anchor="w", pady=(8, 4))
            variable = tk.StringVar(self, value)
            self.variables[key] = variable
            widget = ttk.Combobox(body, textvariable=variable, values=options, state="readonly", width=55) if options else ttk.Entry(body, textvariable=variable, width=58)
            widget.pack(fill="x")
            first = first or widget
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(22, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Confirm", style="Primary.TButton", command=self.submit).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Return>", lambda _: self.submit())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx()+180}+{parent.winfo_rooty()+160}")
        self.deiconify()
        self.grab_set()
        if first:
            first.focus_set()
        self.wait_window()

    def submit(self):
        values = {key: var.get().strip() for key, var in self.variables.items()}
        if any(not value for value in values.values()):
            messagebox.showerror("Missing value", "Complete every field.", parent=self)
            return
        self.result = values
        self.destroy()


class JsonDialog(tk.Toplevel):
    def __init__(self, parent, title, value, required=None, description=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.geometry(f"900x680+{parent.winfo_rootx()+100}+{parent.winfo_rooty()+70}")
        self.transient(parent)
        self.result = None
        self.required = required if required is not None else ("base_url", "course_id", "urls", "locators", "grade_types", "timeout")
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, font=("Segoe UI Semibold", 15)).pack(anchor="w", pady=(0, 8))
        ttk.Label(body, text=description or "Edit the Level 2 site URLs and element locators.", style="Muted.TLabel", wraplength=840).pack(anchor="w", pady=(0, 12))
        self.text = dark_text(body)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2))
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Save configuration", style="Primary.TButton", command=self.submit).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()
        self.wait_window()

    def submit(self):
        try:
            value = json.loads(self.text.get("1.0", "end-1c"))
            if not isinstance(value, dict) or not all(k in value for k in self.required):
                raise ValueError("Missing required site configuration fields")
            self.result = value
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid configuration", str(exc), parent=self)
            return
        self.destroy()
