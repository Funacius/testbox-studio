"""Local sample website for editable browser tests; no Docker or Moodle required."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Testbox Studio demo</title><style>
body{background:#202020;color:#eee;font:17px system-ui;max-width:600px;margin:70px auto}
input,button{display:block;margin:12px 0;padding:10px;font:inherit}
button{background:#4772b3;color:white;border:0;cursor:pointer}#message{min-height:30px}
</style><h1>Testbox Studio demo</h1><p>Local automation fixture. Demo credentials: demo / demo123.</p>
<form id="form"><label>Username<input id="username" autocomplete="off"></label>
<label>Password<input id="password" type="password" autocomplete="off"></label>
<button id="login" type="submit">Sign in</button></form><p id="message"></p>
<script>document.getElementById('form').addEventListener('submit',e=>{e.preventDefault();
const ok=document.getElementById('username').value==='demo'&&document.getElementById('password').value==='demo123';
document.getElementById('message').textContent=ok?'Welcome demo':'Invalid credentials';});</script></html>'''


class DemoHandler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            # Browser shutdown may close an idle preconnection.
            pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9542)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"Testbox demo ready: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
