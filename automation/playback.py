"""Versioned file-based playback control shared by the GUI and its child runner."""

import json
import os
import tempfile
import time
from pathlib import Path


class ExecutionStopped(Exception):
    """Explicit interruption; cleanup must still run."""


def write_control(path: Path, command: str, sequence: int):
    if command not in {"run", "pause", "next", "stop"} or type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid playback command or sequence")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".control.json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(dict(command=command, sequence=sequence), stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class PlaybackController:
    def __init__(self, path, on_event=None, stop_file=None):
        self.path = Path(path)
        self.on_event = on_event or (lambda event, **values: None)
        self.stop_file = Path(stop_file) if stop_file else None
        self.sequence = -1
        self.paused, self.pause_next, self.stopped = False, False, False
        self.pause_seconds = 0
        if not self.path.exists():
            write_control(self.path, "run", 0)

    def command(self):
        if self.stopped:
            raise ExecutionStopped("Stopped by user; cleanup will run")
        if self.stop_file and self.stop_file.exists():
            self.stopped = True
            raise ExecutionStopped("Stopped by user; cleanup will run")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.stopped = True
            raise RuntimeError("Playback control file is unavailable or invalid") from exc
        if value.get("command") not in {"run", "pause", "next", "stop"} or type(value.get("sequence")) is not int or value["sequence"] < 0:
            self.stopped = True
            raise RuntimeError("Playback command is invalid")
        if value["sequence"] <= self.sequence:
            return
        self.sequence = value["sequence"]
        command = value["command"]
        if command == "stop":
            self.stopped = True
            raise ExecutionStopped("Stopped by user; cleanup will run")
        self.paused = command == "pause"
        self.pause_next = command == "next"

    def before_step(self, step, **context):
        if self.pause_next:
            self.paused, self.pause_next = True, False
        self.command()
        if step.get("breakpoint"):
            self.paused = True
        if not self.paused:
            return
        values = dict(step_id=step["id"], command=step["command"], phase=step["phase"], **context)
        self.on_event("playback", state="paused", message="Paused before " + step["command"], **values)
        began = time.perf_counter()
        try:
            while self.paused:
                time.sleep(.05)
                self.command()
        finally:
            self.pause_seconds += time.perf_counter() - began
        self.on_event("playback", state="running", message="Resumed", **values)
