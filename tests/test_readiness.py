import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automation.readiness import checked_settings, website_status


class Handler(BaseHTTPRequestHandler):
    status = 200
    requested = []
    def do_GET(self):
        type(self).requested.append(self.path)
        self.send_response(type(self).status)
        self.end_headers()
    def log_message(self, *args):
        pass


class ReadinessTests(unittest.TestCase):
    def test_connection_probe_uses_origin_not_the_test_action_path(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/delete?id=1"
            for status in (200, 401, 403, 404):
                Handler.status = status
                self.assertIn(f"HTTP {status}", website_status(url))
            self.assertTrue(all(path == "/" for path in Handler.requested))
            Handler.status = 503
            with self.assertRaisesRegex(ValueError, "HTTP 503"):
                website_status(url)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_connection_refusal_has_actionable_message(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            with self.assertRaisesRegex(ValueError, "Start the local website/service"):
                website_status(f"http://127.0.0.1:{reserved.getsockname()[1]}", timeout=.2)

    def test_invalid_runtime_settings_fail_before_browser_start(self):
        for settings in ({"window": [1, 900]}, {"window": [1440, "900"]}, {"slow_ms": float("nan")},
                         {"check_connection": "yes"}, {"locators": []}, {"environments": []}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                checked_settings(settings)


if __name__ == "__main__":
    unittest.main()
