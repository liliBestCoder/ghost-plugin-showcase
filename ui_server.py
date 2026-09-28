"""The plugin's own page server -- what `uiUrl` points at
(spec-manifest.md §5, spec-plugin-api.md §8).

Ghost's plugins page shows it in an iframe named "ghost-plugin-<port>"; it can
also be opened in a browser tab. Either way it is served by THIS process on
127.0.0.1, and anything else running on this machine can connect to it too --
a local program, or a web page's fetch() to 127.0.0.1. So:

  * port 0: the system picks a free one (never hard-code; never 80 or 23551,
    which Ghost refuses as a uiUrl);
  * a random 128-bit path prefix, new every start, carried only by uiUrl: it
    is this server's credential. Without it, anyone local could read what
    this plugin reads from Ghost, and press its buttons;
  * the Host header must be exactly 127.0.0.1:<port> -- DNS rebinding: a page
    that points its own name at 127.0.0.1 still sends its own name in Host;
  * a POST must carry this page's own Origin (browsers always send one on a
    fetch POST), so another page cannot press the buttons even if it learned
    the address;
  * a Content-Security-Policy with nothing external, and frame-ancestors
    naming exactly one origin -- Ghost's, derived from apiBase -- so no other
    page can frame this one;
  * request bodies are small and bounded; a slow client times out.

No part of a request path ever becomes part of a file path: the page's files
are served by NAME from a fixed table.
"""

import hmac
import http.server
import json
import os
import secrets
import urllib.parse

from ghost_api import parse_json

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UI_FILES = {
    "": ("index.html", "text/html; charset=utf-8"),
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "app.css": ("app.css", "text/css; charset=utf-8"),
}
MAX_BODY_BYTES = 4096
REQUEST_TIMEOUT_SEC = 10
REFUSED_PORTS = (80, 23551)       # IsLoopbackUiUrl refuses both (spec-host-protocol §4)


def csp(frame_ancestor):
    return ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors " + frame_ancestor)


def make_handler(get_routes, post_routes, prefix, port_box, frame_ancestor):
    """get_routes: {"api/x": fn() -> (code, body bytes, content type)}
    post_routes: {"api/y": fn(body dict) -> the same}."""

    policy = csp(frame_ancestor)

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "GhostShowcase/1.0"
        sys_version = ""
        timeout = REQUEST_TIMEOUT_SEC          # a client that stops sending is dropped

        def log_message(self, fmt, *args):     # silent: requests are not logged anywhere
            pass

        def send_body(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            self.wfile.write(body)

        def refuse(self, code, error):
            self.send_body(code, json.dumps({"error": error}).encode("ascii"), "application/json")

        def own_origin(self):
            return "http://127.0.0.1:%d" % port_box[0]

        def route(self):
            """The path under the prefix, or None (already answered)."""
            if self.headers.get("Host") != "127.0.0.1:%d" % port_box[0]:
                self.refuse(403, "bad_host")
                return None
            # "/<prefix>/<rest>" or nothing. compare_digest on BYTES: on str it
            # raises for any non-ASCII character, and it takes the same time
            # whichever character is wrong.
            parts = urllib.parse.urlsplit(self.path).path.split("/", 2)
            if len(parts) != 3 or parts[0] != "" or \
                    not hmac.compare_digest(parts[1].encode("utf-8", "surrogatepass"), prefix.encode("ascii")):
                self.refuse(404, "not_found")
                return None
            return parts[2]

        def answer(self, result):
            code, body, ctype = result
            self.send_body(code, body, ctype)

        def do_GET(self):
            rest = self.route()
            if rest is None:
                return
            if rest in UI_FILES:
                name, ctype = UI_FILES[rest]
                with open(os.path.join(UI_DIR, name), "rb") as f:
                    self.send_body(200, f.read(), ctype)
            elif rest in get_routes:
                self.answer(get_routes[rest]())
            else:
                self.refuse(404, "not_found")

        def do_POST(self):
            rest = self.route()
            if rest is None:
                return
            if self.headers.get("Origin") != self.own_origin():
                self.refuse(403, "bad_origin")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self.refuse(413 if length > 0 else 400, "bad_length")
                return
            raw = self.rfile.read(length) if length else b"{}"
            body = parse_json(raw, MAX_BODY_BYTES)
            if not isinstance(body, dict):
                self.refuse(400, "bad_json")
            elif rest in post_routes:
                self.answer(post_routes[rest](body))
            else:
                self.refuse(404, "not_found")

    return Handler


class UiServer:
    """uiUrl is http://127.0.0.1:<port>/<prefix>/ -- the trailing slash is
    part of it: the page uses relative paths ("api/status"), which resolve
    under the prefix."""

    def __init__(self, get_routes, post_routes, frame_ancestor):
        self.prefix = secrets.token_hex(16)          # 128 random bits
        port_box = [0]
        handler = make_handler(get_routes, post_routes, self.prefix, port_box, frame_ancestor)
        while True:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            if server.server_address[1] not in REFUSED_PORTS:
                break
            server.server_close()                    # practically never; cheap to be sure
        server.daemon_threads = True
        self.server = server
        self.port = port_box[0] = server.server_address[1]
        self.origin = "http://127.0.0.1:%d" % self.port
        self.url = "%s/%s/" % (self.origin, self.prefix)

    def serve(self):
        try:
            self.server.serve_forever(poll_interval=0.2)
        finally:
            self.server.server_close()

    def shutdown(self):
        self.server.shutdown()


def json_result(obj, code=200):
    """(code, body, content type) for a get/post route to return."""
    return code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
