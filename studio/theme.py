"""Blender-inspired neutral charcoal palette for native Tk/ttk widgets."""

import tkinter as tk
from tkinter import ttk

BG = "#202020"
PANEL = "#303030"
SURFACE = "#3d3d3d"
FIELD = "#242424"
BORDER = "#191919"
TEXT = "#e3e3e3"
MUTED = "#aaaaaa"
ACCENT = "#ea8a23"
SELECT = "#3c5d7c"
GREEN = "#9ac77b"
RED = "#e58b8b"
YELLOW = "#e5b76a"
BLUE = "#4772b3"


def apply_theme(root):
    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANEL, foreground=TEXT, bordercolor=BORDER, font=("Segoe UI", 10),
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=BG)
    style.configure("TFrame", background=PANEL)
    style.configure("TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
    style.configure("Section.TLabel", foreground=MUTED, font=("Segoe UI Semibold", 9))
    style.configure("TButton", background=SURFACE, foreground=TEXT, padding=(12, 7),
                    borderwidth=1, focusthickness=0)
    style.map("TButton", background=[("active", "#505050"), ("disabled", PANEL)],
              foreground=[("disabled", "#707070")])
    style.configure("Primary.TButton", background=BLUE, foreground="#ffffff", font=("Segoe UI Semibold", 10))
    style.map("Primary.TButton", background=[("active", "#5984c3"), ("disabled", "#3b4657")])
    style.configure("Danger.TButton", foreground=RED)
    style.configure("Small.TButton", padding=(8, 4), font=("Segoe UI", 9))
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, padding=7,
                    insertcolor=TEXT, bordercolor=BORDER)
    style.map("TEntry", fieldbackground=[("disabled", PANEL)], foreground=[("disabled", MUTED)])
    style.configure("TSpinbox", fieldbackground=FIELD, background=SURFACE, foreground=TEXT,
                    insertcolor=TEXT, padding=6, arrowcolor=MUTED, bordercolor=BORDER)
    style.map("TSpinbox", fieldbackground=[("disabled", PANEL)], foreground=[("disabled", MUTED)])
    style.configure("TCombobox", fieldbackground=FIELD, background=SURFACE, foreground=TEXT,
                    padding=6, arrowcolor=MUTED)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], selectbackground=[("readonly", FIELD)],
              selectforeground=[("readonly", TEXT)], foreground=[("readonly", TEXT)])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=31, borderwidth=0, indent=18)
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=SURFACE, foreground=MUTED, relief="flat",
                    font=("Segoe UI Semibold", 9), padding=(8, 9))
    style.map("Treeview.Heading", background=[("active", "#494949")])
    style.configure("TNotebook", background=PANEL, borderwidth=0, tabmargins=(0, 0, 0, 9))
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(17, 10))
    style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", TEXT)])
    style.configure("TPanedwindow", background=BG)
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background="#737373", troughcolor=FIELD, arrowcolor=TEXT,
                        bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD,
                        borderwidth=0, arrowsize=14, width=14, gripcount=0)
        # Clam inherits a white active background unless explicitly mapped.
        style.map(name, background=[("disabled", SURFACE), ("pressed", "#aaaaaa"), ("active", "#929292")],
                  arrowcolor=[("disabled", MUTED), ("active", "#ffffff")])
    style.configure("TProgressbar", background=ACCENT, troughcolor=FIELD, borderwidth=0)
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
    style.map("TCheckbutton", background=[("active", PANEL)])
    style.configure("TSeparator", background=BORDER)


def dark_text(parent, **kwargs):
    kwargs.setdefault("width", 1)
    kwargs.setdefault("height", 8)
    return tk.Text(parent, bg=FIELD, fg=TEXT, insertbackground=TEXT,
                   selectbackground=SELECT, selectforeground=TEXT,
                   relief="flat", borderwidth=0, padx=12, pady=10,
                   font=("Cascadia Code", 10), undo=True, wrap="word", **kwargs)


def dark_menu(parent):
    return tk.Menu(parent, tearoff=False, bg=SURFACE, fg=TEXT,
                   activebackground=SELECT, activeforeground=TEXT,
                   relief="flat", borderwidth=1, font=("Segoe UI", 10))
