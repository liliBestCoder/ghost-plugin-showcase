"""The ONE object that holds the plugin token and talks to Ghost
(docs/plugin-sdk/spec-plugin-api.md §1).

Rules this client follows -- copy them along with it:

  * The token goes in exactly one header, `X-Ghost-Plugin-Token`, to exactly
    one address, the handshake's apiBase (checked to be loopback). Never the
    session header of Ghost's own pages, which no plugin has. It is never put
    on a command line, in the environment, in a log line, in a file, or in
    anything this process serves to its page.
  * No `Origin` header: a native process has no page. Any Origin other than
    apiBase itself is a 401 -- including this plugin's own page's origin,
    which is why the page talks to this process and never to Ghost (§8).
  * Every request has a timeout, and every answer a size limit.
  * 429 `rate_limited` -- the per-plugin budget, 20 calls/s with a burst of
    100 (spec-limits.md §7.1) -- is retried with EXPONENTIAL BACKOFF, a few
    times, then given up. Retrying is safe even for a POST: the gate answers
    429 before the command runs, so nothing happened. Every request counts
    against the budget, a refused 403 included; 401s (no identity) do not.
  * 401 and 403 are answers, not failures to retry: the same request will get
    the same answer.

This file is meant to be copied into your plugin unchanged. (The showcase's
two deliberate 401s do not go through it: sections.py builds those wrong
requests by hand, so that nothing here can ever send one.)
"""

import http.client
import json
import threading
import time

PLUGIN_HEADER = "X-Ghost-Plugin-Token"

REQUEST_TIMEOUT_SEC = 10
# /process-stats carries base64 icons, so the cap is generous; it still means a
# misbehaving answer cannot make this process hold an unbounded amount.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# Four retries after the first 429: 0.25 + 0.5 + 1 + 2 = 3.75 s at most. The
# budget refills continuously (20 per second), so a short pause is enough.
RETRY_DELAYS_SEC = (0.25, 0.5, 1.0, 2.0)


def parse_json(raw, limit=MAX_RESPONSE_BYTES):
    """The JSON value in `raw` (bytes), or None -- never an exception.

    A safe parse: bounded in size, strict UTF-8, and no NaN/Infinity (which
    Python's json accepts by default and JSON does not have)."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > limit:
        return None
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_refuse)
    except (ValueError, RecursionError):
        return None


def _refuse(name):
    raise ValueError(name)


class Reply:
    """One answer: HTTP status (0 = no answer at all), body bytes, type."""

    __slots__ = ("status", "body", "ctype")

    def __init__(self, status, body=b"", ctype=""):
        self.status, self.body, self.ctype = status, body, ctype

    def json(self):
        return parse_json(self.body)


class GhostClient:
    """`host`, `port`: the handshake's apiBase, already checked to be
    127.0.0.1 (protocol.split_api_base). `sleep` is a parameter so the tests
    can see the backoff without waiting for it."""

    def __init__(self, host, port, token, sleep=time.sleep):
        self._host, self._port = host, port
        self._token = token
        self._sleep = sleep
        self._lock = threading.Lock()
        # What the page may see about the client: counts, never the token.
        self.stats = {"calls": 0, "rateLimited": 0, "retries": 0, "gaveUp": 0}

    @property
    def api_base(self):
        return "http://%s:%d" % (self._host, self._port)

    def _count(self, key, n=1):
        with self._lock:
            self.stats[key] += n

    def counters(self):
        with self._lock:
            return dict(self.stats)

    def _once(self, method, path, body, headers):
        self._count("calls")
        conn = http.client.HTTPConnection(self._host, self._port, timeout=REQUEST_TIMEOUT_SEC)
        try:
            conn.request(method, path, body, headers)
            resp = conn.getresponse()
            data = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                return Reply(0, b"", "")          # too large: treated as no answer
            return Reply(resp.status, data, resp.getheader("Content-Type", ""))
        except (OSError, http.client.HTTPException, ValueError):
            return Reply(0)
        finally:
            conn.close()

    def request(self, method, path, body=None, content_type=None):
        """One call to Ghost, retried on 429 with exponential backoff."""
        headers = {PLUGIN_HEADER: self._token}
        if content_type:
            headers["Content-Type"] = content_type
        reply = self._once(method, path, body, headers)
        for delay in RETRY_DELAYS_SEC:
            if reply.status != 429:
                return reply
            self._count("rateLimited")
            self._count("retries")
            self._sleep(delay)
            reply = self._once(method, path, body, headers)
        if reply.status == 429:
            self._count("rateLimited")
            self._count("gaveUp")
        return reply

    def get_json(self, path):
        """(status, parsed JSON or None)."""
        reply = self.request("GET", path)
        return reply.status, reply.json()

    def post_json(self, path, obj):
        body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        reply = self.request("POST", path, body, "application/json")
        return reply.status, reply.json()

    def open_events(self, after, timeout):
        """(connection, response) for GET /events -- the caller reads the
        stream and closes the connection. `after`: the last id seen, so a
        reconnect resumes instead of starting from "now" (spec-plugin-api §3).
        Opening a stream costs one call of the budget, like any request."""
        self._count("calls")
        path = "/events" if after is None else "/events?after=%d" % after
        conn = http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        conn.request("GET", path, headers={PLUGIN_HEADER: self._token, "Accept": "text/event-stream"})
        return conn, conn.getresponse()
