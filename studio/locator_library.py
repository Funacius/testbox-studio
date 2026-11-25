"""Editable locator aliases and a separately owned browser inspection session."""

import json
import queue
import threading
import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, ttk

from automation.locators import build_library, library_rows, probe_locator
from automation.schema import locator, resolve
from studio.table_editor import TableEditor
from studio.theme import PANEL, dark_text


class LocatorLibraryDialog(tk.Toplevel):
    def __init__(self, parent, settings, browser, variables=None):
        rows = library_rows(settings.get("locators", {}))
        super().__init__(parent)
        self.title("Locator library · inspect and highlight")
        self.configure(bg=PANEL)
        self.transient(parent)
        self.geometry("1000x730")
        self.result, self.driver = None, None
        self.browser_visible = False
        self.settings, self.browser, self.variables = deepcopy(settings), browser, dict(variables or {})
        self.events, self.busy, self.close_when_done = queue.Queue(), False, False
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Locator library", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Edit aliases, then check a selector in a separate temporary browser. Open visible browser to sign in manually if the page requires it.",
                  style="Muted.TLabel", wraplength=950).pack(anchor="w", pady=(5, 10))
        self.table = TableEditor(body, lambda: None, fixed_columns=("Name", "By", "Selector"))
        self.table.pack(fill="both", expand=True)
        self.table.load_records(rows)
        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=8)
        self.url = tk.StringVar(self, settings.get("base_url", ""))
        ttk.Label(controls, text="URL").pack(side="left", padx=(0, 6))
        ttk.Entry(controls, textvariable=self.url).pack(side="left", fill="x", expand=True)
        self.buttons = []
        for label, callback in (("Open visible browser", self.open_browser), ("Check selected locator", self.check)):
            button = ttk.Button(controls, text=label, command=callback)
            button.pack(side="left", padx=(7, 0))
            self.buttons.append(button)
        ttk.Label(body, text="By: id / name / css / xpath / link / partial_link / tag / class. Select a row to check it.",
                  style="Muted.TLabel", wraplength=950).pack(anchor="w")
        self.output = dark_text(body, height=5)
        self.output.pack(fill="both", expand=True, pady=(8, 0))
        self.output.configure(state="disabled")
        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")
        save = ttk.Button(bottom, text="Apply library", command=self.save, style="Primary.TButton")
        save.pack(side="right", padx=8)
        self.buttons.append(save)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after_id = self.after(80, self.poll)
        self.grab_set()
        self.wait_window()

    def show(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def start(self, operation, task):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")
        self.show(operation + "…")
        def work():
            try:
                self.events.put((operation, True, task()))
            except Exception as exc:
                self.events.put((operation, False, f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def open_browser(self):
        url = self.url.get().strip()
        if not url:
            messagebox.showerror("Missing URL", "Enter a URL to open", parent=self)
            return
        def task():
            from gradebook.browser import close_browser, create_browser
            if self.driver is not None and not self.browser_visible:
                close_browser(self.driver)
                self.driver = None
            if self.driver is None:
                self.driver = create_browser(self.browser, {**self.settings, "command_timeout": 15}, headless=False)
                self.browser_visible = True
            self.driver.get(url)
            return "Browser opened. Sign in or navigate as needed, then check a locator."
        self.start("Opening browser", task)

    def check(self):
        try:
            library = build_library(self.table.records())
            index = self.table.selected_row()
            if index is None:
                raise ValueError("Select a locator row first")
            target = "@" + self.table.rows[index][0].strip()
            by, selector = locator(target, library)
            resolve(selector, self.variables)
        except (ValueError, IndexError) as exc:
            messagebox.showerror("Cannot check locator", str(exc), parent=self)
            return
        url = self.url.get().strip()
        def task():
            from gradebook.browser import create_browser
            if self.driver is None:
                if not url:
                    raise ValueError("Enter a URL first")
                self.driver = create_browser(self.browser, {**self.settings, "command_timeout": 15}, headless=True)
                self.driver.get(url)
            return json.dumps(probe_locator(self.driver, target, library, self.variables), ensure_ascii=False, indent=2)
        self.start("Checking locator", task)

    def save(self):
        try:
            self.result = build_library(self.table.records())
        except ValueError as exc:
            messagebox.showerror("Invalid locator library", str(exc), parent=self)
            return
        self.close()

    def close(self):
        self.close_when_done = True
        if self.busy:
            self.show("Waiting for the current browser operation to finish before closing…")
        elif self.driver:
            def close_driver():
                from gradebook.browser import close_browser
                try:
                    close_browser(self.driver)
                finally:
                    self.driver = None
                return "Browser closed"
            self.start("Closing browser", close_driver)
        else:
            self.destroy()

    def poll(self):
        try:
            while True:
                operation, success, result = self.events.get_nowait()
                self.busy = False
                self.show(str(result))
                for button in self.buttons:
                    button.configure(state="normal")
                if self.close_when_done:
                    self.close()
                    if not self.winfo_exists():
                        return
        except queue.Empty:
            pass
        self.after_id = self.after(80, self.poll)

    def destroy(self):
        if getattr(self, "after_id", None):
            self.after_cancel(self.after_id)
        super().destroy()
