import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path

from automation.playback import ExecutionStopped, PlaybackController, write_control
from automation.schema import new_step


class PlaybackTests(unittest.TestCase):
    def test_pause_single_step_resume_breakpoint_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.json"
            write_control(path, "pause", 0)
            events, finished = queue.Queue(), queue.Queue()
            controller = PlaybackController(path, lambda event, **values: events.put(values))
            def call(step):
                def worker():
                    try:
                        controller.before_step(step)
                        finished.put("completed")
                    except Exception as exc:
                        finished.put(exc)
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                return thread
            first = call(new_step("click", target="id=first"))
            self.assertEqual(events.get(timeout=2)["state"], "paused")
            self.assertTrue(finished.empty())
            write_control(path, "next", 1)
            self.assertEqual(finished.get(timeout=2), "completed")
            self.assertEqual(events.get(timeout=2)["state"], "running")
            first.join(2)
            second = call(new_step("click", target="id=second"))
            self.assertEqual(events.get(timeout=2)["state"], "paused")
            self.assertTrue(finished.empty())
            write_control(path, "run", 2)
            self.assertEqual(finished.get(timeout=2), "completed")
            self.assertEqual(events.get(timeout=2)["state"], "running")
            second.join(2)
            third = call(new_step("click", target="id=third", breakpoint=True))
            self.assertEqual(events.get(timeout=2)["state"], "paused")
            write_control(path, "stop", 3)
            self.assertIsInstance(finished.get(timeout=2), ExecutionStopped)
            third.join(2)
            self.assertTrue(controller.stopped)
            self.assertGreater(controller.pause_seconds, 0)
            with self.assertRaises(ExecutionStopped):
                controller.command()

    def test_missing_and_invalid_control_are_errors_instead_of_silent_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.json"
            controller = PlaybackController(path)
            path.write_text('{"command":"run","sequence":-1}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                controller.command()
            controller = PlaybackController(path)
            path.unlink()
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                controller.command()

    def test_stop_file_is_respected_before_next_action(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            controller = PlaybackController(path / "control.json", stop_file=path / "stop.request")
            (path / "stop.request").write_text("stop", encoding="utf-8")
            with self.assertRaises(ExecutionStopped):
                controller.before_step(new_step("open", target="http://example.test"))
