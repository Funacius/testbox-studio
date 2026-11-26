"""Cancelable read/validation jobs that keep Tk's event loop responsive."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from studio.theme import PANEL, RED

CSV_ENCODINGS = ("auto", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "cp1252", "cp1258")


class BackgroundTask(tk.Toplevel):
    def __init__(self, parent, title, task, *, encoding=None):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=PANEL)
        self.transient(parent)
        self.geometry("640x320")
        self.minsize(600, 300)
        self.result, self.error, self.busy = None, None, False
        self.task, self.events = task, queue.Queue()
        self.cancelled = threading.Event()
        self.encoding = tk.StringVar(self, encoding or "auto")
        self.allow_retry = encoding is not None
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="Title.TLabel").pack(anchor="w")
        self.message = ttk.Label(body, text="Reading/validating in the background. Cancel leaves the workspace unchanged.", wraplength=590, style="Muted.TLabel")
        self.message.pack(anchor="w", fill="both", expand=True, pady=12)
        if self.allow_retry:
            row = ttk.Frame(body)
            row.pack(fill="x", before=self.message)
            ttk.Label(row, text="CSV encoding").pack(side="left")
            self.encoding_box = ttk.Combobox(row, textvariable=self.encoding, values=CSV_ENCODINGS, state="readonly", width=18)
            self.encoding_box.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(side="bottom", fill="x", pady=10, before=self.message)
        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", fill="x", before=self.progress)
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.destroy)
        self.cancel_button.pack(side="right")
        self.retry = ttk.Button(buttons, text="Read / Retry", command=self.start)
        self.retry.pack(side="right", padx=8)
        self.after_id = self.after(50, self.poll)
        self.after(0, self.start)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def start(self):
        if self.busy:
            return
        self.busy = True
        self.error = None
        self.retry.configure(state="disabled")
        self.message.configure(text="Reading/validating in the background…", foreground="")
        self.progress.start(15)
        encoding = self.encoding.get()
        def work():
            try:
                self.events.put((self.task(self.cancelled, encoding), None))
            except Exception as exc:
                self.events.put((None, exc))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            result, error = self.events.get_nowait()
            self.busy = False
            self.progress.stop()
            if error and self.allow_retry:
                self.message.configure(text=f"{error}\nChoose the file's encoding and Read / Retry, or Cancel.", foreground=RED)
                self.retry.configure(state="normal")
            else:
                self.result, self.error = result, error
                self.destroy()
                return
        except queue.Empty:
            pass
        self.after_id = self.after(50, self.poll)

    def destroy(self):
        self.cancelled.set()
        try:
            self.progress.stop()
            if getattr(self, "after_id", None):
                self.after_cancel(self.after_id)
        except tk.TclError:
            pass
        try:
            super().destroy()
        except tk.TclError:
            pass
