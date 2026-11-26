"""Configure a browser/level matrix and per-case elapsed measurement boundaries."""

import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, ttk

from automation.nfr import checked_nfr
from automation.schema import is_script, script_data
from studio.theme import PANEL


def gui_nfr_config(config):
    config = deepcopy(config)
    if isinstance(config, dict) and isinstance(config.get("browsers"), list) and "opera" in config["browsers"]:
        config["browsers"] = ["chrome", "edge"]
    return config


class NfrDialog(tk.Toplevel):
    def __init__(self, parent, records, config, selected_case=None):
        super().__init__(parent)
        self.withdraw()
        self.title("Non-functional requirements")
        self.configure(bg=PANEL)
        self.transient(parent)
        self.geometry("900x700")
        self.result = None
        self.records = {r["case_id"]: r for r in records if is_script(r)}
        self.config = gui_nfr_config(config)
        self.current_case = None
        self.step_ids = {}
        body = ttk.Frame(self, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Non-functional requirements", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Run the selected cases through exported Level 1 Python and/or Level 2 JSON definitions.", style="Muted.TLabel").pack(anchor="w", pady=(8, 14))
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Label(row, text="Levels").pack(side="left")
        levels = self.config.get("levels", [1, 2])
        self.levels = tk.StringVar(self, "Both levels" if len(levels) == 2 else f"Level {levels[0]}")
        ttk.Combobox(row, textvariable=self.levels, values=("Both levels", "Level 1", "Level 2"), state="readonly", width=16).pack(side="left", padx=(10, 35))
        ttk.Label(row, text="Repetitions per dataset row").pack(side="left")
        self.repetitions = tk.StringVar(self, str(self.config.get("repetitions", 1)))
        ttk.Spinbox(row, from_=1, to=30, textvariable=self.repetitions, width=5).pack(side="left", padx=10)
        browsers = ttk.Frame(body)
        browsers.pack(fill="x", pady=16)
        ttk.Label(browsers, text="Browsers").pack(side="left", padx=(0, 12))
        self.browsers = {}
        for key, label in (("chrome", "Chrome"), ("edge", "Edge")):
            variable = tk.BooleanVar(self, key in self.config.get("browsers", ["chrome", "edge"]))
            self.browsers[key] = variable
            ttk.Checkbutton(browsers, text=label, variable=variable).pack(side="left", padx=8)
        ttk.Label(body, text="Compatibility needs two browsers. Elapsed mode uses the checked browsers and the limits below.\nFor measurements, use zero step delay; playback pauses and breakpoints are disabled.",
            style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(0, 16))
        ttk.Separator(body).pack(fill="x")
        ttk.Label(body, text="Elapsed-time requirement for an editable case", style="Section.TLabel").pack(anchor="w", pady=(18, 10))
        self.case = tk.StringVar(self)
        self.case_box = ttk.Combobox(body, textvariable=self.case, values=list(self.records), state="readonly")
        self.case_box.pack(fill="x")
        self.case_box.bind("<<ComboboxSelected>>", lambda _: self.load_case())
        self.start, self.end, self.maximum = tk.StringVar(self), tk.StringVar(self), tk.StringVar(self)
        for label, variable, key in (("Start immediately before action", self.start, "start_box"), ("End after readiness/assertion action", self.end, "end_box")):
            ttk.Label(body, text=label, style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
            widget = ttk.Combobox(body, textvariable=variable, state="readonly")
            widget.pack(fill="x")
            setattr(self, key, widget)
        limit = ttk.Frame(body)
        limit.pack(fill="x", pady=14)
        ttk.Label(limit, text="Maximum seconds (every sample must meet this)").pack(side="left")
        ttk.Entry(limit, textvariable=self.maximum, width=14).pack(side="left", padx=12)
        ttk.Label(body, text="The interval includes the start action and finishes only after the end action succeeds.\nUse an assertion/wait for the saved or ready state, rather than the whole case duration.\nNative Gradebook elapsed measurements require an editable steps case; compatibility also supports native cases.",
            style="Muted.TLabel", wraplength=820).pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply NFR settings", style="Primary.TButton", command=self.submit).pack(side="right", padx=10)
        if self.records:
            self.case.set(selected_case if selected_case in self.records else next(iter(self.records)))
            self.load_case()
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def store_current(self):
        if not self.current_case:
            return
        rules = self.config.setdefault("measurements", {})
        if not self.start.get() and not self.end.get() and not self.maximum.get():
            rules.pop(self.current_case, None)
            return
        rules[self.current_case] = dict(start=self.step_ids.get(self.start.get(), ""),
            end=self.step_ids.get(self.end.get(), ""), maximum_seconds=self.maximum.get())

    def load_case(self):
        self.store_current()
        self.current_case = self.case.get()
        record = self.records[self.current_case]
        steps = script_data(record)["steps"]
        from automation.flow import top_level_actions
        try:
            eligible = top_level_actions(steps, "test")
        except ValueError:
            eligible = set()
        self.step_ids = {f"{i}. {s['command']}  {s['target']}": s["id"] for i, s in enumerate(steps, 1)
                         if s["id"] in eligible}
        self.start_box.configure(values=list(self.step_ids))
        self.end_box.configure(values=list(self.step_ids))
        rule = self.config.get("measurements", {}).get(self.current_case, {})
        self.start.set(next((label for label, uid in self.step_ids.items() if uid == rule.get("start")), ""))
        self.end.set(next((label for label, uid in self.step_ids.items() if uid == rule.get("end")), ""))
        self.maximum.set(str(rule.get("maximum_seconds", "")))

    def submit(self):
        try:
            self.store_current()
            self.config.update(levels=[1, 2] if self.levels.get() == "Both levels" else [int(self.levels.get()[-1])],
                browsers=[key for key, value in self.browsers.items() if value.get()], repetitions=int(self.repetitions.get()))
            checked_nfr(self.config, [], "elapsed")
            for case_id in self.config.get("measurements", {}):
                if case_id in self.records:
                    checked_nfr(self.config, [self.records[case_id]], "elapsed")
            self.result = deepcopy(self.config)
            self.destroy()
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Invalid NFR settings", str(exc), parent=self)
