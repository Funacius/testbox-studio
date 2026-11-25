"""Browse durable case/data-row/step outcomes and export a portable report ZIP."""

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from automation.reporting import evidence_path, planned_results, text, zip_report
from studio.theme import GREEN, PANEL, RED, YELLOW, dark_text


class ReportViewer(tk.Toplevel):
    def __init__(self, parent, output, open_path):
        output = Path(output)
        document = json.loads((output / "results.json").read_text(encoding="utf-8-sig"))
        if not isinstance(document.get("results"), list) or not isinstance(document.get("metadata"), dict):
            raise ValueError("This file is not a Testbox execution report")
        super().__init__(parent)
        self.title("Execution report")
        self.configure(bg=PANEL)
        self.transient(parent)
        self.geometry("1200x800")
        self.output_dir, self.document, self.open_path = output, document, open_path
        self.current_steps = []
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        title = "Stopped / incomplete" if document["metadata"].get("stopped") else "PASS" if document.get("successful") else "FAIL / incomplete"
        ttk.Label(body, text="Execution report · " + title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text=text(document.get("counts", {})) + "  ·  " + document["metadata"].get("executed_at", ""),
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 9))
        self.filter = tk.StringVar(self, "All")
        choices = ttk.Combobox(controls, textvariable=self.filter, values=("All", "PASS", "FAIL", "ERROR", "SKIP"), state="readonly", width=12)
        choices.pack(side="left")
        choices.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Button(controls, text="Open HTML report", command=lambda: self.open_path(output / "report.html")).pack(side="right")
        ttk.Button(controls, text="Export report ZIP…", command=self.export).pack(side="right", padx=7)
        ttk.Button(controls, text="Open folder", command=lambda: self.open_path(output)).pack(side="right")
        panes = ttk.Panedwindow(body, orient="vertical")
        panes.pack(fill="both", expand=True)
        case_frame, step_frame, details = ttk.Frame(panes), ttk.Frame(panes), ttk.Frame(panes)
        panes.add(case_frame, weight=2)
        panes.add(step_frame, weight=3)
        panes.add(details, weight=2)
        self.cases = self.table(case_frame, [("case", "CASE", 150), ("browser", "BROWSER", 100), ("row", "DATA ROW", 80),
                                           ("status", "STATUS", 90), ("seconds", "SECONDS", 100), ("title", "NAME", 550)])
        self.steps = self.table(step_frame, [("index", "#", 40), ("phase", "PHASE", 80), ("command", "ACTION", 150),
                                           ("target", "TARGET", 200), ("expected", "EXPECTED", 220), ("actual", "ACTUAL", 250), ("status", "STATUS", 100)])
        self.details = dark_text(details, height=6)
        self.details.pack(fill="both", expand=True)
        self.details.configure(state="disabled")
        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="Open selected evidence", command=self.open_evidence).pack(side="left")
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right")
        self.cases.bind("<<TreeviewSelect>>", lambda _: self.show_case())
        self.steps.bind("<<TreeviewSelect>>", lambda _: self.show_step())
        self.refresh()

    def table(self, parent, definitions):
        tree = ttk.Treeview(parent, columns=[key for key, _, _ in definitions], show="headings", selectmode="browse", height=5)
        tree.grid(row=0, column=0, sticky="nsew")
        for key, label, width in definitions:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=40)
        vertical = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        for name, color in (("PASS", GREEN), ("FAIL", RED), ("ERROR", RED), ("SKIP", YELLOW), ("NOT_RUN", YELLOW)):
            tree.tag_configure(name, foreground=color)
        return tree

    def refresh(self):
        self.cases.delete(*self.cases.get_children())
        for index, record in enumerate(self.document["results"]):
            if self.filter.get() not in {"All", record["status"]}:
                continue
            self.cases.insert("", "end", iid=str(index), values=(record["case_id"], record["browser"], record.get("row_index", 0) + 1,
                              record["status"], record.get("duration_seconds", ""), record["title"]), tags=(record["status"],))
        first = self.cases.get_children()
        if first:
            self.cases.selection_set(first[0])
            self.show_case()
        else:
            self.steps.delete(*self.steps.get_children())
            self.current_steps = []
            self.detail("No cases match this filter.")

    def detail(self, value):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", value)
        self.details.configure(state="disabled")

    def selected_case(self):
        selected = self.cases.selection()
        return self.document["results"][int(selected[0])] if selected else None

    def show_case(self):
        record = self.selected_case()
        if record is None:
            return
        self.steps.delete(*self.steps.get_children())
        self.current_steps = planned_results(record)
        for index, step in enumerate(self.current_steps):
            self.steps.insert("", "end", iid=str(index), values=(step.get("index", ""), step.get("phase", ""), step.get("command", ""),
                              step.get("target", ""), text(step.get("expected", "")), text(step.get("actual", "")), step["status"]), tags=(step["status"],))
        self.detail("CASE OUTCOME\n" + record.get("actual", "") + "\n\nCLEANUP\n" + (record.get("cleanup_error") or "No cleanup error")
                    + "\n\nMEASUREMENTS\n" + text(record.get("metrics", [])))

    def show_step(self):
        selected = self.steps.selection()
        if selected and int(selected[0]) < len(self.current_steps):
            self.detail(json.dumps(self.current_steps[int(selected[0])], ensure_ascii=False, indent=2))

    def open_evidence(self):
        record = self.selected_case()
        selected = self.steps.selection()
        item = self.current_steps[int(selected[0])] if selected else record
        paths = item.get("evidence", []) if item else []
        for raw in paths:
            try:
                path = evidence_path(raw, self.output_dir)
            except (ValueError, OSError):
                continue
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                self.open_path(path)
                return
        messagebox.showinfo("No screenshot", "No screenshot was captured for the selected case/step.", parent=self)

    def export(self):
        name = filedialog.asksaveasfilename(parent=self, title="Export report ZIP", defaultextension=".zip", initialfile=self.output_dir.name + ".zip", filetypes=[("ZIP archive", "*.zip")])
        if not name:
            return
        try:
            zip_report(self.output_dir, Path(name))
            messagebox.showinfo("Report exported", name, parent=self)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot export report", str(exc), parent=self)
