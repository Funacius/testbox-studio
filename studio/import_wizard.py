"""Sheet/header selection and explicit, reusable spreadsheet column mapping."""

import json
import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, ttk

from studio.importing import FIELDS, guess_header, headings, import_selection, read_grids, suggest_mapping
from studio.theme import PANEL, dark_text
from studio.background import BackgroundTask, CSV_ENCODINGS


def load_grids(parent, path, encoding="auto"):
    if path.suffix.lower() == ".csv" and path.stat().st_size <= 128 * 1024:
        try:
            return read_grids(path, encoding)
        except UnicodeError:
            pass
    job = BackgroundTask(parent, "Read spreadsheet", lambda cancelled, choice: read_grids(path, choice, cancelled),
                         encoding=encoding if path.suffix.lower() == ".csv" else None)
    if job.error:
        raise ValueError(str(job.error)) from job.error
    return job.result


class ImportWizard(tk.Toplevel):
    def __init__(self, parent, path, profiles=None, selected_case=None, grids=None):
        super().__init__(parent)
        self.withdraw()
        self.result = None
        try:
            grids = grids if grids is not None else load_grids(parent, path)
            if grids is None:
                self.destroy()
                return
            if not grids:
                raise ValueError("This file contains no sheets")
        except Exception as exc:
            self.destroy()
            raise ValueError(f"Cannot read spreadsheet: {exc}") from exc
        self.title("Import · sheets, columns and preview")
        self.configure(bg=PANEL)
        self.geometry(f"1100x{min(800, self.winfo_screenheight() - 120)}")
        self.transient(parent)
        self.path, self.grids, self.profiles = path, grids, profiles or {}
        self.result = None
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=path.name, style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Choose the sheet and header, map columns, then preview before importing. Manual prose becomes disabled reference steps.",
                  style="Muted.TLabel", wraplength=1030).pack(anchor="w", pady=(4, 10))
        top = ttk.Frame(body)
        top.pack(fill="x")
        self.sheet_name = tk.StringVar(self, grids[0]["name"])
        self.header = tk.StringVar(self, "1")
        self.mode = tk.StringVar(self, "Steps table")
        self.profile = tk.StringVar(self, "")
        for label, variable, choices, width in (("Sheet", self.sheet_name, [g["name"] for g in grids], 28),
                                                ("Mode", self.mode, ("Steps table", "Dataset", "Testbox export", "Project 2 Gradebook"), 22)):
            ttk.Label(top, text=label).pack(side="left", padx=(0, 5))
            box = ttk.Combobox(top, textvariable=variable, values=choices, state="readonly", width=width)
            box.pack(side="left", padx=(0, 15))
            box.bind("<<ComboboxSelected>>", self.sheet_changed if variable is self.sheet_name else lambda _: self.refresh_mapping(False))
        ttk.Label(top, text="Header row").pack(side="left")
        header = ttk.Spinbox(top, from_=1, to=10000, textvariable=self.header, width=6, command=lambda: self.refresh_mapping())
        header.pack(side="left", padx=6)
        header.bind("<Return>", lambda _: self.refresh_mapping())
        ttk.Button(top, text="Read header", command=self.refresh_mapping, style="Small.TButton").pack(side="left")
        options = ttk.Frame(body)
        options.pack(fill="x", pady=9)
        self.continue_ids = tk.BooleanVar(self, True)
        self.use_selected = tk.BooleanVar(self, bool(selected_case))
        ttk.Checkbutton(options, text="Blank Case IDs continue the previous case", variable=self.continue_ids).pack(side="left")
        ttk.Checkbutton(options, text=f"Dataset → selected case ({selected_case or 'none'})", variable=self.use_selected,
                        state="normal" if selected_case else "disabled").pack(side="left", padx=14)
        if path.suffix.lower() == ".csv":
            encoding_row = ttk.Frame(body)
            encoding_row.pack(fill="x", pady=(0, 7))
            self.csv_encoding = tk.StringVar(self, grids[0].get("csv_encoding", "auto"))
            ttk.Label(encoding_row, text="CSV encoding").pack(side="left")
            ttk.Combobox(encoding_row, textvariable=self.csv_encoding, values=CSV_ENCODINGS, width=18, state="readonly").pack(side="left", padx=8)
            ttk.Button(encoding_row, text="Reload CSV", command=self.reload_csv, style="Small.TButton").pack(side="left")
        profiles = ttk.Frame(body)
        profiles.pack(fill="x", pady=(0, 10))
        ttk.Label(profiles, text="Mapping profile").pack(side="left", padx=(0, 8))
        ttk.Combobox(profiles, textvariable=self.profile, values=list(self.profiles), width=28).pack(side="left")
        ttk.Button(profiles, text="Load profile", command=self.load_profile, style="Small.TButton").pack(side="left", padx=7)
        ttk.Label(profiles, text="Enter a name to save this mapping with the project.", style="Muted.TLabel").pack(side="left")
        middle = ttk.Panedwindow(body, orient="horizontal")
        middle.pack(fill="both", expand=True)
        mapping_frame = ttk.Frame(middle, padding=(0, 0, 12, 0))
        middle.add(mapping_frame, weight=0)
        self.mapping = {}
        self.boxes = []
        for row, field in enumerate(FIELDS):
            ttk.Label(mapping_frame, text=field.replace("_", " ").title()).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            variable = tk.StringVar(self)
            box = ttk.Combobox(mapping_frame, textvariable=variable, state="readonly", width=25)
            box.grid(row=row, column=1, sticky="ew", pady=4)
            self.mapping[field] = variable
            self.boxes.append(box)
        right = ttk.Frame(middle)
        middle.add(right, weight=1)
        preview_frame = ttk.Frame(right)
        preview_frame.pack(fill="both", expand=True)
        self.grid = ttk.Treeview(preview_frame, show="headings", height=6)
        self.grid.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(preview_frame, orient="vertical", command=self.grid.yview)
        horizontal = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.grid.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.grid.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview = dark_text(right, height=9)
        self.preview.pack(fill="both", expand=True, pady=(8, 0))
        self.preview.configure(state="disabled")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Import", command=self.submit, style="Primary.TButton").pack(side="right", padx=8)
        ttk.Button(buttons, text="Preview mapped data", command=self.show_preview).pack(side="right")
        self.sheet_changed()
        self.bind("<Escape>", lambda _: self.destroy())
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def sheet(self):
        return next(g for g in self.grids if g["name"] == self.sheet_name.get())

    def reload_csv(self):
        try:
            grids = load_grids(self, self.path, self.csv_encoding.get())
            if grids is not None:
                self.grids = grids
                self.csv_encoding.set(grids[0].get("csv_encoding", "auto"))
                self.sheet_changed()
        except (OSError, ValueError, UnicodeError) as exc:
            self.text(str(exc))

    def sheet_changed(self, _=None):
        try:
            header = guess_header(self.sheet()["rows"])
            self.header.set(str(header + 1))
            labels = headings(self.sheet()["rows"], header)
            if {"inputs_json", "expected_json", "workflow"} <= set(labels):
                self.mode.set("Testbox export")
            elif self.sheet_name.get() == "003 - Moodle Grading":
                self.mode.set("Project 2 Gradebook")
            else:
                self.mode.set("Steps table" if suggest_mapping(labels).get("command") else "Dataset")
            self.refresh_mapping()
        except ValueError as exc:
            self.text(str(exc))

    def refresh_mapping(self, guess=True):
        try:
            header = int(self.header.get()) - 1
            labels = headings(self.sheet()["rows"], header)
            guesses = suggest_mapping(labels)
            for key, box in zip(FIELDS, self.boxes):
                box.configure(values=["", *[s for s in labels if s]], state="readonly" if self.mode.get() == "Steps table" else "disabled")
                if guess or self.mapping[key].get() not in labels:
                    self.mapping[key].set(guesses[key])
            self.grid.delete(*self.grid.get_children())
            columns = [f"c{n}" for n in range(len(labels))]
            self.grid.configure(columns=columns)
            for key, label in zip(columns, labels):
                self.grid.heading(key, text=label)
                self.grid.column(key, width=130, stretch=False)
            for row in self.sheet()["rows"][header + 1:header + 11]:
                self.grid.insert("", "end", values=row)
            self.text("Preview the mapped result before confirming. Dataset headers are normalized to usable variable names; the preview lists the mapping.")
        except (ValueError, TypeError) as exc:
            self.text(str(exc))

    def load_profile(self):
        profile = self.profiles.get(self.profile.get())
        if not profile:
            return
        self.header.set(str(profile["header"] + 1))
        self.mode.set(profile["mode"])
        self.refresh_mapping(False)
        for key, value in profile.get("mapping", {}).items():
            if key in self.mapping:
                self.mapping[key].set(value)
        self.continue_ids.set(profile.get("continue_ids", True))

    def build(self):
        return import_selection(self.path, self.sheet(), int(self.header.get()) - 1, self.mode.get(),
                                {key: v.get() for key, v in self.mapping.items()}, self.continue_ids.get())

    def build_responsive(self):
        if len(self.sheet()["rows"]) <= 2000 and self.path.stat().st_size <= 128 * 1024 and self.mode.get() != "Project 2 Gradebook":
            return self.build()
        sheet, header, mode = self.sheet(), int(self.header.get()) - 1, self.mode.get()
        mapping, continuation = {key: v.get() for key, v in self.mapping.items()}, self.continue_ids.get()
        job = BackgroundTask(self, "Validate mapped data", lambda cancelled, _: import_selection(self.path, sheet, header, mode, mapping, continuation))
        if job.error:
            raise ValueError(str(job.error)) from job.error
        return job.result

    def text(self, value):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", value)
        self.preview.configure(state="disabled")

    def show_preview(self):
        try:
            result = self.build_responsive()
            if result is None:
                return
            if result["kind"] == "dataset":
                summary = f"{len(result['dataset'])} data rows. Column mapping:\n" + json.dumps(result["columns"], ensure_ascii=False, indent=2)
                summary += "\n\nFirst rows:\n" + json.dumps(result["dataset"][:3], ensure_ascii=False, indent=2)
            else:
                summary = f"{len(result['records'])} cases; {result['drafts']} manual steps imported as disabled notes.\n"
                summary += json.dumps(result["records"][:2], ensure_ascii=False, indent=2)
            if len(summary) > 12000:
                summary = summary[:12000] + "\n\n[Preview shortened. Full values are retained for import.]"
            self.text(summary)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.text(str(exc))

    def submit(self):
        try:
            result = self.build_responsive()
            if result is None:
                return
            result["use_selected"] = self.use_selected.get()
            if self.profile.get().strip():
                result["profile"] = (self.profile.get().strip(), dict(header=int(self.header.get()) - 1, mode=self.mode.get(),
                    mapping={key: v.get() for key, v in self.mapping.items()}, continue_ids=self.continue_ids.get()))
            self.result = result
        except (ValueError, KeyError, TypeError, OSError) as exc:
            messagebox.showerror("Cannot import", str(exc), parent=self)
            return
        self.destroy()
