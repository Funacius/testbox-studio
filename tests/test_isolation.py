"""Browser reuse must discard state belonging to every visited origin."""

import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automation.isolation import origin


class IsolationTests(unittest.TestCase):
    def test_origin_drops_credentials_paths_and_default_ports(self):
        self.assertEqual(origin("https://user:private@example.test:443/path?q=private"), "https://example.test")
        self.assertEqual(origin("http://[::1]:9000/a"), "http://[::1]:9000")
        self.assertIsNone(origin("about:blank"))


class Handler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<!doctype html><title>Isolation fixture</title><body>ready</body>")
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get("TESTBOX_BROWSER_TESTS") == "1", "Set TESTBOX_BROWSER_TESTS=1 for actual browser isolation checks")
class IsolationBrowserTests(unittest.TestCase):
    def test_same_chrome_and_edge_session_resets_two_origins_and_preserves_viewport(self):
        from automation.isolation import owned_reused_browser
        from gradebook.browser import close_browser
        servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for thread in threads:
            thread.start()
        urls = [f"http://127.0.0.1:{servers[0].server_port}", f"http://localhost:{servers[1].server_port}"]
        try:
            for browser in ("chrome", "edge"):
                with self.subTest(browser=browser):
                    drivers = {}
                    driver = owned_reused_browser(drivers, browser, {"window": [1440, 900]}, True)
                    try:
                        for url in urls:
                            driver.get(url)
                            result = driver.execute_async_script('''const done=arguments[0];
                                localStorage.setItem('marker','old');sessionStorage.setItem('marker','old');document.cookie='marker=old;path=/';
                                const req=indexedDB.open('testbox-isolation',1);
                                req.onupgradeneeded=()=>req.result.createObjectStore('items');
                                req.onerror=()=>done('DB error');req.onsuccess=()=>{const db=req.result,tx=db.transaction('items','readwrite');
                                tx.objectStore('items').put('old','marker');tx.oncomplete=()=>{db.close();
                                caches.open('testbox-isolation').then(c=>c.put('/cached',new Response('old'))).then(()=>done('stored')).catch(e=>done(String(e)));};};''')
                            self.assertEqual(result, "stored")
                        previous = driver
                        previous_handle = driver.current_window_handle
                        driver = owned_reused_browser(drivers, browser, {"window": [1440, 900]}, True)
                        self.assertIs(driver, previous)
                        self.assertNotEqual(driver.current_window_handle, previous_handle)
                        self.assertIn("reused process", driver._testbox_isolation)
                        self.assertEqual(len(driver.window_handles), 1)
                        self.assertEqual(driver.execute_script("return [innerWidth,innerHeight]"), [1440, 900])
                        for url in urls:
                            driver.get(url)
                            state = driver.execute_async_script('''const done=arguments[0];Promise.all([indexedDB.databases(),caches.keys()])
                                .then(([db,cache])=>done({local:localStorage.getItem('marker'),session:sessionStorage.getItem('marker'),cookies:document.cookie,db:db.length,cache:cache.length}))
                                .catch(e=>done({error:String(e)}));''')
                            self.assertEqual(state, {"local": None, "session": None, "cookies": "", "db": 0, "cache": 0})
                    finally:
                        close_browser(driver)
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join()
