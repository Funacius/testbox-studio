"""Dark desktop manager. Browser execution is always an explicit Run action."""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from gradebook.config import ROOT
from automation.schema import is_script, script_data, validate_records as parse_rows
from studio import APP_NAME
from studio.dialogs import FormDialog, JsonDialog
from studio.exchange import read_table, write_table
from studio.model import WORKFLOWS, Workspace, folder, planned_steps, template_record, testcase
from studio.steps_editor import ScriptDataEditor, StepsEditor
from studio.import_wizard import ImportWizard
from automation.readiness import checked_settings, website_status
from automation.playback import write_control
from studio.locator_library import LocatorLibraryDialog
from studio.report_viewer import ReportViewer
from studio.nfr_dialog import NfrDialog
from studio.templates import TemplateDialog, instantiate
from studio.recorder_dialog import RecorderDialog
from studio.theme import (ACCENT, BG, BORDER, FIELD, GREEN, MUTED, PANEL, RED,
                          SURFACE, TEXT, YELLOW, apply_theme, dark_menu, dark_text)

FILE_TYPES = [("Test data", "*.csv *.xls *.xlsx"), ("CSV", "*.csv"),
              ("Excel workbook", "*.xlsx"), ("Excel 97–2003", "*.xls")]
DEFAULT_WORKSPACE = ROOT / "workspace/testbox.project.json"
LEGACY_WORKSPACE = ROOT / "workspace/gradebook.project.json"
BANGKOK = timezone(timedelta(hours=7))


class Studio(tk.Tk):
    def __init__(self, workspace_path: Path | None = None):
        super().__init__()
        self.withdraw()
        apply_theme(self)
        self.title(APP_NAME)
        width, height = min(1600, self.winfo_screenwidth() - 80), min(960, self.winfo_screenheight() - 150)
        self.geometry(f"{width}x{height}+35+30")
        self.minsize(1180, 730)
        self.workspace_path = workspace_path or (LEGACY_WORKSPACE if not DEFAULT_WORKSPACE.exists() and LEGACY_WORKSPACE.exists() else DEFAULT_WORKSPACE)
        self.workspace = Workspace.load(self.workspace_path) if self.workspace_path.exists() else Workspace("Untitled workspace")
        self.dirty = False
        self.editor_dirty = False
        self.editor_uid = None
        self.loading = False
        self.history = []
        self.future = []
        self.statuses = {}
        self.events = queue.Queue()
        self.process = None
        self.stop_file = None
        self.playback_path = None
        self.playback_sequence = 0
        self.run_generic = False
        self.run_nfr = False
        self.last_output = None
        self.close_when_stopped = False
        self.run_count = 0
        self.run_total = 0
        self.drag_start = None
        self.vars = {}
        self.run_rows = {}
        self.execution_states = {}
        self._build_menu()
        self._build_ui()
        self._select_environment()
        self._bind_keys()
        self._rebuild_tree()
        first = next((n["uid"] for n, _ in self.workspace.walk() if n["kind"] == "case"), None)
        if first:
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._show_node(first)
        else:
            self._empty_editor()
        if not self.workspace_path.exists():
            self.saved_label.configure(text="UNTITLED · NOT SAVED", fg=MUTED)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll_events)
        self.after(60, self.deiconify)
        self.after(100, self._dark_titlebar)

    def _dark_titlebar(self):
        if sys.platform == "win32":
            try:
                import ctypes
                handle = ctypes.windll.user32.GetParent(self.winfo_id())
                enabled = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 20, ctypes.byref(enabled), 4)
            except (AttributeError, OSError):
                pass

    def _build_menu(self):
        menu = dark_menu(self)
        self.configure(menu=menu)
        file_menu = dark_menu(menu)
        for text, command, accelerator in [
            ("New workspace", self._new_workspace, ""), ("Open workspace…", self._open_workspace, "Ctrl+O"),
            ("Save workspace", self._save, "Ctrl+S"), ("Save workspace as…", lambda: self._save(True), "Ctrl+Shift+S"),
            ("Import data…", self._import, "Ctrl+I"), ("Export data…", self._export, "Ctrl+E")]:
            file_menu.add_command(label=text, command=command, accelerator=accelerator)
        file_menu.add_separator()
        file_menu.add_command(label="Export Python / unittest…", command=self._export_python)
        file_menu.add_command(label="Open execution report…", command=self._open_report)
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)
        edit = dark_menu(menu)
        for text, command, accelerator in [
            ("Undo workspace change", self._undo, "Ctrl+Z"), ("Redo workspace change", self._redo, "Ctrl+Y"),
            ("New test case…", self._new_case, "Ctrl+N"), ("New folder…", self._new_folder, "Ctrl+Shift+N"),
            ("Rename…", self._rename, "F2"), ("Duplicate", self._duplicate, "Ctrl+D"),
            ("Move to folder…", self._move_dialog, ""), ("Move up", lambda: self._reorder(-1), "Alt+Up"),
            ("Move down", lambda: self._reorder(1), "Alt+Down"), ("Delete…", self._delete, "Delete")]:
            edit.add_command(label=text, command=command, accelerator=accelerator)
        menu.add_cascade(label="Edit", menu=edit)
        tools_menu = dark_menu(menu)
        tools_menu.add_command(label="Case templates…", command=self._templates)
        tools_menu.add_command(label="Browser recorder / picker…", command=self._recorder)
        tools_menu.add_command(label="Locator library…", command=self._locator_library)
        tools_menu.add_command(label="NFR settings…", command=self._nfr_settings)
        tools_menu.add_separator()
        tools_menu.add_command(label="Load Gradebook sample", command=self._load_gradebook_sample)
        menu.add_cascade(label="Tools", menu=tools_menu)
        help_menu = dark_menu(menu)
        help_menu.add_command(label="Open user guide", command=lambda: self._open_path(ROOT / "README.md"))
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo(
            APP_NAME, f"{APP_NAME}\nEditable browser steps and data-driven automation.\n\nCSV / XLS / XLSX workspace manager.\nPython + Selenium + unittest.\n\nGradebook templates remain available.\nOnly Run starts browser tests.", parent=self))
        menu.add_cascade(label="Help", menu=help_menu)

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, padx=22, pady=15)
        header.pack(fill="x")
        badge = tk.Label(header, text="T", bg=ACCENT, fg=BG, font=("Segoe UI Semibold", 22), width=2)
        badge.pack(side="left", padx=(0, 13))
        branding = tk.Frame(header, bg=BG)
        branding.pack(side="left")
        tk.Label(branding, text=APP_NAME, font=("Segoe UI Semibold", 19), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(branding, text="BROWSER AUTOMATION  /  EDITABLE STEPS  /  DATA-DRIVEN TESTING",
                 font=("Segoe UI", 8), bg=BG, fg=MUTED).pack(anchor="w", pady=(2, 0))
        self.count_label = tk.Label(header, text="", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 10))
        self.count_label.pack(side="right")
        toolbar = ttk.Frame(self, padding=(18, 10))
        toolbar.pack(fill="x", padx=10)
        ttk.Button(toolbar, text="＋ Test case", command=self._new_case).pack(side="left")
        ttk.Button(toolbar, text="＋ Folder", command=self._new_folder).pack(side="left", padx=7)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Import…", command=self._import).pack(side="left")
        ttk.Button(toolbar, text="Export…", command=self._export).pack(side="left", padx=7)
        ttk.Button(toolbar, text="Save workspace", command=self._save).pack(side="left")
        self.stop_button = ttk.Button(toolbar, text="■ Stop after case", style="Danger.TButton", command=self._stop, state="disabled")
        self.stop_button.pack(side="right", padx=(7, 0))
        self.run_button = ttk.Button(toolbar, text="▶  Run", style="Primary.TButton", command=self._run)
        self.run_button.pack(side="right")
        self.scope = tk.StringVar(self, "Selected items")
        ttk.Combobox(toolbar, textvariable=self.scope, values=["Selected items", "All cases"], state="readonly", width=15).pack(side="right", padx=10)

        self.vertical = ttk.Panedwindow(self, orient="vertical")
        self.vertical.pack(fill="both", expand=True, padx=10, pady=(9, 0))
        horizontal = ttk.Panedwindow(self.vertical, orient="horizontal")
        self.vertical.add(horizontal, weight=5)
        self.sidebar = ttk.Frame(horizontal, padding=(12, 14))
        horizontal.add(self.sidebar, weight=0)
        self.center = ttk.Frame(horizontal, padding=(18, 14))
        horizontal.add(self.center, weight=5)
        inspector_shell = ttk.Frame(horizontal)
        horizontal.add(inspector_shell, weight=0)
        self.inspector = self._scroll_panel(inspector_shell, padding=(16, 14), width=240)
        self._build_explorer()
        self._build_editor()
        self._build_inspector()
        self._build_console()
        footer = tk.Frame(self, bg=BG, padx=16, pady=7)
        footer.pack(side="bottom", fill="x", before=self.vertical)
        self.status = tk.StringVar(self, f"Ready · {len(self.workspace.rows())} cases · No browser tests started in this session")
        tk.Label(footer, textvariable=self.status, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)
        self.saved_label = tk.Label(footer, text="WORKSPACE SAVED" if self.workspace_path.exists() else "NEW WORKSPACE", bg=BG, fg=GREEN, font=("Segoe UI Semibold", 8))
        self.saved_label.pack(side="right")
        self.after(220, lambda: self._set_sashes(horizontal))

    def _set_sashes(self, horizontal):
        try:
            self.vertical.sashpos(0, max(400, self.vertical.winfo_height() - 215))
            self.update_idletasks()
            total = horizontal.winfo_width()
            horizontal.sashpos(1, total - 260)
            horizontal.sashpos(0, 325)
        except tk.TclError:
            pass

    def _scroll_panel(self, parent, padding=0, width=500):
        canvas = tk.Canvas(parent, bg=PANEL, highlightthickness=0, width=width)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(canvas, padding=padding)
        window = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        def wheel(event):
            widget = event.widget
            if isinstance(widget, tk.Text):
                return
            while widget is not None:
                if widget is body or widget is canvas:
                    canvas.yview_scroll(-int(event.delta / 120), "units")
                    return "break"
                widget = getattr(widget, "master", None)
        self.bind_all("<MouseWheel>", wheel, add=True)
        return body

    def _build_explorer(self):
        ttk.Label(self.sidebar, text="EXPLORER", style="Section.TLabel").pack(anchor="w")
        self.search = tk.StringVar(self)
        search = ttk.Entry(self.sidebar, textvariable=self.search, width=35)
        search.pack(fill="x", pady=(11, 6))
        self.search.trace_add("write", lambda *_: self._rebuild_tree())
        ttk.Label(self.sidebar, text="Search case ID, name or folder", style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 10))
        tree_frame = ttk.Frame(self.sidebar)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("status",), selectmode="extended", show="tree", height=8)
        self.tree.column("#0", width=290, minwidth=140)
        self.tree.column("status", width=55, minwidth=50, stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        for tag, color in [("folder", MUTED), ("PASS", GREEN), ("FAIL", RED), ("ERROR", RED), ("SKIP", YELLOW), ("NOT_RUN", YELLOW), ("RUNNING", ACCENT)]:
            self.tree.tag_configure(tag, foreground=color)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<ButtonPress-1>", self._drag_press, add=True)
        self.tree.bind("<B1-Motion>", self._drag_motion, add=True)
        self.tree.bind("<ButtonRelease-1>", self._drag_release, add=True)
        controls = ttk.Frame(self.sidebar)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="↑", style="Small.TButton", width=3, command=lambda: self._reorder(-1)).pack(side="left")
        ttk.Button(controls, text="↓", style="Small.TButton", width=3, command=lambda: self._reorder(1)).pack(side="left", padx=5)
        ttk.Button(controls, text="Move…", style="Small.TButton", command=self._move_dialog).pack(side="left")
        ttk.Label(self.sidebar, text="Drag into a folder or between test cases.\nCtrl / Shift selects multiple items.", style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w", pady=(9, 0))

    def _build_editor(self):
        self.breadcrumb = ttk.Label(self.center, text="WORKSPACE", style="Section.TLabel")
        self.breadcrumb.pack(anchor="w")
        self.selection_title = ttk.Label(self.center, text="Select a test case", style="Title.TLabel", wraplength=650)
        self.selection_title.pack(anchor="w", pady=(8, 12))
        self.notebook = ttk.Notebook(self.center)
        self.notebook.pack(fill="both", expand=True)
        self.overview_tab = ttk.Frame(self.notebook, padding=(0, 10))
        self.overview = self._scroll_panel(self.overview_tab, width=650)
        self.steps_tab = ttk.Frame(self.notebook, padding=(0, 10))
        self.json_tab = ttk.Frame(self.notebook, padding=(0, 10))
        self.source_tab = ttk.Frame(self.notebook, padding=(0, 10))
        for frame, title in [(self.overview_tab, "Test data"), (self.steps_tab, "Steps"), (self.json_tab, "JSON / Expected"), (self.source_tab, "Source")]:
            self.notebook.add(frame, text=title)
        self.notebook.bind("<<NotebookTabChanged>>", lambda _: self._refresh_steps())
        self.overview.columnconfigure(0, weight=1)
        self.overview.columnconfigure(1, weight=1)
        fields = [("case_id", "Case ID", 0, 0, None), ("workflow", "Workflow", 0, 1, WORKFLOWS[1:]),
                  ("title", "Test case name", 2, 0, None), ("item_name", "Item name (spaces are preserved)", 4, 0, None),
                  ("minimum", "Minimum grade", 6, 0, None), ("maximum", "Maximum grade", 6, 1, None),
                  ("grade_type", "Grade type", 8, 0, ("Value", "Scale", "Text")), ("scale", "Scale name (Scale type only)", 8, 1, None)]
        for key, label, row, col, choices in fields:
            span = 2 if key in {"title", "item_name"} else 1
            ttk.Label(self.overview, text=label, style="Muted.TLabel", font=("Segoe UI", 9)).grid(row=row, column=col, columnspan=span, sticky="w", padx=(0 if col == 0 else 9, 0), pady=(4, 3))
            variable = tk.StringVar(self)
            self.vars[key] = variable
            entry = ttk.Combobox(self.overview, textvariable=variable, values=choices, state="readonly") if choices else ttk.Entry(self.overview, textvariable=variable)
            entry.grid(row=row + 1, column=col, columnspan=span, sticky="ew", padx=(0 if col == 0 else 9, 0), pady=(0, 5))
            variable.trace_add("write", self._editor_changed)
        ttk.Label(self.overview, text="Expected result · original description / your acceptance criteria", style="Muted.TLabel", font=("Segoe UI", 9)).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 5))
        self.expected_text = dark_text(self.overview, height=5)
        self.expected_text.grid(row=11, column=0, columnspan=2, sticky="nsew")
        self.overview.rowconfigure(11, weight=1)
        self.expected_text.bind("<<Modified>>", self._text_changed)
        bottom = ttk.Frame(self.center)
        bottom.pack(side="bottom", fill="x", pady=(12, 0), before=self.notebook)
        self.apply_button = ttk.Button(bottom, text="Apply changes", style="Primary.TButton", command=self._apply)
        self.apply_button.pack(side="right")
        ttk.Button(bottom, text="Case templates…", command=self._templates).pack(side="left")
        self.editor_hint = ttk.Label(bottom, text="Expected assertions are edited separately.", style="Muted.TLabel", font=("Segoe UI", 8))
        self.editor_hint.pack(side="left", padx=10)

        ttk.Label(self.steps_tab, text="Preview generated from the current workflow and data", style="Muted.TLabel").pack(anchor="w", pady=(0, 9))
        frame = ttk.Frame(self.steps_tab)
        frame.pack(fill="both", expand=True)
        self.steps_tree = ttk.Treeview(frame, columns=("number", "action", "expected"), show="headings", selectmode="browse", height=8)
        for key, label, width in [("number", "#", 38), ("action", "ACTION", 350), ("expected", "EXPECTED RESULT", 320)]:
            self.steps_tree.heading(key, text=label)
            self.steps_tree.column(key, width=width, stretch=key != "number")
        self.steps_tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.steps_tree.yview)
        scroll.pack(side="right", fill="y")
        self.steps_tree.configure(yscrollcommand=scroll.set)
        self.steps_tree.bind("<Double-1>", self._step_detail)
        ttk.Label(self.steps_tab, text="Double-click a row for full details. Live actions appear below when Run is pressed.", style="Muted.TLabel", wraplength=660, font=("Segoe UI", 8)).pack(anchor="w", pady=(9, 0))
        panes = ttk.Panedwindow(self.json_tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        texts = []
        for title in ("INPUT OPTIONS · inputs_json", "ASSERTIONS · expected_json"):
            frame = ttk.Frame(panes, padding=(0, 0, 8, 0))
            panes.add(frame, weight=1)
            ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
            text = dark_text(frame)
            text.pack(fill="both", expand=True)
            text.bind("<<Modified>>", self._text_changed)
            texts.append(text)
        self.inputs_text, self.assertions_text = texts
        ttk.Button(self.json_tab, text="Format JSON", style="Small.TButton", command=self._format_json).pack(anchor="e", pady=(9, 0))
        ttk.Label(self.json_tab, text="Common input fields use the Test data tab. Changing inputs does not rewrite expected assertions.", style="Muted.TLabel", wraplength=660, font=("Segoe UI", 8)).pack(anchor="w", pady=(7, 0))
        self.source_text = dark_text(self.source_tab)
        self.source_text.pack(fill="both", expand=True)
        self.source_text.configure(state="disabled")
        self.script_data_tab = ttk.Frame(self.notebook, padding=(0, 10))
        self.script_steps_tab = ttk.Frame(self.notebook, padding=(0, 10))
        self.script_data_body = self._scroll_panel(self.script_data_tab, width=650)
        self.script_editor = ScriptDataEditor(self.script_data_body, self._editor_changed)
        self.script_editor.pack(fill="both", expand=True)
        self.steps_editor = StepsEditor(self.script_steps_tab, self._editor_changed)
        self.steps_editor.pack(fill="both", expand=True)
        self.notebook.add(self.script_data_tab, text="Test data")
        self.notebook.add(self.script_steps_tab, text="Steps")
        self.notebook.hide(self.script_data_tab)
        self.notebook.hide(self.script_steps_tab)

    def _case_tabs(self, script):
        legacy = [(self.overview_tab, "Test data"), (self.steps_tab, "Steps"), (self.json_tab, "JSON / Expected")]
        generic = [(self.script_data_tab, "Test data"), (self.script_steps_tab, "Steps")]
        if script is None:
            for frame, _ in legacy + generic:
                self.notebook.hide(frame)
            self.apply_button.configure(state="disabled")
            self.notebook.tab(self.source_tab, text="Workspace")
            self.notebook.select(self.source_tab)
            return
        self.apply_button.configure(state="normal")
        self.notebook.tab(self.source_tab, text="Source")
        for frame, _ in legacy if script else generic:
            self.notebook.hide(frame)
        for index, (frame, title) in enumerate(generic if script else legacy):
            self.notebook.insert(index, frame, text=title, state="normal")

    def _build_inspector(self):
        ttk.Label(self.inspector, text="RUN CONFIGURATION", style="Section.TLabel").pack(anchor="w", pady=(0, 14))
        self.environment = tk.StringVar(self, self.workspace.settings.get("active_environment", "(current)"))
        self.environment_box = ttk.Combobox(self.inspector, textvariable=self.environment,
            values=["(current)", *self.workspace.settings.get("environments", {})], state="readonly", width=23)
        self.environment_box.pack(fill="x", pady=(0, 6))
        self.environment_box.bind("<<ComboboxSelected>>", self._select_environment)
        self.run_vars = {}
        self.run_labels, self.run_widgets = {}, {}
        has_gradebook = any(n["kind"] == "case" and not is_script(n["record"]) for n, _ in self.workspace.walk())
        settings = [("mode", "Mode", "Functional", ("Functional", "Compatibility NFR", "Elapsed-time NFR")),
                    ("level", "Automation level", "Level 2", ("Level 1", "Level 2")),
                    ("browser", "Browser", "Chrome", ("Chrome", "Edge", "Opera GX", "Both")),
                    ("base_url", "Base URL", self.workspace.settings.get("base_url", "http://127.0.0.1:9501" if has_gradebook else ""), None),
                    ("course_id", "Course ID (Gradebook)", "2" if has_gradebook else "", None),
                    ("username", "Username", os.environ.get("TESTBOX_VAR_username", os.environ.get("MOODLE_USERNAME", "teacher01") if has_gradebook else ""), None),
                    ("password", "Password", os.environ.get("TESTBOX_VAR_password", os.environ.get("MOODLE_PASSWORD", "1234") if has_gradebook else ""), None)]
        for key, label, value, choices in settings:
            self.run_labels[key] = ttk.Label(self.inspector, text=label, style="Muted.TLabel", font=("Segoe UI", 9))
            self.run_labels[key].pack(anchor="w", pady=(6, 4))
            variable = tk.StringVar(self, value)
            self.run_vars[key] = variable
            widget = ttk.Combobox(self.inspector, textvariable=variable, values=choices, state="readonly", width=23) if choices else ttk.Entry(self.inspector, textvariable=variable, show="●" if key == "password" else "", width=25)
            widget.pack(fill="x", pady=(0, 5))
            self.run_widgets[key] = widget
        self.run_vars["mode"].trace_add("write", lambda *_: self._mode_controls())
        self.headless = tk.BooleanVar(self, True)
        ttk.Checkbutton(self.inspector, text="Headless (background)", variable=self.headless).pack(anchor="w", pady=(5, 0))
        self.start_paused = tk.BooleanVar(self, False)
        ttk.Checkbutton(self.inspector, text="Start paused (editable steps)", variable=self.start_paused).pack(anchor="w", pady=(5, 0))
        self.highlight_steps = tk.BooleanVar(self, self.workspace.settings.get("highlight", False))
        ttk.Checkbutton(self.inspector, text="Highlight active element", variable=self.highlight_steps).pack(anchor="w", pady=(5, 0))
        self.slow_ms = tk.StringVar(self, str(self.workspace.settings.get("slow_ms", 0)))
        ttk.Label(self.inspector, text="Step delay (milliseconds)", style="Muted.TLabel").pack(anchor="w", pady=(5, 3))
        ttk.Spinbox(self.inspector, from_=0, to=10000, increment=100, textvariable=self.slow_ms, width=15).pack(fill="x")
        ttk.Button(self.inspector, text="Check connection", command=self._check_connection, style="Small.TButton").pack(fill="x", pady=(8, 0))
        ttk.Button(self.inspector, text="Save environment…", command=self._save_environment, style="Small.TButton").pack(fill="x", pady=(6, 0))
        self.config_path = ROOT / "level2/config/site.json"
        ttk.Button(self.inspector, text="Project settings…", command=self._edit_project_settings).pack(fill="x", pady=(13, 0))
        ttk.Button(self.inspector, text="Locator library…", command=self._locator_library).pack(fill="x", pady=(6, 0))
        ttk.Button(self.inspector, text="Recorder / picker…", command=self._recorder).pack(fill="x", pady=(6, 0))
        ttk.Button(self.inspector, text="NFR settings…", command=self._nfr_settings).pack(fill="x", pady=(6, 0))
        self.gradebook_buttons = [ttk.Button(self.inspector, text="Gradebook site config…", command=self._edit_config),
                                  ttk.Button(self.inspector, text="Choose Gradebook config…", style="Small.TButton", command=self._choose_config)]
        for button in self.gradebook_buttons:
            button.pack(fill="x", pady=(6, 0))
        self.inspector_divider = ttk.Separator(self.inspector)
        self.inspector_divider.pack(fill="x", pady=17)
        ttk.Label(self.inspector, text="HOW IT RUNS", style="Section.TLabel").pack(anchor="w")
        ttk.Label(self.inspector, text="Run uses a snapshot of the selected cases in folder order.\n\nBrowser tests start only when you press Run. Stop finishes the current case and cleanup.",
                  style="Muted.TLabel", wraplength=210, font=("Segoe UI", 9)).pack(anchor="w", pady=(9, 0))
        self._gradebook_inspector(has_gradebook)

    def _mode_controls(self):
        nfr = self.run_vars["mode"].get() != "Functional"
        for key in ("level", "browser"):
            self.run_widgets[key].configure(state="disabled" if nfr else "readonly")
        self.run_labels["level"].configure(text="Level (use NFR settings)" if nfr else "Automation level")
        self.run_labels["browser"].configure(text="Browser (use NFR settings)" if nfr else "Browser")

    def _gradebook_inspector(self, visible):
        widgets = [self.run_labels["course_id"], self.run_widgets["course_id"]]
        if visible:
            widgets[0].pack(anchor="w", pady=(6, 4), before=self.run_labels["username"])
            widgets[1].pack(fill="x", pady=(0, 5), before=self.run_labels["username"])
            for button in self.gradebook_buttons:
                button.pack(fill="x", pady=(6, 0), before=self.inspector_divider)
        else:
            for widget in [*widgets, *self.gradebook_buttons]:
                widget.pack_forget()

    def _build_console(self):
        frame = ttk.Frame(self.vertical, padding=(16, 10))
        self.vertical.add(frame, weight=1)
        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 7))
        ttk.Label(top, text="EXECUTION", style="Section.TLabel").pack(side="left")
        self.run_label = ttk.Label(top, text="Idle · press Run to start", style="Muted.TLabel")
        self.run_label.pack(side="left", padx=20)
        self.playback_buttons = {}
        for label, action in (("Pause", "pause"), ("Resume", "run"), ("Next step", "next")):
            button = ttk.Button(top, text=label, style="Small.TButton", command=lambda command=action: self._playback(command), state="disabled")
            button.pack(side="left", padx=(0, 4))
            self.playback_buttons[action] = button
        ttk.Button(top, text="Open results", style="Small.TButton", command=self._open_results).pack(side="right")
        ttk.Button(top, text="View report", style="Small.TButton", command=self._view_report).pack(side="right", padx=5)
        ttk.Button(top, text="Clear", style="Small.TButton", command=self._clear_console).pack(side="right", padx=6)
        self.progress = ttk.Progressbar(top, mode="determinate", length=170)
        self.progress.pack(side="right", padx=12)
        tabs = ttk.Notebook(frame)
        tabs.pack(fill="both", expand=True)
        log_frame, result_frame = ttk.Frame(tabs), ttk.Frame(tabs)
        tabs.add(log_frame, text="Live steps")
        tabs.add(result_frame, text="Case results")
        self.console = dark_text(log_frame, height=5)
        self.console.pack(fill="both", expand=True)
        self.console.configure(state="disabled")
        for tag, color in [("info", MUTED), ("step", TEXT), ("PASS", GREEN), ("FAIL", RED), ("ERROR", RED), ("SKIP", YELLOW)]:
            self.console.tag_configure(tag, foreground=color)
        self.result_tree = ttk.Treeview(result_frame, columns=("case", "browser", "status", "duration", "title"), show="headings", selectmode="browse", height=3)
        for key, label, width in [("case", "CASE", 140), ("browser", "BROWSER", 100), ("status", "STATUS", 90), ("duration", "SECONDS", 100), ("title", "NAME", 700)]:
            self.result_tree.heading(key, text=label)
            self.result_tree.column(key, width=width, stretch=key == "title")
        self.result_tree.pack(fill="both", expand=True)
        for tag, color in [("PASS", GREEN), ("FAIL", RED), ("ERROR", RED), ("SKIP", YELLOW), ("NOT_RUN", YELLOW), ("RUNNING", ACCENT)]:
            self.result_tree.tag_configure(tag, foreground=color)
        self.result_tree.bind("<Double-1>", self._result_detail)

    def _bind_keys(self):
        for key, handler in [("<Control-s>", self._save), ("<Control-Shift-S>", lambda: self._save(True)),
                             ("<Control-o>", self._open_workspace), ("<Control-i>", self._import),
                             ("<Control-e>", self._export), ("<Control-n>", self._new_case),
                             ("<Control-Shift-N>", self._new_folder)]:
            self.bind(key, lambda _, fn=handler: (fn(), "break")[-1])
        for key, handler in [("<F2>", self._rename), ("<Delete>", self._delete),
                             ("<Control-d>", self._duplicate), ("<Alt-Up>", lambda: self._reorder(-1)),
                             ("<Alt-Down>", lambda: self._reorder(1)), ("<Control-z>", self._undo), ("<Control-y>", self._redo)]:
            self.tree.bind(key, lambda _, fn=handler: (fn(), "break")[-1])

    def _editor_changed(self, *_):
        if not self.loading and self.editor_uid:
            self.editor_dirty = True
            self._mark_dirty()

    def _text_changed(self, event):
        text = event.widget
        if text.edit_modified():
            text.edit_modified(False)
            self._editor_changed()

    def _mark_dirty(self):
        self.dirty = True
        self.saved_label.configure(text="UNSAVED CHANGES", fg=YELLOW)
        self.title(f"● {self.workspace.name} — {APP_NAME}")

    def _checkpoint(self):
        self.history.append(self.workspace.to_dict())
        self.history = self.history[-50:]
        self.future.clear()

    def _selected(self):
        return list(self.tree.selection())

    def _primary(self):
        selected = self._selected()
        return selected[0] if selected else None

    def _parent_for_new(self):
        uid = self._primary()
        if not uid:
            return None
        return uid if self.workspace.find(uid)["kind"] == "folder" else self.workspace.parent_uid(uid)

    def _draft(self):
        node = self.workspace.find(self.editor_uid)
        if is_script(node["record"]):
            record = self.script_editor.draft(node["record"], self.steps_editor.steps)
            for other, _ in self.workspace.walk():
                if other["kind"] == "case" and other["uid"] != self.editor_uid and other["record"]["case_id"] == record["case_id"]:
                    raise ValueError(f"Case ID already exists: {record['case_id']}")
            return record
        record = deepcopy(node["record"])
        for key, variable in self.vars.items():
            if key != "scale":
                record[key] = variable.get()
        record["case_id"] = record["case_id"].strip()
        record["title"] = record["title"].strip()
        if not record["title"]:
            raise ValueError("A test case needs a name")
        inputs = json.loads(self.inputs_text.get("1.0", "end-1c"))
        expected = json.loads(self.assertions_text.get("1.0", "end-1c"))
        if not isinstance(inputs, dict) or not isinstance(inputs.get("fields"), dict):
            raise ValueError("Input JSON needs a fields object")
        inputs["fields"]["itemname"] = record["item_name"]
        inputs["grade_type"] = record["grade_type"]
        if record["grade_type"] == "Value":
            inputs["fields"].update(grademin=record["minimum"], grademax=record["maximum"])
        else:
            inputs["fields"].pop("grademin", None)
            inputs["fields"].pop("grademax", None)
        if record["grade_type"] == "Scale":
            inputs["scale"] = self.vars["scale"].get()
        record["inputs_json"] = json.dumps(inputs, ensure_ascii=False)
        record["expected_json"] = json.dumps(expected, ensure_ascii=False)
        record["expected_result"] = self.expected_text.get("1.0", "end-1c")
        parse_rows([record])
        for other, _ in self.workspace.walk():
            if other["kind"] == "case" and other["uid"] != self.editor_uid and other["record"]["case_id"] == record["case_id"]:
                raise ValueError(f"Case ID already exists: {record['case_id']}")
        return record

    def _commit(self):
        if not self.editor_uid or not self.editor_dirty:
            return True
        try:
            record = self._draft()
            node = self.workspace.find(self.editor_uid)
            if record != node["record"]:
                self._checkpoint()
                node["record"] = record
                node["name"] = record["title"]
            self.editor_dirty = False
            self.selection_title.configure(text=record["title"])
            self._rebuild_tree()
            return True
        except (ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Cannot apply changes", str(exc), parent=self)
            return False

    def _apply(self):
        if self._commit():
            self._refresh_steps()
            self.status.set("Changes applied · Save workspace to keep them on disk")

    def _set_text(self, widget, value, readonly=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.edit_modified(False)
        if readonly:
            widget.configure(state="disabled")

    def _show_node(self, uid):
        self.loading = True
        try:
            node = self.workspace.find(uid)
            path = next(path for candidate, path in self.workspace.walk() if candidate["uid"] == uid)
            self.breadcrumb.configure(text=" / ".join(("WORKSPACE", *path))[-110:])
            self.selection_title.configure(text=node["name"])
            self.editor_uid = uid if node["kind"] == "case" else None
            self.editor_dirty = False
            if node["kind"] == "folder":
                self._case_tabs(None)
                self._gradebook_inspector(any(not is_script(row) for row in self.workspace.rows([uid])))
                for key in self.vars:
                    self.vars[key].set("")
                for text in (self.expected_text, self.inputs_text, self.assertions_text):
                    self._set_text(text, "")
                count = len(self.workspace.rows([uid]))
                self._set_text(self.source_text, f"FOLDER: {node['name']}\n\n{count} test cases in this folder and its subfolders.\n\nUse + Test case, + Folder, Import, or drag existing items here.\n\nChoose Selected items and press Run to execute this folder in order.", True)
                self.steps_tree.delete(*self.steps_tree.get_children())
                self.notebook.select(self.source_tab)
                self.editor_hint.configure(text=f"Folder selected · {count} cases")
                return
            record = node["record"]
            if is_script(record):
                self._gradebook_inspector(False)
                self._case_tabs(True)
                self.script_editor.load(record)
                self.steps_editor.load(script_data(record)["steps"])
                for key in ("case_id", "title", "workflow"):
                    self.vars[key].set(record[key])
                source = ["EDITABLE BROWSER TEST", "", "The Steps tab contains the executable actions.",
                          "Use ${column} for data values and @name for locator aliases.", "", record.get("notes", ""),
                          "", "IMPORTED MANUAL STEPS (REFERENCE)"]
                for index, step in enumerate(node.get("steps", []), 1):
                    source.extend([f"{index}. {step.get('action', '')}", f"Expected: {step.get('expected', '')}"])
                self._set_text(self.source_text, "\n".join(source), True)
                self.editor_hint.configure(text="Executable steps · data and expected values are independent.")
                self.notebook.select(self.script_steps_tab)
                return
            self._case_tabs(False)
            self._gradebook_inspector(True)
            inputs = json.loads(record["inputs_json"])
            for key, variable in self.vars.items():
                variable.set(inputs.get("scale", "") if key == "scale" else record.get(key, ""))
            self._set_text(self.expected_text, record["expected_result"])
            self._set_text(self.inputs_text, json.dumps(inputs, ensure_ascii=False, indent=2))
            self._set_text(self.assertions_text, json.dumps(json.loads(record["expected_json"]), ensure_ascii=False, indent=2))
            source = [f"CASE: {record['case_id']}", f"SHEET: {record.get('source_sheet', '')}  ROW: {record.get('source_row', '')}",
                      f"KNOWN DEFECT: {record.get('known_defect') or '—'}", "", "PRECONDITIONS", record.get("precondition", ""),
                      "", "NOTES", record.get("notes", ""), "", "IMPORTED MANUAL STEPS (REFERENCE)"]
            for i, step in enumerate(node.get("steps", []), 1):
                source.extend([f"\n{i}. {step['action']}", f"Expected: {step['expected']}"])
            if not node.get("steps"):
                source.append("No original manual steps were imported. See Steps for the generated workflow preview.")
            self._set_text(self.source_text, "\n".join(source), True)
            self.editor_hint.configure(text="Input and expected values are independent.")
            if self.notebook.select() == str(self.source_tab):
                self.notebook.select(self.overview_tab)
            self._refresh_steps()
        finally:
            self.loading = False

    def _on_select(self, _=None):
        if self.loading:
            return
        uid = self._primary()
        if not uid or uid == self.editor_uid:
            return
        previous = self.editor_uid
        if not self._commit():
            if previous and self.tree.exists(previous):
                self.tree.selection_set(previous)
            return
        self._show_node(uid)

    def _rebuild_tree(self, select=None):
        if not hasattr(self, "tree"):
            return
        open_ids = {item for item in self._all_tree_ids() if self.tree.item(item, "open")}
        old_selected = self._selected()
        self.loading = True
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().casefold().strip()
        def matches(node):
            text = node["name"] + (" " + node["record"]["case_id"] if node["kind"] == "case" else "")
            return query in text.casefold() or node["kind"] == "folder" and any(matches(n) for n in node["children"])
        def insert(nodes, parent="", inherited=False):
            for node in nodes:
                if query and not inherited and not matches(node):
                    continue
                uid = node["uid"]
                if node["kind"] == "folder":
                    count = sum(n["kind"] == "case" for n, _ in self.workspace.walk([node]))
                    text = f"{node['name']}  ({count})"
                    self.tree.insert(parent, "end", iid=uid, text=text, tags=("folder",),
                                     open=bool(query) or uid in open_ids or not open_ids and (not parent or node["name"].startswith("01")))
                    insert(node["children"], uid, inherited or bool(query and query in node["name"].casefold()))
                else:
                    case_id = node["record"]["case_id"]
                    state = self.statuses.get(case_id, "")
                    self.tree.insert(parent, "end", iid=uid, text=f"{case_id}  {node['name']}", values=(state,), tags=(state,))
        insert(self.workspace.nodes)
        target = [select] if select else old_selected
        target = [uid for uid in target if self.tree.exists(uid)]
        if target:
            self.tree.selection_set(target)
            self.tree.focus(target[0])
            if select:
                self.tree.see(select)
        count = sum(n["kind"] == "case" for n, _ in self.workspace.walk())
        folders = sum(n["kind"] == "folder" for n, _ in self.workspace.walk())
        self.count_label.configure(text=f"{count:02} CASES     /     {folders:02} FOLDERS")
        self.loading = False

    def _all_tree_ids(self):
        def walk(parent=""):
            for uid in self.tree.get_children(parent):
                yield uid
                yield from walk(uid)
        return list(walk())

    def _refresh_steps(self):
        if not hasattr(self, "steps_tree") or not self.editor_uid:
            return
        if is_script(self.workspace.find(self.editor_uid)["record"]):
            return
        try:
            record = self._draft() if self.editor_dirty else self.workspace.find(self.editor_uid)["record"]
            steps = planned_steps(record)
            self.steps_tree.delete(*self.steps_tree.get_children())
            for i, step in enumerate(steps, 1):
                self.steps_tree.insert("", "end", values=(i, step["action"], step["expected"]))
        except (ValueError, KeyError, TypeError):
            self.editor_hint.configure(text="Fix the input/expected JSON to preview steps.")

    def _step_detail(self, _=None):
        selected = self.steps_tree.selection()
        if selected:
            number, action, expected = self.steps_tree.item(selected[0], "values")
            self._show_details(f"Step {number}", f"ACTION\n{action}\n\nEXPECTED\n{expected}")

    def _show_details(self, title, value):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=PANEL)
        dialog.geometry(f"850x540+{self.winfo_rootx()+130}+{self.winfo_rooty()+110}")
        text = dark_text(dialog)
        text.pack(fill="both", expand=True, padx=15, pady=15)
        self._set_text(text, value, True)
        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(anchor="e", padx=15, pady=(0, 15))

    def _format_json(self):
        try:
            values = [json.loads(t.get("1.0", "end-1c")) for t in (self.inputs_text, self.assertions_text)]
            for widget, value in zip((self.inputs_text, self.assertions_text), values):
                self._set_text(widget, json.dumps(value, ensure_ascii=False, indent=2))
            self._editor_changed()
        except ValueError as exc:
            messagebox.showerror("Invalid JSON", str(exc), parent=self)

    def _reset_template(self):
        if not self.editor_uid:
            return
        node = self.workspace.find(self.editor_uid)
        if is_script(node["record"]):
            self._templates()
            return
        workflow = self.vars["workflow"].get()
        if workflow not in WORKFLOWS:
            return
        if not messagebox.askyesno("Reset case data", "Replace this case's input and expected data with the selected workflow template?", parent=self):
            return
        self._checkpoint()
        node = self.workspace.find(self.editor_uid)
        record = template_record(node["record"]["case_id"], workflow)
        record["title"] = self.vars["title"].get() or node["name"]
        node["record"] = record
        node["name"] = record["title"]
        self._mark_dirty()
        self._show_node(node["uid"])
        self._rebuild_tree(node["uid"])

    def _templates(self):
        if not self._commit():
            return
        current = self.workspace.find(self.editor_uid)["record"] if self.editor_uid else None
        try:
            dialog = TemplateDialog(self, self.workspace.settings.get("templates", {}), current)
            if dialog.result is None:
                return
            self._checkpoint()
            self.workspace.settings["templates"] = dialog.result["templates"]
            record = dialog.result["record"]
            uid = None
            if record:
                record = instantiate(record, self.workspace.next_case_id())
                uid = self.workspace.add(testcase(record), self._parent_for_new())
            self._mark_dirty()
            self._rebuild_tree(uid)
            if uid:
                self._show_node(uid)
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Case templates", str(exc), parent=self)

    def _load_gradebook_sample(self):
        if not self._confirm_discard():
            return
        self.workspace = Workspace.seed()
        self.workspace_path = LEGACY_WORKSPACE.with_name("gradebook-sample.project.json")
        self.history.clear()
        self.future.clear()
        self.editor_uid = None
        self.editor_dirty = False
        for key, value in dict(base_url="http://127.0.0.1:9501", course_id="2", username="teacher01", password="1234").items():
            self.run_vars[key].set(value)
        self.environment.set("(current)")
        self.environment_box.configure(values=["(current)"])
        self._mark_dirty()
        self._rebuild_tree()
        self._show_first()

    def _recorder(self):
        if not self._commit():
            return
        try:
            settings = self._effective_settings()
            current = self.workspace.find(self.editor_uid) if self.editor_uid else None
            record = current["record"] if current else None
            can_append = bool(record and is_script(record))
            occupied = set(settings.get("variables", {}))
            if can_append:
                data = script_data(record)
                occupied.update(data["variables"])
                occupied.update(key for row in data["dataset"] for key in row)
            dialog = RecorderDialog(self, settings, occupied, can_append)
            if not dialog.result:
                return
            result = dialog.result
            if not result["steps"]:
                messagebox.showinfo("No recorded steps", "No actions were applied. Record actions or add an assertion first.", parent=self)
                return
            self._checkpoint()
            environment = self.workspace.settings.get("environments", {}).get(self.environment.get())
            target = environment if environment is not None else self.workspace.settings
            target.setdefault("locators", {}).update(result["locators"])
            if result["destination"] == "Append to selected case" and can_append:
                actions = data["steps"] + result["steps"]
                variables = {**data["variables"], **result["variables"]}
                record.update(actions_json=json.dumps(actions, ensure_ascii=False), variables_json=json.dumps(variables, ensure_ascii=False))
                uid = current["uid"]
            else:
                record = template_record(self.workspace.next_case_id(), "steps")
                record.update(title="Recorded browser test", actions_json=json.dumps(result["steps"], ensure_ascii=False),
                    variables_json=json.dumps(result["variables"], ensure_ascii=False),
                    notes="Recorded in an owned Chrome profile. Review selectors, input variables and expected assertions before Run.")
                uid = self.workspace.add(testcase(record), self._parent_for_new())
            self._mark_dirty()
            self._rebuild_tree(uid)
            self._show_node(uid)
            self.notebook.select(self.script_steps_tab)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            messagebox.showerror("Browser recorder", str(exc), parent=self)

    def _new_folder(self):
        if not self._commit():
            return
        dialog = FormDialog(self, "New folder", [("name", "Folder name", "New folder", None)])
        if dialog.result:
            self._checkpoint()
            uid = self.workspace.add(folder(dialog.result["name"]), self._parent_for_new())
            self._mark_dirty()
            self._rebuild_tree(uid)
            self._show_node(uid)

    def _new_case(self):
        if not self._commit():
            return
        dialog = FormDialog(self, "New test case", [("name", "Test case name", "New test case", None),
                                                     ("workflow", "Workflow template", "steps", WORKFLOWS)])
        if dialog.result:
            self._checkpoint()
            record = template_record(self.workspace.next_case_id(), dialog.result["workflow"])
            record["title"] = dialog.result["name"]
            uid = self.workspace.add(testcase(record), self._parent_for_new())
            self._mark_dirty()
            self._rebuild_tree(uid)
            self._show_node(uid)

    def _rename(self):
        if not self._commit() or not self._primary():
            return
        node = self.workspace.find(self._primary())
        dialog = FormDialog(self, "Rename", [("name", "Name", node["name"], None)])
        if dialog.result:
            self._checkpoint()
            node["name"] = dialog.result["name"]
            if node["kind"] == "case":
                node["record"]["title"] = node["name"]
            self._mark_dirty()
            self._rebuild_tree(node["uid"])
            self._show_node(node["uid"])

    def _duplicate(self):
        if not self._commit() or not self._primary():
            return
        uid = self._primary()
        clone = deepcopy(self.workspace.find(uid))
        used = set()
        for node, _ in self.workspace.walk([clone]):
            node["uid"] = uuid4().hex
            if node["kind"] == "case":
                node["record"]["original_case_id"] = node["record"]["case_id"]
                node["record"]["case_id"] = self.workspace.next_case_id(used)
                used.add(node["record"]["case_id"])
        clone["name"] += " (copy)"
        if clone["kind"] == "case":
            clone["record"]["title"] = clone["name"]
        self._checkpoint()
        container = self.workspace.container(uid)
        index = next(i for i, n in enumerate(container) if n["uid"] == uid)
        container.insert(index + 1, clone)
        self._mark_dirty()
        self._rebuild_tree(clone["uid"])
        self._show_node(clone["uid"])

    def _top_selected(self):
        selected = set(self._selected())
        result = []
        for node, _ in self.workspace.walk():
            uid = node["uid"]
            if uid not in selected:
                continue
            parent = self.workspace.parent_uid(uid)
            while parent and parent not in selected:
                parent = self.workspace.parent_uid(parent)
            if parent is None:
                result.append(uid)
        return result

    def _delete(self):
        if not self._commit():
            return
        selected = self._top_selected()
        if not selected or not messagebox.askyesno("Delete items", f"Delete {len(selected)} selected item(s), including their contents? You can undo this change.", parent=self):
            return
        self._checkpoint()
        for uid in selected:
            container = self.workspace.container(uid)
            container.remove(self.workspace.find(uid))
        self.editor_uid = None
        self.editor_dirty = False
        self._mark_dirty()
        self._rebuild_tree()
        first = next((n["uid"] for n, _ in self.workspace.walk()), None)
        if first:
            self.tree.selection_set(first)
            self._show_node(first)
        else:
            self._empty_editor()

    def _move_dialog(self):
        if not self._commit() or not self._primary():
            return
        selected = self._top_selected()
        excluded = {n["uid"] for uid in selected for n, _ in self.workspace.walk([self.workspace.find(uid)])}
        choices = {"Workspace root": None}
        for node, path in self.workspace.walk():
            if node["kind"] == "folder" and node["uid"] not in excluded:
                label = " / ".join((*path, node["name"]))
                if label in choices:
                    label += " · " + node["uid"][:6]
                choices[label] = node["uid"]
        dialog = FormDialog(self, "Move to folder", [("folder", "Destination", "Workspace root", tuple(choices))])
        if dialog.result:
            self._checkpoint()
            for uid in selected:
                self.workspace.move(uid, choices[dialog.result["folder"]])
            self._mark_dirty()
            self._rebuild_tree(selected[0])
            self._show_node(selected[0])

    def _reorder(self, direction):
        if not self._commit() or not self._primary():
            return
        uid = self._primary()
        node = self.workspace.find(uid)
        container = self.workspace.container(uid)
        index = container.index(node)
        target = index + direction
        if 0 <= target < len(container):
            self._checkpoint()
            container[index], container[target] = container[target], container[index]
            self._mark_dirty()
            self._rebuild_tree(uid)

    def _drag_press(self, event):
        self.drag_start = (self.tree.identify_row(event.y), event.x, event.y, False)

    def _drag_motion(self, event):
        if self.drag_start and self.drag_start[0] and abs(event.y - self.drag_start[2]) > 8:
            self.drag_start = (*self.drag_start[:3], True)
            self.tree.configure(cursor="fleur")
            if event.y < 25:
                self.tree.yview_scroll(-1, "units")
            elif event.y > self.tree.winfo_height() - 25:
                self.tree.yview_scroll(1, "units")

    def _drag_release(self, event):
        self.tree.configure(cursor="")
        drag, self.drag_start = self.drag_start, None
        if not drag or not drag[3] or not self._commit():
            return
        uid = drag[0]
        target = self.tree.identify_row(event.y)
        if target == uid:
            return
        try:
            parent, index = None, None
            if target:
                node = self.workspace.find(target)
                if node["kind"] == "folder":
                    parent = target
                else:
                    parent = self.workspace.parent_uid(target)
                    container = self.workspace.container(target)
                    index = container.index(node)
                    bbox = self.tree.bbox(target)
                    if bbox and event.y > bbox[1] + bbox[3] / 2:
                        index += 1
            self._checkpoint()
            self.workspace.move(uid, parent, index)
            self._mark_dirty()
            self._rebuild_tree(uid)
            self._show_node(uid)
        except ValueError as exc:
            messagebox.showerror("Cannot move", str(exc), parent=self)

    def _context_menu(self, event):
        uid = self.tree.identify_row(event.y)
        if uid and uid not in self.tree.selection():
            self.tree.selection_set(uid)
            self.tree.focus(uid)
        menu = dark_menu(self)
        for label, command in [("＋ Test case", self._new_case), ("＋ Folder", self._new_folder),
                               ("Rename…", self._rename), ("Duplicate", self._duplicate),
                               ("Move to folder…", self._move_dialog), ("Move up", lambda: self._reorder(-1)),
                               ("Move down", lambda: self._reorder(1)), ("Export selection…", self._export),
                               ("Delete…", self._delete)]:
            menu.add_command(label=label, command=command)
        menu.tk_popup(event.x_root, event.y_root)

    def _undo(self):
        if not self._commit() or not self.history:
            return
        self.future.append(self.workspace.to_dict())
        self.workspace = Workspace.from_dict(self.history.pop())
        self._sync_settings_view()
        self.editor_uid = None
        self._mark_dirty()
        self._rebuild_tree()
        self._show_first()

    def _redo(self):
        if not self._commit() or not self.future:
            return
        self.history.append(self.workspace.to_dict())
        self.workspace = Workspace.from_dict(self.future.pop())
        self._sync_settings_view()
        self.editor_uid = None
        self._mark_dirty()
        self._rebuild_tree()
        self._show_first()

    def _show_first(self):
        uid = next((n["uid"] for n, _ in self.workspace.walk()), None)
        if uid:
            self.tree.selection_set(uid)
            self._show_node(uid)
        else:
            self._empty_editor()

    def _empty_editor(self):
        self.editor_uid, self.editor_dirty = None, False
        self.selection_title.configure(text="Create a test case, use a template, or import your file")
        self._case_tabs(None)
        self._gradebook_inspector(any(n["kind"] == "case" and not is_script(n["record"]) for n, _ in self.workspace.walk()))
        self._set_text(self.source_text, "Use + Test case for editable steps, or Tools > Case templates. Import CSV/XLS/XLSX to map your steps and data.\n\nSet the website URL before running. Existing Gradebook samples are available from Tools > Load Gradebook sample.", True)

    def _save(self, save_as=False):
        if not self._commit():
            return False
        path = self.workspace_path
        if save_as:
            name = filedialog.asksaveasfilename(parent=self, title="Save workspace", defaultextension=".json",
                                               filetypes=[("Workspace JSON", "*.json")], initialfile=path.name)
            if not name:
                return False
            path = Path(name)
        try:
            self.workspace.save(path)
            self.workspace_path = path
            self.dirty = False
            self.saved_label.configure(text="WORKSPACE SAVED", fg=GREEN)
            self.title(f"{self.workspace.name} — {APP_NAME}")
            self.status.set(f"Saved: {path}")
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False

    def _confirm_discard(self):
        if not self.dirty and not self.editor_dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", "Save workspace changes before continuing?", parent=self)
        return self._save() if answer else answer is False

    def _new_workspace(self):
        if not self._confirm_discard():
            return
        self.workspace = Workspace("Untitled workspace")
        for key in ("base_url", "course_id", "username", "password"):
            self.run_vars[key].set("")
        self.environment.set("(current)")
        self.environment_box.configure(values=["(current)"])
        self.run_vars["mode"].set("Functional")
        self._sync_settings_view()
        self.workspace_path = DEFAULT_WORKSPACE.with_name("untitled.project.json")
        self.history.clear()
        self.future.clear()
        self.editor_uid = None
        self.editor_dirty = False
        self._rebuild_tree()
        self._mark_dirty()
        self.selection_title.configure(text="Create a folder or import test data")
        for var in self.vars.values():
            var.set("")
        for text in (self.expected_text, self.inputs_text, self.assertions_text):
            self._set_text(text, "")
        self.steps_tree.delete(*self.steps_tree.get_children())

        self.steps_editor.load([])
        self._case_tabs(None)
        self._set_text(self.source_text, "Create an editable test case with + Test case, or import steps and data from CSV/XLS/XLSX.", True)
        self.notebook.select(self.source_tab)
        self._gradebook_inspector(False)

    def _open_workspace(self):
        if not self._confirm_discard():
            return
        name = filedialog.askopenfilename(parent=self, title="Open workspace", filetypes=[("Workspace JSON", "*.json")])
        if not name:
            return
        try:
            workspace = Workspace.load(Path(name))
            self.workspace, self.workspace_path = workspace, Path(name)
            self.history.clear()
            self.future.clear()
            self.editor_uid = None
            self.editor_dirty = self.dirty = False
            self._rebuild_tree()
            self._show_first()
            self.saved_label.configure(text="WORKSPACE SAVED", fg=GREEN)
            self.status.set(f"Opened: {name}")
            self._sync_settings_view()
            self.run_vars["username"].set("")
            self.run_vars["password"].set("")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Open failed", str(exc), parent=self)

    def _import(self):
        if not self._commit():
            return
        name = filedialog.askopenfilename(parent=self, title="Import test cases", filetypes=FILE_TYPES)
        if not name:
            return
        try:
            selected = self.workspace.find(self.editor_uid) if self.editor_uid else None
            selected = selected if selected and is_script(selected["record"]) else None
            dialog = ImportWizard(self, Path(name), self.workspace.settings.get("import_profiles", {}),
                                  selected_case=selected["record"]["case_id"] if selected else None)
            if not dialog.result:
                return
            result = dialog.result
            staging = Workspace.from_dict(self.workspace.to_dict())
            renamed = 0
            if result["kind"] == "dataset":
                if selected and result.get("use_selected"):
                    if not messagebox.askyesno("Replace dataset", f"Replace data rows for {selected['record']['case_id']} with this imported dataset?", parent=self):
                        return
                    node = staging.find(selected["uid"])
                    node["record"]["dataset_json"] = json.dumps(result["dataset"], ensure_ascii=False)
                    target = node["uid"]
                else:
                    record = template_record(staging.next_case_id(), "steps")
                    record.update(title=Path(name).stem, dataset_json=json.dumps(result["dataset"], ensure_ascii=False))
                    target = staging.add(testcase(record), self._parent_for_new())
                count = len(result["dataset"])
                description = f"Imported {count} data rows"
            else:
                container = folder(Path(name).stem)
                target = staging.add(container, self._parent_for_new())
                count, renamed = staging.import_rows(result["records"], target)
                description = f"Imported {count} cases · {result['drafts']} disabled manual steps need review"
            if "profile" in result:
                profile_name, profile = result["profile"]
                staging.settings.setdefault("import_profiles", {})[profile_name] = profile
            self._checkpoint()
            self.workspace = staging
            self.editor_uid = None
            self._mark_dirty()
            self._rebuild_tree(target)
            self._show_node(target)
            self.status.set(description + f" · {Path(name).name}")
            self._log(description + f". {renamed} duplicate IDs renamed; originals retained.", "info")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self)

    def _export(self):
        if not self._commit():
            return
        selected = self._selected()
        if selected:
            answer = messagebox.askyesnocancel("Export scope", "Export selected items and their contents?\n\nYes: selection · No: entire workspace", parent=self)
            if answer is None:
                return
            selected = selected if answer else None
        try:
            rows = self.workspace.rows(selected or None)
            if not rows:
                raise ValueError("There are no test cases in this selection")
            name = filedialog.asksaveasfilename(parent=self, title="Export test data", defaultextension=".csv",
                                               initialfile="gradebook_cases.csv", filetypes=FILE_TYPES[1:])
            if not name:
                return
            write_table(Path(name), rows)
            self.status.set(f"Exported {len(rows)} cases: {name}")
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

    def _export_python(self):
        if not self._commit():
            return
        dialog = FormDialog(self, "Export runnable Python", [
            ("scope", "Cases", "Selection" if self._selected() else "All cases", ("Selection", "All cases")),
            ("levels", "Export levels", "Both levels", ("Both levels", "Level 1", "Level 2"))])
        if not dialog.result:
            return
        try:
            selected = self._selected() if dialog.result["scope"] == "Selection" else None
            if dialog.result["scope"] == "Selection" and not selected:
                raise ValueError("Select at least one case or folder before exporting a selection")
            rows = self.workspace.rows(selected)
            if not rows:
                raise ValueError("There are no test cases to export")
            name = filedialog.asksaveasfilename(parent=self, title="Export standalone Selenium/unittest suite",
                defaultextension=".zip", initialfile="testbox-python.zip", filetypes=[("Python suite ZIP", "*.zip")])
            if not name:
                return
            from automation.exporting import export_python
            settings = self._effective_settings()
            settings["course_id"] = self.run_vars["course_id"].get().strip()
            legacy = json.loads(self.config_path.read_text(encoding="utf-8")) if any(not is_script(r) for r in rows) else None
            levels = (1, 2) if dialog.result["levels"] == "Both levels" else (int(dialog.result["levels"][-1]),)
            result = export_python(name, rows, settings, levels=levels,
                project_dir=self.workspace_path.resolve().parent, legacy_site=legacy)
            self.status.set(f"Exported {result['cases']} cases to Python: {name}")
            messagebox.showinfo("Python suite exported", f"Saved: {name}\n\nExtract the ZIP and follow README.md. "
                "Inputs and expected values are read from CSV at runtime.\n\nReview saved data before sharing; "
                "credentials already in datasets/variables are included."
                + ("\n\n" + "\n".join(result["warnings"]) if result["warnings"] else ""), parent=self)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Python export failed", str(exc), parent=self)

    def _choose_config(self):
        name = filedialog.askopenfilename(parent=self, title="Choose Level 2 configuration", filetypes=[("JSON", "*.json")])
        if name:
            self.config_path = Path(name)
            self.status.set(f"Level 2 configuration: {name}")

    def _edit_project_settings(self):
        current = {"base_url": self.run_vars["base_url"].get(), "locators": {}, "variables": {},
                   "window": [1440, 900], "slow_ms": 0, "highlight": False, **deepcopy(self.workspace.settings)}
        dialog = JsonDialog(self, "Project settings", current, required=("base_url", "locators", "variables"),
                            description="General browser tests: base URL, locator aliases (for example login_button: css=#login), and shared variables. Use Run configuration for credentials.")
        if dialog.result is not None:
            try:
                checked_settings(dialog.result)
            except ValueError as exc:
                messagebox.showerror("Invalid project settings", str(exc), parent=self)
                return
            self._checkpoint()
            self.workspace.settings = dialog.result
            self.run_vars["base_url"].set(dialog.result["base_url"])
            self._mark_dirty()

    def _effective_settings(self):
        settings = deepcopy(self.workspace.settings)
        environment = settings.get("environments", {}).get(self.environment.get(), {})
        for key in ("variables", "locators"):
            settings[key] = {**settings.get(key, {}), **environment.get(key, {})}
        settings.update({key: value for key, value in environment.items() if key not in {"variables", "locators"}})
        settings["base_url"] = self.run_vars["base_url"].get().strip()
        try:
            settings["slow_ms"] = float(self.slow_ms.get())
        except ValueError as exc:
            raise ValueError("Step delay must be a number between 0 and 10000 milliseconds") from exc
        settings["highlight"] = self.highlight_steps.get()
        checked_settings(settings)
        return settings

    def _sync_settings_view(self):
        profiles = self.workspace.settings.get("environments", {})
        active = self.workspace.settings.get("active_environment", "(current)")
        self.environment_box.configure(values=["(current)", *profiles])
        self.environment.set(active if active in profiles else "(current)")
        self._apply_environment_values()

    def _apply_environment_values(self):
        values = {**self.workspace.settings, **self.workspace.settings.get("environments", {}).get(self.environment.get(), {})}
        legacy = any(n["kind"] == "case" and not is_script(n["record"]) for n, _ in self.workspace.walk())
        self.run_vars["base_url"].set(values.get("base_url", "http://127.0.0.1:9501" if legacy else ""))
        self.run_vars["course_id"].set(str(values.get("course_id", "2" if legacy else "")))
        self.run_vars["browser"].set(values.get("browser", "Chrome"))
        self.headless.set(values.get("headless", True))
        self.slow_ms.set(str(values.get("slow_ms", 0)))
        self.highlight_steps.set(values.get("highlight", False))

    def _select_environment(self, _=None, remember=True):
        if self.workspace.settings.get("active_environment", "(current)") != self.environment.get():
            if remember:
                self._checkpoint()
            self.workspace.settings["active_environment"] = self.environment.get()
            self._mark_dirty()
        self._apply_environment_values()

    def _save_environment(self):
        values = self._effective_settings()
        dialog = FormDialog(self, "Save environment", [
            ("name", "Environment name", "Local" if self.environment.get() == "(current)" else self.environment.get(), None),
            ("base_url", "Base URL", self.run_vars["base_url"].get(), None),
            ("browser", "Browser", self.run_vars["browser"].get(), ("Chrome", "Edge", "Opera GX", "Both")),
            ("display", "Display", "Headless" if self.headless.get() else "Visible", ("Headless", "Visible")),
            ("width", "Viewport width", str(values.get("window", [1440, 900])[0]), None),
            ("height", "Viewport height", str(values.get("window", [1440, 900])[1]), None),
            ("timeout", "Element timeout (seconds)", str(values.get("timeout", 15)), None),
            ("slow_ms", "Delay between steps (milliseconds)", str(values.get("slow_ms", 0)), None)])
        if not dialog.result:
            return
        try:
            row = dialog.result
            profile = dict(base_url=row["base_url"], browser=row["browser"], headless=row["display"] == "Headless",
                           window=[int(row["width"]), int(row["height"])], timeout=float(row["timeout"]), slow_ms=float(row["slow_ms"]))
            checked_settings(profile)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid environment", str(exc), parent=self)
            return
        self._checkpoint()
        self.workspace.settings.setdefault("environments", {})[row["name"]] = profile
        self.environment_box.configure(values=["(current)", *self.workspace.settings["environments"]])
        self.environment.set(row["name"])
        self._select_environment(remember=False)
        self._mark_dirty()

    def _check_connection(self):
        try:
            message = website_status(self.run_vars["base_url"].get().strip())
            self.status.set(message)
            messagebox.showinfo("Connection check", message, parent=self)
        except ValueError as exc:
            messagebox.showerror("Website is not ready", str(exc), parent=self)

    def _locator_library(self):
        if not self._commit():
            return
        try:
            settings = self._effective_settings()
            variables = dict(settings.get("variables", {}))
            variables.update(username=self.run_vars["username"].get(), password=self.run_vars["password"].get())
            if self.editor_uid:
                record = self.workspace.find(self.editor_uid)["record"]
                if is_script(record):
                    from automation.runner import variables_for
                    data = script_data(record)
                    index = self.script_editor.dataset.selected_row() or 0
                    row = data["dataset"][index] if data["dataset"] else {}
                    variables = variables_for(record, row, {**settings, "variables": variables}, "locator-preview")
            browser = self.run_vars["browser"].get()
            browser = "opera" if browser == "Opera GX" else "chrome" if browser == "Both" else browser.lower()
            dialog = LocatorLibraryDialog(self, settings, browser, variables)
            if dialog.result is not None:
                self._checkpoint()
                environment = self.workspace.settings.get("environments", {}).get(self.environment.get())
                target = environment if environment is not None else self.workspace.settings
                target["locators"] = dialog.result
                self._mark_dirty()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Locator library", str(exc), parent=self)

    def _edit_config(self):
        try:
            current = json.loads(self.config_path.read_text(encoding="utf-8"))
            dialog = JsonDialog(self, "Level 2 · URLs & locators", current)
            if dialog.result:
                self.config_path.write_text(json.dumps(dialog.result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self.run_vars["base_url"].set(dialog.result["base_url"])
                self.run_vars["course_id"].set(str(dialog.result["course_id"]))
                self.status.set(f"Saved site configuration: {self.config_path}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Configuration error", str(exc), parent=self)

    def _nfr_settings(self):
        if not self._commit():
            return
        current = self.workspace.find(self.editor_uid)["record"]["case_id"] if self.editor_uid else None
        dialog = NfrDialog(self, self.workspace.rows(), self.workspace.settings.get("nfr", {}), current)
        if dialog.result is not None:
            self._checkpoint()
            self.workspace.settings["nfr"] = dialog.result
            self._mark_dirty()

    def _start_nfr(self, rows, effective):
        from automation.nfr import checked_nfr
        from automation.runner import preflight
        kind = "compatibility" if self.run_vars["mode"].get() == "Compatibility NFR" else "elapsed"
        settings = {**effective, "course_id": self.run_vars["course_id"].get().strip(),
                    "project_dir": str(self.workspace_path.resolve().parent)}
        settings["nfr"] = checked_nfr(settings.get("nfr", {}), rows, kind)
        if kind == "elapsed" and (self.start_paused.get() or settings.get("slow_ms", 0)):
            raise ValueError("Turn off Start paused and set step delay to 0 for elapsed NFR")
        probe = {**settings, "variables": {**settings.get("variables", {}),
            "username": self.run_vars["username"].get(), "password": self.run_vars["password"].get()}}
        preflight(rows, probe)
        run_home = ROOT / "results" / ("studio-nfr-" + datetime.now(BANGKOK).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
        run_home.mkdir(parents=True, exist_ok=False)
        snapshot = run_home / "project-snapshot.json"
        snapshot.write_text(json.dumps(dict(records=rows, settings=settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stop_file = run_home / "stop.request"
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        command = [str(executable), "-u", "-m", "automation.nfr", "--project", str(snapshot), "--kind", kind,
            "--output", str(run_home), "--events", "--stop-file", str(self.stop_file), "--legacy-config", str(self.config_path)]
        if self.headless.get():
            command.append("--headless")
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
            "MOODLE_USERNAME": self.run_vars["username"].get(), "MOODLE_PASSWORD": self.run_vars["password"].get(),
            "TESTBOX_VAR_username": self.run_vars["username"].get(), "TESTBOX_VAR_password": self.run_vars["password"].get()}
        self._clear_console()
        self.last_output = run_home
        self.run_count = 0
        matrix = settings["nfr"]
        self.run_total = sum(len(script_data(r)["dataset"]) if is_script(r) else 1 for r in rows) * len(matrix["levels"]) * len(matrix["browsers"]) * matrix["repetitions"]
        self.run_generic, self.run_nfr, self.playback_path = False, True, None
        self.execution_states.clear()
        self.stop_button.configure(text="■ Stop after case", state="normal")
        for button in self.playback_buttons.values():
            button.configure(state="disabled")
        self.progress.configure(maximum=self.run_total, value=0)
        self.run_button.configure(state="disabled")
        self.run_label.configure(text=f"Starting NFR · {self.run_total} executions")
        self._log(f"Starting {kind} NFR · levels {matrix['levels']} · browsers {matrix['browsers']} · {matrix['repetitions']} repetitions", "info")
        self.status.set("Running NFR from an immutable snapshot; both levels use their exported definitions")
        self.process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        threading.Thread(target=self._read_process, args=(self.process,), daemon=True).start()

    def _run(self):
        if self.process and self.process.poll() is None or not self._commit():
            return
        if not importlib.util.find_spec("selenium"):
            messagebox.showerror("Selenium is not installed", "Install dependencies before running:\n\npython -m pip install -r requirements.txt\n\nYou can manage and export test data without running Selenium.", parent=self)
            return
        nfr = self.run_vars["mode"].get() != "Functional"
        selected = self._selected() if self.scope.get() == "Selected items" else None
        if self.scope.get() == "Selected items" and not selected:
            messagebox.showinfo("Select test cases", "Select a case or folder, or choose All cases.", parent=self)
            return
        try:
            rows = self.workspace.rows(selected)
            parse_rows(rows)
            generic = any(is_script(row) for row in rows)
            effective = self._effective_settings()
            if effective.get("check_connection", True):
                self.status.set("Checking website connection…")
                self.update_idletasks()
                website_status(effective.get("base_url", ""))
            if nfr:
                self._start_nfr(rows, effective)
                return
            token = datetime.now(BANGKOK).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
            run_home = ROOT / "results" / ("studio-" + token)
            run_home.mkdir(parents=True, exist_ok=False)
            data_path = run_home / "input-snapshot.csv"
            write_table(data_path, rows)
            self.stop_file = run_home / "stop.request"
            executable = Path(sys.executable)
            if sys.platform == "win32" and executable.name.lower() == "pythonw.exe":
                executable = executable.with_name("python.exe")
            command = [str(executable), "-u", "-m", "gradebook.runner",
                       "--data", str(data_path), "--output", str(run_home), "--events", "--reuse-browser", "--stop-file", str(self.stop_file)]
            level = int(self.run_vars["level"].get()[-1])
            browser_name = "opera" if self.run_vars["browser"].get() == "Opera GX" else self.run_vars["browser"].get().lower()
            command += ["--level", str(level), "--browser", browser_name]
            if self.headless.get():
                command.append("--headless")
            if level == 2:
                command += ["--config", str(self.config_path)]
            command += ["--base-url", self.run_vars["base_url"].get().strip(), "--course-id", self.run_vars["course_id"].get().strip()]
            if generic:
                from automation.runner import preflight
                settings = {**effective, "base_url": self.run_vars["base_url"].get().strip(),
                            "course_id": self.run_vars["course_id"].get().strip(), "project_dir": str(self.workspace_path.resolve().parent)}
                # Credentials stay in the child environment, outside the saved snapshot.
                for key in ("username", "password"):
                    settings.setdefault("variables", {}).pop(key, None)
                probe = {**settings, "variables": {**settings.get("variables", {}),
                                                  "username": self.run_vars["username"].get(), "password": self.run_vars["password"].get()}}
                preflight(rows, probe)
                project_path = run_home / "project-snapshot.json"
                project_path.write_text(json.dumps(dict(records=rows, settings=settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                browser_name = "opera" if self.run_vars["browser"].get() == "Opera GX" else self.run_vars["browser"].get().lower()
                command = [str(executable), "-u", "-m", "automation.runner", "--project", str(project_path),
                           "--level", str(level), "--browser", browser_name, "--output", str(run_home), "--events", "--stop-file", str(self.stop_file)]
                if level == 2:
                    command += ["--legacy-config", str(self.config_path)]
                if self.headless.get():
                    command.append("--headless")
                self.playback_path = run_home / "playback.json"
                self.playback_sequence = 0
                write_control(self.playback_path, "pause" if self.start_paused.get() else "run", 0)
                command += ["--control-file", str(self.playback_path)]
            else:
                runtime_path = run_home / "runtime-settings.json"
                runtime_path.write_text(json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                command += ["--runtime-settings", str(runtime_path)]
            environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                           "MOODLE_USERNAME": self.run_vars["username"].get(), "MOODLE_PASSWORD": self.run_vars["password"].get(),
                           "TESTBOX_VAR_username": self.run_vars["username"].get(), "TESTBOX_VAR_password": self.run_vars["password"].get()}
            self._clear_console()
            self.last_output = run_home
            self.run_count = 0
            self.run_total = sum(len(script_data(r)["dataset"]) if is_script(r) else 1 for r in rows) * (2 if self.run_vars["browser"].get() == "Both" else 1)
            self.execution_states.clear()
            self.run_generic = generic
            self.run_nfr = False
            self.stop_button.configure(text="■ Stop + cleanup" if generic else "■ Stop after case")
            for button in self.playback_buttons.values():
                button.configure(state="normal" if generic else "disabled")
            self.progress.configure(maximum=self.run_total, value=0)
            self.run_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.run_label.configure(text=f"Starting · {self.run_total} executions")
            self.status.set("Running a snapshot · edits to the workspace do not affect this run")
            self._log(f"Starting Level {level} · {self.run_total} executions", "info")
            self.process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            threading.Thread(target=self._read_process, args=(self.process,), daemon=True).start()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.run_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            for button in self.playback_buttons.values():
                button.configure(state="disabled")
            messagebox.showerror("Cannot start run", str(exc), parent=self)

    def _read_process(self, process):
        try:
            for line in process.stdout:
                line = line.rstrip("\r\n")
                if line.startswith("@@GRADEBOOK_EVENT "):
                    try:
                        self.events.put(json.loads(line[len("@@GRADEBOOK_EVENT "):]))
                    except ValueError:
                        self.events.put({"event": "text", "message": line})
                else:
                    self.events.put({"event": "text", "message": line})
            code = process.wait()
            self.events.put({"event": "process_end", "code": code})
        finally:
            if process.stdout:
                process.stdout.close()

    def _poll_events(self):
        try:
            for _ in range(120):
                event = self.events.get_nowait()
                kind = event.get("event")
                case_id, browser = event.get("case_id", ""), event.get("browser", "")
                if kind == "text":
                    if event.get("message"):
                        self._log(event["message"], "info")
                elif kind == "run_start":
                    self.last_output = Path(event["output"])
                elif kind == "case_start":
                    self.statuses[case_id] = "RUNNING"
                    self._rebuild_tree()
                    key = self._execution_key(event)
                    label = self._execution_label(event)
                    item = self.result_tree.insert("", "end", values=(label, browser, "RUNNING", "—", event["title"]), tags=("RUNNING",))
                    self.run_rows[key] = {"item": item, "event": event}
                    self.run_label.configure(text=f"{self.run_count}/{self.run_total} · {case_id} · {browser}")
                    self._log(f"START  {case_id} · {browser}", "info")
                elif kind == "case_not_run":
                    key = self._execution_key(event)
                    if key not in self.run_rows:
                        item = self.result_tree.insert("", "end", values=(self._execution_label(event), browser, "NOT_RUN", "—", event["title"]), tags=("NOT_RUN",))
                        self.run_rows[key] = {"item": item, "event": event}
                    self.execution_states[key] = "NOT_RUN"
                    if self.statuses.get(case_id) not in {"FAIL", "ERROR", "SKIP"}:
                        self.statuses[case_id] = "NOT_RUN"
                    self._rebuild_tree()
                elif kind == "step":
                    self._log(f"{case_id} / {browser}  ›  {event['message']}", "step")
                elif kind == "step_start":
                    self._log(f"{case_id} / {browser} / row {event.get('row_index', 0) + 1}  ›  {event['message']}", "step")
                    if self.editor_uid and self.workspace.find(self.editor_uid)["record"]["case_id"] == case_id:
                        step_id = event.get("step_id")
                        if step_id and self.steps_editor.tree.exists(step_id):
                            self.steps_editor.tree.selection_set(step_id)
                            self.steps_editor.tree.see(step_id)
                elif kind == "step_end":
                    self._log(f"{event['status']}  step {event['index']} · {event['command']} · {event['duration_seconds']}s", event["status"])
                elif kind == "playback":
                    self.run_label.configure(text=f"{event['state'].title()} · {case_id} · {event['command']}")
                    self._log(event["message"], "info")
                    if self.editor_uid and self.workspace.find(self.editor_uid)["record"]["case_id"] == case_id:
                        step_id = event.get("step_id")
                        if step_id and self.steps_editor.tree.exists(step_id):
                            self.steps_editor.tree.selection_set(step_id)
                            self.steps_editor.tree.see(step_id)
                elif kind == "case_end":
                    self.run_count += 1
                    self.progress.configure(value=self.run_count)
                    self.execution_states[self._execution_key(event)] = event["status"]
                    ranking = {"PASS": 0, "NOT_RUN": 1, "SKIP": 1, "RUNNING": 2, "FAIL": 3, "ERROR": 4}
                    self.statuses[case_id] = max((state for key, state in self.execution_states.items() if key[0] == case_id), key=ranking.get)
                    self._rebuild_tree()
                    row = self.run_rows.get(self._execution_key(event))
                    if row:
                        row["event"] = event
                        label = self._execution_label(event)
                        self.result_tree.item(row["item"], values=(label, browser, event["status"], event["duration_seconds"], event["title"]), tags=(event["status"],))
                    self._log(f"{event['status']}  {case_id} · {browser} · {event['duration_seconds']}s", event["status"])
                    if event["status"] in {"FAIL", "ERROR"}:
                        self._log(event.get("actual", ""), event["status"])
                elif kind == "run_end":
                    self.last_output = Path(event["output"])
                    self._log("Run stopped after cleanup." if event.get("stopped") else "Run complete. Results saved.", "info")
                elif kind == "process_end":
                    for row in self.run_rows.values():
                        if row["event"].get("event") == "case_start":
                            unfinished = row["event"]
                            self.statuses[unfinished["case_id"]] = "ERROR"
                            row["event"] = {**unfinished, "status": "ERROR", "actual": "Runner exited without completing this case; no assertion result was received."}
                            self.result_tree.item(row["item"], values=(unfinished["case_id"], unfinished["browser"], "ERROR", "—", unfinished["title"]), tags=("ERROR",))
                    self._rebuild_tree()
                    self.process = None
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    for button in self.playback_buttons.values():
                        button.configure(state="disabled")
                    self.run_label.configure(text=f"Finished · {self.run_count}/{self.run_total} · exit {event['code']}")
                    self.status.set(f"Run finished · results: {self.last_output}")
                    if self.close_when_stopped:
                        self.close_when_stopped = False
                        self._close()
                        return
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _execution_key(self, event):
        return (event.get("case_id", ""), event.get("browser", ""), event.get("row_index", 0),
                event.get("level", 0) if self.run_nfr else 0, event.get("repetition", 1) if self.run_nfr else 1)

    def _execution_label(self, event):
        label = f"{event.get('case_id', '')} · data {event.get('row_index', 0) + 1}"
        if self.run_nfr:
            label += f" · L{event.get('level', '')} · repeat {event.get('repetition', 1)}"
        return label

    def _stop(self):
        if self.process and self.process.poll() is None and self.stop_file:
            self.stop_file.write_text("Stop after current case and cleanup.\n", encoding="utf-8")
            if self.run_generic:
                self._playback("stop")
            self.stop_button.configure(state="disabled")
            self.run_label.configure(text="Stopping + cleanup…" if self.run_generic else "Stopping after current case + cleanup…")
            self._log("Stop requested. The current action finishes, then cleanup runs." if self.run_generic else "Stop requested. The current case will finish and clean up before stopping.", "info")

    def _playback(self, command):
        if self.playback_path and self.run_generic:
            try:
                self.playback_sequence += 1
                write_control(self.playback_path, command, self.playback_sequence)
                self.status.set(f"Playback command sent: {command}")
            except OSError as exc:
                messagebox.showerror("Playback command", str(exc), parent=self)

    def _log(self, message, tag="info"):
        self.console.configure(state="normal")
        timestamp = datetime.now(BANGKOK).strftime("%H:%M:%S")
        self.console.insert("end", f"{timestamp}  {message}\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        if self.process and self.process.poll() is None:
            return
        self._set_text(self.console, "", True)
        self.result_tree.delete(*self.result_tree.get_children())
        self.run_rows.clear()

    def _result_detail(self, _=None):
        selected = self.result_tree.selection()
        if not selected:
            return
        row = next((r for r in self.run_rows.values() if r["item"] == selected[0]), None)
        if row:
            self._show_details("Execution result", json.dumps(row["event"], ensure_ascii=False, indent=2))

    def _open_path(self, path):
        if not path.exists():
            messagebox.showinfo("Not available", f"Path does not exist yet:\n{path}", parent=self)
            return
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def _open_results(self):
        if self.last_output:
            self._open_path(self.last_output)
        else:
            messagebox.showinfo("No run results", "Results will be available after an actual run.", parent=self)

    def _view_report(self, output=None):
        output = Path(output) if output else self.last_output
        if not output or not (output / "results.json").exists():
            messagebox.showinfo("No execution report", "A report is available after a run finishes.", parent=self)
            return
        try:
            ReportViewer(self, output, self._open_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Cannot open report", str(exc), parent=self)

    def _open_report(self):
        name = filedialog.askopenfilename(parent=self, title="Open results.json", filetypes=[("Execution results JSON", "*.json")])
        if name:
            self._view_report(Path(name).parent)

    def _close(self):
        if self.process and self.process.poll() is None:
            if messagebox.askyesno("Run in progress", "Stop and run cleanup, then close the app?" if self.run_generic else "Stop after the current case and cleanup, then close the app?", parent=self):
                self.close_when_stopped = True
                self._stop()
            return
        recorder = next((child for child in self.winfo_children() if isinstance(child, RecorderDialog)), None)
        if recorder:
            recorder.cancel()
            self.after(150, self._close)
            return
        library = next((child for child in self.winfo_children() if isinstance(child, LocatorLibraryDialog)), None)
        if library:
            library.close()
            self.after(150, self._close)
            return
        if self._confirm_discard():
            self.destroy()

    def destroy(self):
        try:
            for callback in self.tk.call("after", "info"):
                # Some ttk timers contain a Tcl command list rather than a
                # registered Python callback. Tkinter.after_cancel assumes the
                # latter; cancel both kinds directly, then normal destruction
                # releases the widgets' registered Python commands.
                self.tk.call("after", "cancel", callback)
            self.update_idletasks()
        except tk.TclError:
            pass
        super().destroy()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop application")
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    app = Studio(args.workspace)
    app.mainloop()


if __name__ == "__main__":
    main()
