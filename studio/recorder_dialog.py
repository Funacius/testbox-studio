"""Reviewable browser recording and element picking in an owned Chrome profile."""

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from automation.recording import RecorderSession, RecordingBuffer
from automation.schema import VARIABLE_NAME, new_step, locator
from studio.theme import PANEL, dark_text


class RecorderDialog(tk.Toplevel):
    def __init__(self, parent, settings, occupied=(), can_append=False):
        super().__init__(parent)
        self.withdraw()
        self.title("Browser recorder and element picker")
        self.configure(bg=PANEL)
        self.transient(parent)
        self.geometry("1140x850")
        self.minsize(1000, 740)
        self.result, self.applying, self.closing = None, False, False
        self.buffer = RecordingBuffer(occupied)
        self.locators, self.existing_locators = {}, dict(settings.get("locators", {}))
        self.tasks, self.events = queue.Queue(), queue.Queue()
        self.settings = settings
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Browser recorder and element picker", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Open a temporary Chrome browser, then record your interactions or pick an element. Review the steps before applying.\nRecords the current tab's top document. Add frame/tab steps manually for embedded content or new tabs. Use Open URL to record manual navigation.",
            style="Muted.TLabel", wraplength=1100).pack(anchor="w", pady=(6, 12))
        top = ttk.Frame(body)
        top.pack(fill="x")
        self.url = tk.StringVar(self, settings.get("base_url", ""))
        ttk.Entry(top, textvariable=self.url).pack(side="left", fill="x", expand=True)
        self.buttons = []
        for text, callback in (("Open URL", lambda: self.enqueue("open", self.url.get().strip())),
                               ("● Record", lambda: self.enqueue("mode", "record")),
                               ("Pause recording", lambda: self.enqueue("mode", "idle")),
                               ("Pick element", lambda: self.enqueue("mode", "pick"))):
            button = ttk.Button(top, text=text, command=callback)
            button.pack(side="left", padx=(6, 0))
            self.buttons.append(button)
        alert = ttk.Frame(body)
        alert.pack(fill="x", pady=8)
        self.prompt = tk.StringVar(self)
        ttk.Label(alert, text="Prompt text (optional)").pack(side="left")
        ttk.Entry(alert, textvariable=self.prompt, width=24).pack(side="left", padx=8)
        for name, command in (("Accept alert", "accept_alert"), ("Dismiss alert", "dismiss_alert")):
            button = ttk.Button(alert, text=name, command=lambda c=command: self.enqueue("alert", c, self.prompt.get()))
            button.pack(side="left", padx=5)
            self.buttons.append(button)
        self.status = tk.StringVar(self, "No browser opened. Only Open URL starts the recorder browser.")
        ttk.Label(body, textvariable=self.status, style="Muted.TLabel", wraplength=1100).pack(anchor="w", pady=6)
        pick = ttk.LabelFrame(body, text="Picked element / add a step", padding=10)
        pick.pack(fill="x", pady=(5, 10))
        self.target, self.alias = tk.StringVar(self), tk.StringVar(self)
        self.target_box = ttk.Combobox(pick, textvariable=self.target)
        self.target_box.grid(row=0, column=0, columnspan=3, sticky="ew", padx=(0, 8))
        ttk.Entry(pick, textvariable=self.alias, width=16).grid(row=0, column=3, sticky="ew")
        ttk.Button(pick, text="Save locator alias", command=self.save_alias).grid(row=0, column=4, padx=(8, 0))
        self.command = tk.StringVar(self, "assert_visible")
        ttk.Combobox(pick, textvariable=self.command, values=("assert_visible", "assert_text", "assert_value", "assert_contains", "click", "type", "check", "frame", "wait_visible"),
            state="readonly", width=18).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.value, self.expected = tk.StringVar(self), tk.StringVar(self)
        ttk.Entry(pick, textvariable=self.value).grid(row=1, column=1, sticky="ew", padx=8, pady=(10, 0))
        ttk.Entry(pick, textvariable=self.expected).grid(row=1, column=2, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(pick, text="Add step", command=self.add_step).grid(row=1, column=4, padx=(8, 0), pady=(10, 0))
        ttk.Label(pick, text="Action                          Value (input)                               Expected (from your requirement; not automatically copied)", style="Muted.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", pady=5)
        for index in (1, 2):
            pick.columnconfigure(index, weight=1)
        self.picked = dark_text(pick, height=2)
        self.picked.grid(row=3, column=0, columnspan=5, sticky="ew")
        self.picked.configure(state="disabled")
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x")
        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True)
        self.steps = ttk.Treeview(frame, columns=("index", "command", "target", "value", "expected"), show="headings", selectmode="browse", height=8)
        for name, label, width in (("index", "#", 40), ("command", "ACTION", 140), ("target", "TARGET", 300), ("value", "VALUE", 230), ("expected", "EXPECTED", 250)):
            self.steps.heading(name, text=label)
            self.steps.column(name, width=width, minwidth=35)
        self.steps.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.steps.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        self.steps.configure(yscrollcommand=vertical.set)
        scroll = ttk.Scrollbar(frame, orient="horizontal", command=self.steps.xview)
        scroll.grid(row=1, column=0, sticky="ew")
        self.steps.configure(xscrollcommand=scroll.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        controls = ttk.Frame(footer)
        controls.pack(fill="x", pady=10)
        ttk.Button(controls, text="Delete selected step", command=self.delete_step).pack(side="left")
        self.destination = tk.StringVar(self, "New case")
        ttk.Combobox(controls, textvariable=self.destination, values=("New case", "Append to selected case") if can_append else ("New case",),
            state="readonly", width=24).pack(side="right")
        ttk.Label(footer, text="Typed text becomes editable case variables. Password fields use ${password}; fill Run configuration or dataset.\nFile chooser paths use ${upload_file}. Review disabled notes and add expected assertions before Run.", style="Muted.TLabel", wraplength=1100).pack(anchor="w")
        bottom = ttk.Frame(footer)
        bottom.pack(fill="x", pady=(14, 0))
        ttk.Button(bottom, text="Cancel and close browser", command=self.cancel).pack(side="right")
        self.apply_button = ttk.Button(bottom, text="Apply recorded steps", style="Primary.TButton", command=self.apply)
        self.apply_button.pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.after_id = self.after(80, self.poll)
        threading.Thread(target=self.worker, daemon=True).start()
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def enqueue(self, name, *args):
        if not self.closing:
            self.status.set("Recorder operation: " + name)
            self.tasks.put((name, args))

    def worker(self):
        session = None
        last_error = None
        def collect():
            for event in session.poll():
                self.events.put(("browser", event))
        try:
            session = RecorderSession(self.settings)
            while True:
                try:
                    name, args = self.tasks.get(timeout=.2)
                except queue.Empty:
                    name, args = "poll", ()
                try:
                    manual = None
                    if name == "open":
                        manual = session.open(*args)
                    elif name == "mode":
                        session.set_mode(*args)
                    elif name == "alert":
                        if not session.driver:
                            raise ValueError("Open a recorder browser first")
                        command, text = args
                        alert = session.driver.switch_to.alert
                        if command == "accept_alert" and text:
                            alert.send_keys(text)
                        alert.accept() if command == "accept_alert" else alert.dismiss()
                        manual = new_step(command, value=text if command == "accept_alert" else "")
                    elif name in {"finish", "close"}:
                        if session.driver:
                            try:
                                session.set_mode("idle")
                                collect()
                            except Exception as exc:
                                if name == "finish":
                                    self.events.put(("browser", dict(event="warning", message="Recording ended with an incomplete browser state: " + type(exc).__name__)))
                        session.close()
                        self.events.put(("closed", None))
                        break
                    collect()
                    if manual:
                        self.events.put(("manual", manual))
                    if name != "poll":
                        self.events.put(("status", "Browser ready · " + session.mode + " mode"))
                    last_error = None
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    if message != last_error:
                        self.events.put(("error", message))
                    last_error = message
                    if name in {"finish", "close"}:
                        self.events.put(("closed", None))
                        break
        except Exception as exc:
            self.events.put(("error", f"Recorder could not start: {exc}"))
            self.events.put(("closed", None))
        finally:
            try:
                if session:
                    session.close()
            except Exception:
                pass

    def refresh(self):
        self.steps.delete(*self.steps.get_children())
        for index, step in enumerate(self.buffer.steps):
            self.steps.insert("", "end", iid=str(index), values=(index + 1, step["command"], step["target"], step["value"], step["expected"]))
        if self.buffer.steps:
            self.steps.see(str(len(self.buffer.steps) - 1))

    def poll(self):
        try:
            while True:
                kind, event = self.events.get_nowait()
                if kind == "browser":
                    if event.get("event") == "picked":
                        self.target_box.configure(values=event.get("targets", []))
                        self.target.set(next(iter(event.get("targets", [])), ""))
                        self.picked.configure(state="normal")
                        self.picked.delete("1.0", "end")
                        self.picked.insert("1.0", json.dumps(event, ensure_ascii=False))
                        self.picked.configure(state="disabled")
                        self.status.set("Element picked without activating it. Choose an action/expected value and Add step.")
                    elif event.get("event") == "document":
                        self.status.set("Current document: " + event.get("url", ""))
                    else:
                        self.buffer.ingest(event)
                        self.refresh()
                elif kind == "manual":
                    self.buffer.add(event)
                    self.refresh()
                elif kind in {"status", "error"}:
                    self.status.set(str(event))
                elif kind == "closed":
                    if self.applying:
                        self.result = dict(steps=self.buffer.steps, variables=self.buffer.variables,
                            locators=self.locators, destination=self.destination.get())
                    self.destroy()
                    return
        except queue.Empty:
            pass
        except (ValueError, TypeError, KeyError) as exc:
            self.status.set("Review recording: " + str(exc))
        self.after_id = self.after(80, self.poll)

    def save_alias(self):
        try:
            name, target = self.alias.get().strip(), self.target.get()
            if not VARIABLE_NAME.fullmatch(name):
                raise ValueError("Enter an alias name using letters, digits, _, . or -")
            if target.startswith("@"):
                raise ValueError("Choose a raw locator candidate before saving an alias")
            candidate = locator(target, {})
            library = {**self.existing_locators, **self.locators}
            if name in library and locator("@" + name, library) != candidate:
                raise ValueError("That alias already has a different locator; choose another name")
            self.locators[name] = target
            self.target.set("@" + name)
        except ValueError as exc:
            messagebox.showerror("Locator alias", str(exc), parent=self)

    def add_step(self):
        try:
            target = self.target.get()
            locator(target, {**self.existing_locators, **self.locators})
            self.buffer.add(new_step(self.command.get(), target=target, value=self.value.get(), expected=self.expected.get()))
            self.refresh()
        except ValueError as exc:
            messagebox.showerror("Cannot add step", str(exc), parent=self)

    def delete_step(self):
        selected = self.steps.selection()
        if selected:
            self.buffer.steps.pop(int(selected[0]))
            self.buffer.last_input = None
            self.refresh()

    def apply(self):
        if self.closing:
            return
        self.applying = True
        self.finish("finish")

    def cancel(self):
        if not self.closing:
            self.finish("close")

    def finish(self, action):
        self.closing = True
        for button in self.buttons + [self.apply_button]:
            button.configure(state="disabled")
        self.status.set("Finishing the current browser operation and closing the owned browser…")
        self.tasks.put((action, ()))

    def destroy(self):
        if getattr(self, "after_id", None):
            self.after_cancel(self.after_id)
        super().destroy()
