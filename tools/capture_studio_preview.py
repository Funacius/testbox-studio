"""Capture only an owned Tk window on Windows, without activating it."""

import argparse
import ctypes
import json
import os
import struct
import tempfile
import time
import zlib
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def capture(window, path):
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    handle = ctypes.c_void_p
    user.GetParent.argtypes, user.GetParent.restype = [handle], handle
    user.GetWindowDC.argtypes, user.GetWindowDC.restype = [handle], handle
    user.GetWindowRect.argtypes = [handle, ctypes.POINTER(wintypes.RECT)]
    user.PrintWindow.argtypes = [handle, handle, wintypes.UINT]
    user.ShowWindow.argtypes = [handle, ctypes.c_int]
    user.SetWindowPos.argtypes = [handle, handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.ReleaseDC.argtypes = [handle, handle]
    for name in ("CreateCompatibleDC", "CreateCompatibleBitmap", "SelectObject"):
        getattr(gdi, name).restype = handle
    gdi.CreateCompatibleDC.argtypes = [handle]
    gdi.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    gdi.SelectObject.argtypes = [handle, handle]
    gdi.GetDIBits.argtypes = [handle, handle, wintypes.UINT, wintypes.UINT, handle, handle, wintypes.UINT]
    gdi.DeleteObject.argtypes, gdi.DeleteDC.argtypes = [handle], [handle]
    window.withdraw()
    window.update_idletasks()
    hwnd = user.GetParent(window.winfo_id()) or window.winfo_id()
    user.GetForegroundWindow.restype = handle
    foreground = user.GetForegroundWindow()
    user.GetWindowLongW.argtypes, user.GetWindowLongW.restype = [handle, ctypes.c_int], ctypes.c_long
    user.SetWindowLongW.argtypes = [handle, ctypes.c_int, ctypes.c_long]
    flags = user.GetWindowLongW(hwnd, -20)
    user.SetWindowLongW(hwnd, -20, flags | 0x08000000)
    window.tk.call("wm", "deiconify", window._w)
    # SW_SHOWNOACTIVATE, then HWND_BOTTOM + SWP_NOACTIVATE. Other windows are not captured.
    user.ShowWindow(hwnd, 4)
    rectangle = wintypes.RECT()
    user.GetWindowRect(hwnd, ctypes.byref(rectangle))
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    if width < 200 or height < 150:
        raise OSError("The owned window was not mapped at a usable size")
    user.SetWindowPos(hwnd, handle(1), 30, 30, width, height, 0x0010)
    time.sleep(.3)
    window.update()
    if hasattr(window, "vertical"):
        window._set_sashes(window.sidebar.master)
        window.update()
    window.update_idletasks()
    if hasattr(window, "vertical"):
        print("Layout:", {name: [widget.winfo_x(), widget.winfo_y(), widget.winfo_width(), widget.winfo_height(), widget.winfo_ismapped()]
                          for name, widget in (("vertical", window.vertical), ("horizontal", window.sidebar.master),
                                               ("sidebar", window.sidebar), ("center", window.center), ("inspector", window.inspector))})
    if foreground and user.GetForegroundWindow() != foreground:
        user.SetForegroundWindow.argtypes = [handle]
        user.SetForegroundWindow(foreground)
    user.GetWindowRect(hwnd, ctypes.byref(rectangle))
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    dc = user.GetWindowDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    previous = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 2):
            raise OSError("PrintWindow failed")
        gdi.SelectObject(memory, previous)
        info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        header = ctypes.create_string_buffer(info)
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi.GetDIBits(memory, bitmap, 0, height, buffer, header, 0):
            raise OSError("GetDIBits failed")
        raw = buffer.raw
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
        scanlines = b"".join(b"\x00" + rgb[row * width * 3:(row + 1) * width * 3] for row in range(height))
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        print(f"Captured owned window: {path} ({width} x {height})")
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)


def main():
    if os.name != "nt":
        raise SystemExit("This development preview helper is for Windows")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("steps", "locators", "report", "nfr", "templates", "recorder", "welcome", "flow"), default="steps")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/studio-steps-preview.png")
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(ROOT))
    from studio.app import Studio
    from studio.importing import map_dataset, map_steps, read_grids, suggest_mapping
    from studio.model import Workspace, folder, testcase
    grid = read_grids(ROOT / "examples/login-steps.csv")[0]["rows"]
    records, _ = map_steps(grid, 0, suggest_mapping(grid[0]))
    records[0]["dataset_json"] = json.dumps(map_dataset(read_grids(ROOT / "examples/login-data.csv")[0]["rows"], 0)[0])
    project = Workspace("Testbox Studio demo")
    parent = project.add(folder("Browser tests"))
    uid = project.add(testcase(records[0]), parent)
    project.settings = dict(base_url="http://127.0.0.1:9542", locators={"username": "id=username", "password": "id=password", "submit": "id=login", "message": "id=message"})
    if args.view == "welcome":
        project = Workspace("Untitled workspace")
    if args.view == "flow":
        from automation.schema import new_step
        record = project.find(uid)["record"]
        actions = json.loads(record["actions_json"])
        actions[1:1] = [new_step("repeat", target="iteration", value="3"),
            new_step("if_equal", target="${iteration}", expected="2"),
            new_step("note", description="Add conditional actions", enabled=False), new_step("end_if"), new_step("end_repeat")]
        record["actions_json"] = json.dumps(actions)
    with tempfile.TemporaryDirectory() as directory, patch("tkinter.Tk.deiconify"), patch("tkinter.Toplevel.deiconify"):
        path = Path(directory) / "preview.json"
        project.save(path)
        app = Studio(path)
        app.geometry("1600x950+30+30")
        if args.view != "welcome":
            app._show_node(uid)
        dialog = None
        try:
            if args.view not in {"steps", "welcome", "flow"}:
                capture(app, Path(directory) / "parent.png")
            if args.view == "locators":
                from studio.locator_library import LocatorLibraryDialog
                with patch("tkinter.Toplevel.wait_window"), patch("tkinter.Toplevel.grab_set"):
                    dialog = LocatorLibraryDialog(app, project.settings, "chrome")
                dialog.withdraw()
                capture(dialog, args.output)
            elif args.view == "nfr":
                from studio.nfr_dialog import NfrDialog
                steps = json.loads(records[0]["actions_json"])
                first = next(s["id"] for s in steps if s["command"] == "click")
                last = next(s["id"] for s in steps if s["command"] == "assert_text")
                config = dict(levels=[1, 2], browsers=["chrome", "edge"], repetitions=3,
                    measurements={records[0]["case_id"]: dict(start=first, end=last, maximum_seconds=2)})
                with patch("tkinter.Toplevel.wait_window"), patch("tkinter.Toplevel.grab_set"):
                    dialog = NfrDialog(app, records, config, records[0]["case_id"])
                dialog.withdraw()
                capture(dialog, args.output)
            elif args.view == "templates":
                from studio.templates import TemplateDialog
                with patch("tkinter.Toplevel.wait_window"), patch("tkinter.Toplevel.grab_set"):
                    dialog = TemplateDialog(app, {}, records[0])
                dialog.list.selection_set("2")
                dialog.show()
                capture(dialog, args.output)
            elif args.view == "recorder":
                from studio.recorder_dialog import RecorderDialog
                with patch("tkinter.Toplevel.wait_window"), patch("tkinter.Toplevel.grab_set"), patch("studio.recorder_dialog.threading.Thread.start"):
                    dialog = RecorderDialog(app, project.settings)
                dialog.buffer.steps = json.loads(records[0]["actions_json"])
                dialog.target.set("id=message")
                dialog.command.set("assert_text")
                dialog.expected.set("${expected_message}")
                dialog.status.set("Development preview — no browser opened. Recorded steps remain reviewable before applying.")
                dialog.refresh()
                capture(dialog, args.output)
            elif args.view == "report":
                from studio.report_viewer import ReportViewer
                if not args.report:
                    raise ValueError("Supply --report with a completed run's output folder")
                dialog = ReportViewer(app, args.report, lambda path: None)
                dialog.withdraw()
                capture(dialog, args.output)
            else:
                capture(app, args.output)
        finally:
            if dialog and dialog.winfo_exists():
                dialog.destroy()
            app.destroy()


if __name__ == "__main__":
    main()
