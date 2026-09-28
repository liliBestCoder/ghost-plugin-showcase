#!/usr/bin/env python3
"""The showcase's own tests. Standard library only, like the plugin.

Two layers:

  * Unit -- the modules imported directly: the handshake checks row by row,
    the safe JSON parse, the SSE reader's bounds, the event hub's planes and
    Data-plane cap (on a fake clock), the data-directory store (on a fake
    clock), the client's 429 backoff (with a recording sleep), and each
    section's relay rules against a stub client.
  * Process -- main.py as a real process, this file as its HOST (a named stop
    event, a clean environment with the GHOST_PLUGIN_* variables, the args the
    manifest names, one handshake line in, the first stdout line out,
    SetEvent to stop) and as GHOST's control interface (FakeGhost: every route
    the plugin uses, answered the way the real gate answers a plugin holding
    all six permissions; anything without the token in X-Ghost-Plugin-Token,
    or WITH an Origin, is a 401).

Windows only (the stop event is a named event): 77 elsewhere.
CTest: ghost_example_showcase_test.
"""

import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import http.client
import http.server

sys.dont_write_bytecode = True
TESTS = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(TESTS)
MAIN = os.path.join(PLUGIN, "main.py")
sys.path.insert(0, PLUGIN)

import events            # noqa: E402
import ghost_api         # noqa: E402
import protocol          # noqa: E402
import sections          # noqa: E402
import state_store       # noqa: E402

PLUGIN_ID = "com.ghostproxifier.showcase"
TOKEN = "{5A0C3E77-2B19-4D6F-9E21-C4B7A8D90F13}"
TOKEN_CORE = TOKEN.strip("{}").encode("ascii")
ALL_PERMS = ["events.read.control", "events.read.data", "stats.read", "config.read", "log.write", "plugin.assets"]
with open(os.path.join(PLUGIN, "manifest.json"), "rb") as _f:
    MANIFEST = json.loads(_f.read())
ICON = b"\x89PNG\r\n\x1a\n" + b"showcase-icon"

REDACTED_CONFIG = {
    "dns": {"doh": "https://dns.google/dns-query"},
    "settings": {"strictMode": True},
    "stunServers": [],
    "upstream": [
        {"id": "n1", "name": "Demo-HK", "type": "SOCKS5", "addr": "10.0.0.8:1080", "user": "***", "pass": "***"},
        {"id": "n2", "name": "办公室", "type": "HTTP", "addr": "10.0.0.9:8080", "user": "", "pass": ""},
        "not a node",
    ],
}
PROCESS_STATS = {
    "stats": [{"pid": 4242}, {"pid": 4343}],
    "groups": [
        {"id": "g1", "name": "notepad.exe", "path": "C:\\Windows\\notepad.exe", "alias": "Notes", "icon": "AAAA",
         "totalUp": 2048, "totalDown": 4096, "activeCount": 1, "nodeName": "Demo-HK",
         "children": [{"pid": 4242, "name": "notepad.exe", "up": 2048, "down": 4096, "icon": "BBBB"}]},
        # A Ghost that FORGOT to strip env: the plugin must report what arrived,
        # not what it hopes arrived.
        {"id": "g2", "name": "curl.exe", "path": "C:\\t\\curl.exe", "alias": "", "totalUp": 0, "totalDown": 0,
         "activeCount": 0, "children": [], "env": {"GHOST_PROXY_PASS": "leak"}},
        "not a group",
    ],
}
LATENCIES = {"test_timestamp": 1790553600, "is_testing": False, "avg_http_latency": 120, "retransmission_rate": 0.5,
             "nodes": {"n1": {"latency": 120, "success": 3, "attempts": 4, "udp": {"state": "usable"}},
                       "n2": {"latency": -1, "success": 0, "attempts": 2}, "bad": 7}}
THROUGHPUT = {"status": "ok", "history": [1, 2.5, "x", None, 4]}

k32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
if k32:
    from ctypes import wintypes
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]


def wait_until(pred, timeout, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def frame(seq, text, plane="control", level="info", src="ui", tag="Demo"):
    event = {"seq": seq, "ts": 1790553600000 + seq, "plane": plane, "level": level, "src": src, "pid": 0,
             "targetId": "", "tag": tag, "fields": {"k": "v"}, "text": text}
    return ("id: %d\ndata: %s\n\n" % (seq, json.dumps(event))).encode("utf-8")


# =====================================================================================
# Unit
# =====================================================================================

GOOD_HS = {"v": 1, "pluginId": PLUGIN_ID, "pluginDir": "C:\\p\\1.0.0", "dataDir": "C:\\p\\.data",
           "apiBase": "http://127.0.0.1:23551", "token": TOKEN, "permissions": ALL_PERMS, "settings": {},
           "license": {"licensed": False, "trial": False}, "lang": "zh",
           "stopEvent": "Local\\ShowcaseTest_stop"}


def hs_line(**changes):
    hs = dict(GOOD_HS)
    for k, v in changes.items():
        if v is KeyError:
            hs.pop(k, None)
        else:
            hs[k] = v
    return (json.dumps(hs) + "\n").encode("utf-8")


# Each row: label, the line, the reason it must be refused (a substring).
BAD_HANDSHAKES = [
    ("v 2", hs_line(v=2), "version"),
    ("v true", hs_line(v=True), "version"),
    ("v 1.0", hs_line(v=1.0), "version"),
    ("v '1'", hs_line(v="1"), "version"),
    ("no v", hs_line(v=KeyError), "version"),
    ("not an object", b"[1]\n", "version"),
    ("not JSON", b"hello\n", "not a JSON"),
    ("NaN", hs_line().replace(b'"settings": {}', b'"settings": NaN'), "not a JSON"),
    ("no newline (EOF / too long)", hs_line()[:-1], "missing or too long"),
    ("empty (EOF)", b"", "missing or too long"),
    ("no pluginId", hs_line(pluginId=KeyError), "pluginId"),
    ("no pluginDir", hs_line(pluginDir=""), "pluginDir"),
    ("no dataDir", hs_line(dataDir=7), "dataDir"),
    ("no stopEvent", hs_line(stopEvent=None), "stopEvent"),
    ("no apiBase", hs_line(apiBase=KeyError), "apiBase"),
    ("another plugin's", hs_line(pluginId="com.example.other"), "another plugin"),
    ("no token", hs_line(token=KeyError), "token"),
    ("empty token", hs_line(token=""), "token"),
    ("token with CRLF", hs_line(token="abc\r\nX-Evil: 1"), "token"),
    ("token with a space", hs_line(token="abc def"), "token"),
    ("token of 129", hs_line(token="a" * 129), "token"),
    ("apiBase not loopback", hs_line(apiBase="http://192.0.2.1:23551"), "loopback"),
    ("apiBase localhost", hs_line(apiBase="http://localhost:23551"), "loopback"),
    ("apiBase https", hs_line(apiBase="https://127.0.0.1:23551"), "loopback"),
    ("apiBase with a path", hs_line(apiBase="http://127.0.0.1:23551/x"), "loopback"),
    ("apiBase with a query", hs_line(apiBase="http://127.0.0.1:23551?x=1"), "loopback"),
    ("apiBase with userinfo", hs_line(apiBase="http://u:p@127.0.0.1:23551"), "loopback"),
    ("apiBase port 0", hs_line(apiBase="http://127.0.0.1:0"), "loopback"),
    ("apiBase port 99999", hs_line(apiBase="http://127.0.0.1:99999"), "loopback"),
    ("permissions a string", hs_line(permissions="config.read"), "permissions"),
    ("permissions with a number", hs_line(permissions=["config.read", 5]), "permissions"),
    ("settings a list", hs_line(settings=[]), "settings"),
    ("license a string", hs_line(license="yes"), "license"),
    ("lang a number", hs_line(lang=1), "lang"),
]


class UnitHandshake(unittest.TestCase):
    def test_good(self):
        hs, why = protocol.check_handshake(hs_line(), PLUGIN_ID)
        self.assertIsNone(why)
        self.assertEqual(hs, GOOD_HS)
        for optional in ("permissions", "settings", "license", "lang"):
            with self.subTest(without=optional):
                self.assertIsNotNone(protocol.check_handshake(hs_line(**{optional: KeyError}), PLUGIN_ID)[0])
        self.assertIsNotNone(protocol.check_handshake(hs_line(apiBase="http://127.0.0.1:23551/"), PLUGIN_ID)[0],
                             "a trailing slash is still the address")

    def test_every_bad_row(self):
        for label, line, reason in BAD_HANDSHAKES:
            with self.subTest(label):
                hs, why = protocol.check_handshake(line, PLUGIN_ID)
                self.assertIsNone(hs)
                self.assertIn(reason, why)

    def test_read_is_bounded(self):
        class Stream:
            def __init__(self):
                self.asked = None

            def readline(self, n=-1):
                self.asked = n
                return b""
        s = Stream()
        protocol.read_handshake(s, PLUGIN_ID)
        self.assertEqual(s.asked, protocol.MAX_HANDSHAKE_BYTES)

    def test_masked(self):
        view = protocol.masked(GOOD_HS)
        self.assertEqual(set(view), set(GOOD_HS))
        self.assertNotIn(TOKEN_CORE.decode(), json.dumps(view))
        for k in GOOD_HS:
            if k != "token":
                self.assertEqual(view[k], GOOD_HS[k])
        self.assertIn("token", GOOD_HS, "masking a copy, not the original")

    def test_split_api_base(self):
        self.assertEqual(protocol.split_api_base("http://127.0.0.1:5"), ("127.0.0.1", 5))
        self.assertEqual(protocol.split_api_base("http://127.0.0.1:65535/"), ("127.0.0.1", 65535))

    def test_is_hosted(self):
        self.assertTrue(protocol.is_hosted({"GHOST_PLUGIN_ID": ""}))
        self.assertFalse(protocol.is_hosted({"GHOST_PLUGIN_API_BASE": "http://127.0.0.1:1"}))

    def test_write_line(self):
        import io
        buf = io.BytesIO()
        protocol.write_line({"v": 1, "ok": True, "uiUrl": "http://127.0.0.1:5/x/"}, buf)
        self.assertEqual(buf.getvalue(), b'{"v":1,"ok":true,"uiUrl":"http://127.0.0.1:5/x/"}\n')


class UnitJson(unittest.TestCase):
    def test_parse_json(self):
        self.assertEqual(ghost_api.parse_json(b'{"a":[1,2]}'), {"a": [1, 2]})
        for bad in (b"NaN", b'{"a":Infinity}', b"-Infinity", b"{", b"\xff\xfe", "not bytes", None):
            with self.subTest(bad=bad):
                self.assertIsNone(ghost_api.parse_json(bad))
        self.assertIsNone(ghost_api.parse_json(b"[" * 100000), "deep nesting is None, not a RecursionError")
        self.assertIsNone(ghost_api.parse_json(b'"abcd"', limit=5), "over the limit")
        self.assertEqual(ghost_api.parse_json(b'"abc"', limit=5), "abc")


class UnitEvents(unittest.TestCase):
    def hub(self, perms=ALL_PERMS):
        self.now = [100.0]
        return events.EventHub(PLUGIN_ID, perms, clock=lambda: self.now[0])

    def ev(self, seq, plane, **kw):
        e = {"seq": seq, "ts": 1, "plane": plane, "level": "info", "src": "ui", "pid": 0, "targetId": "",
             "tag": "T", "fields": {}, "text": "t%d" % seq}
        e.update(kw)
        return e

    def test_planes_split(self):
        h = self.hub()
        h.add(self.ev(1, "system"), None)
        h.add(self.ev(2, "control"), 2)
        h.add(self.ev(3, "data"), 3)
        h.add(self.ev(4, "martian"), 4)
        v = h.view()
        self.assertEqual([e["seq"] for e in v["control"]], [1, 2], "System and Control together")
        self.assertEqual(v["data"], [], "Data is off by default")
        self.assertEqual((v["counts"], v["dataIgnored"]), ({"system": 1, "control": 1, "data": 1}, 1))
        self.assertEqual(h.resume_after(), 4, "the cursor passes every frame, kept or not")

    def test_data_switch_and_cap(self):
        h = self.hub()
        h.set_data(True)
        for i in range(8):
            h.add(self.ev(i, "data"), i)
        v = h.view()
        self.assertEqual(len(v["data"]), events.DATA_PER_SEC)
        self.assertEqual(v["dataShed"], 8 - events.DATA_PER_SEC)
        self.now[0] += 1.0                              # the next second
        h.add(self.ev(9, "data"), 9)
        self.assertEqual(len(h.view()["data"]), events.DATA_PER_SEC + 1)
        h.set_data(False)
        self.assertEqual(h.view()["data"], [], "switched off: forgotten")
        h.add(self.ev(10, "data"), 10)
        self.assertEqual((h.view()["data"], h.view()["dataIgnored"]), ([], 1))

    def test_keep_bounds(self):
        h = self.hub()
        h.set_data(True)
        for i in range(events.CONTROL_KEEP + 5):
            h.add(self.ev(i, "control"), i)
        self.assertEqual(len(h.view()["control"]), events.CONTROL_KEEP)
        self.assertEqual(h.view()["control"][-1]["seq"], events.CONTROL_KEEP + 4)

    def test_own_echo(self):
        h = self.hub()
        h.add(self.ev(1, "control", src="plugin", tag="com.example.other"), 1)
        self.assertIsNone(h.view()["ownEcho"], "another plugin's line is not ours")
        h.add(self.ev(2, "control", src="ui", tag=PLUGIN_ID), 2)
        self.assertIsNone(h.view()["ownEcho"], "src must be plugin")
        h.add(self.ev(3, "control", src="plugin", tag=PLUGIN_ID), 3)
        self.assertEqual(h.view()["ownEcho"]["seq"], 3)

    def test_clean_event(self):
        e = events.clean_event({"seq": "7", "ts": True, "plane": "data", "level": "loud", "pid": 1.5,
                                "text": "x" * 5000, "fields": {"a": 1}, "extra": "dropped", "tag": 5})
        self.assertEqual(set(e), {"seq", "ts", "plane", "level", "src", "pid", "targetId", "tag", "fields", "text"})
        self.assertEqual((e["seq"], e["ts"], e["level"], e["pid"], e["tag"]), (None, None, "info", 0, "5"))
        self.assertEqual(len(e["text"]), events.TEXT_KEEP_CHARS)
        self.assertEqual(e["fields"], {"a": "1"})

    def test_permissions(self):
        h = self.hub(["events.read.control"])
        self.assertEqual((h.view()["canControl"], h.view()["canData"]), (True, False))

    def test_read_frames(self):
        import io
        big = b"data: " + b"x" * (events.MAX_LINE_BYTES + 10) + b"\n\n"
        stream = io.BytesIO(frame(1, "a") + b": keepalive\n\n" + big + frame(2, "b") +
                            b"data: {not json\n\n" + b"id: 9\ndata: {\"seq\": 9,\ndata: \"text\": \"two lines\"}\n\n")
        got = []
        events.read_frames(stream, lambda ev, fid: got.append((fid, ev.get("text"))))
        self.assertEqual(got, [(1, "a"), (2, "b"), (9, "two lines")], "the oversize line is skipped whole")
        # An oversize line takes its whole FRAME with it -- even when every
        # other line of that frame is a good event, and even when the oversize
        # line is only a comment: a frame is never half-read.
        got = []
        stream = io.BytesIO(frame(1, "a") + b'data: {"seq": 2, "text": "b"}\n: ' + b"y" * (events.MAX_LINE_BYTES + 10) +
                            b"\n\n" + frame(3, "c"))
        events.read_frames(stream, lambda ev, fid: got.append((fid, ev.get("text"))))
        self.assertEqual(got, [(1, "a"), (3, "c")])


class UnitState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1000.0]

    def store(self, version="1.0.0"):
        s = state_store.StateStore(self.tmp.name, version, clock=lambda: self.now[0])
        s.load()
        return s

    def test_start_restart_upgrade(self):
        s = self.store()
        s.record_start()
        self.assertEqual((s.state["starts"], s.state["versions"], s.problem), (1, ["1.0.0"], ""))
        self.now[0] += 5
        s.record_stop()
        s2 = self.store("1.1.0")                # an upgrade: same dataDir, new version
        s2.record_start()
        v = s2.view()["state"]
        self.assertEqual((v["starts"], v["versions"], v["lastStop"], v["firstStart"]),
                         (2, ["1.0.0", "1.1.0"], 1005.0, 1000.0))

    def test_restart_bookkeeping(self):
        s = self.store()
        s.record_start()
        self.now[0] = 2000.0
        self.assertEqual(s.record_demo_exit(), 1)
        self.now[0] = 2001.5
        s2 = self.store()
        s2.record_start()
        self.assertEqual(s2.state["lastRestart"], {"delaySec": 1.5, "at": 2001.5})
        self.assertIsNone(s2.state["restartRequestedAt"])
        self.now[0] = 2001.5 + state_store.RESTART_WINDOW_SEC + 1
        s2.record_demo_exit()
        self.now[0] += state_store.RESTART_WINDOW_SEC + 1       # too late: a user's re-enable, not a restart
        s3 = self.store()
        s3.record_start()
        self.assertEqual(s3.state["lastRestart"]["at"], 2001.5, "unchanged")
        self.assertEqual(s3.view()["state"]["recentDemoExits"], 2)
        self.now[0] += state_store.BUDGET_WINDOW_SEC
        self.assertEqual(s3.view()["state"]["recentDemoExits"], 0, "outside the budget window")

    def test_bad_files_start_over(self):
        path = os.path.join(self.tmp.name, state_store.STATE_FILE)
        for label, content in (("not JSON", b"{"), ("a list", b"[]"), ("v 2", b'{"v":2,"starts":9}'),
                               ("v true", b'{"v":true,"starts":9}'),
                               ("too large", b'{"v":1}' + b" " * state_store.MAX_STATE_BYTES)):
            with self.subTest(label):
                with open(path, "wb") as f:
                    f.write(content)
                s = self.store()
                self.assertTrue(s.problem)
                self.assertEqual(s.state["starts"], 0)
        with open(path, "wb") as f:
            f.write(b'{"v":1,"starts":"9","versions":["1.0.0",5],"lastStop":"x","demoExits":[1,"a"],'
                    b'"lastRestart":{"delaySec":"1"}}')
        s = self.store()
        self.assertEqual((s.problem, s.state["starts"], s.state["versions"], s.state["lastStop"],
                          s.state["demoExits"], s.state["lastRestart"]), ("", 0, ["1.0.0"], None, [1], None),
                         "a wrong-typed field is reset, the rest kept")

    def test_atomic_write_and_reset(self):
        s = self.store()
        s.record_start()
        s.record_start()
        self.assertFalse(os.path.exists(s.path + ".tmp"), "the temporary file is renamed over, not left")
        with open(s.path, "rb") as f:
            self.assertEqual(json.loads(f.read())["starts"], 2)
        s.reset()
        self.assertEqual((s.state["starts"], s.state["versions"]), (1, ["1.0.0"]))
        self.assertEqual(self.store().state["starts"], 1, "the reset is on disk")

    def test_write_error_reported(self):
        s = state_store.StateStore(os.path.join(self.tmp.name, "missing-dir"), "1.0.0")
        s.record_start()
        self.assertTrue(s.write_error)


class StubClient:
    """For the sections: canned answers by path, every call recorded."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get_json(self, path):
        self.calls.append(("GET", path))
        status, doc = self.answers.get(path, (404, {"status": "error", "error": "not_found"}))
        return status, doc

    def post_json(self, path, obj):
        self.calls.append(("POST", path, obj))
        return self.answers.get(path, (0, None))

    def request(self, method, path, body=None, content_type=None):
        self.calls.append((method, path, body, content_type))
        status, body, ctype = self.answers[path]
        return ghost_api.Reply(status, body, ctype)


class UnitSections(unittest.TestCase):
    def test_config(self):
        c = StubClient({"/config": (200, REDACTED_CONFIG)})
        r = sections.config_section(c)
        self.assertEqual(r["nodes"], [
            {"name": "Demo-HK", "type": "SOCKS5", "addr": "10.0.0.8:1080", "user": "***", "pass": "***"},
            {"name": "办公室", "type": "HTTP", "addr": "10.0.0.9:8080", "user": "", "pass": ""}])
        self.assertEqual(r["keys"], ["dns", "settings", "stunServers", "upstream"])
        r = sections.config_section(StubClient({"/config": (403, {"status": "error", "error": "permission_denied"})}))
        self.assertEqual((r["status"], r["error"], r["nodes"]), (403, "permission_denied", []))
        self.assertEqual(sections.config_section(StubClient({"/config": (0, None)}))["error"], "no answer")

    def test_stats(self):
        now = [0.0]
        c = StubClient({"/process-stats": (200, PROCESS_STATS), "/latencies": (200, LATENCIES),
                        "/throughput-history": (200, THROUGHPUT)})
        s = sections.StatsSection(c, clock=lambda: now[0])
        r = s.get()
        p = r["processes"]
        self.assertEqual((p["status"], p["statsCount"], len(p["groups"])), (200, 2, 2))
        g1, g2 = p["groups"]
        self.assertEqual((g1["alias"], g1["activeCount"], g1["totalDown"], g1["hasEnv"]), ("Notes", 1, 4096, False))
        self.assertEqual(g1["children"], [{"pid": 4242, "name": "notepad.exe", "up": 2048, "down": 4096}])
        self.assertNotIn("icon", g1["keys"])
        self.assertIs(g2["hasEnv"], True, "reported as it arrived")
        self.assertIn("env", g2["keys"])
        self.assertNotIn("env", json.dumps(g2["children"]))
        self.assertNotIn("leak", json.dumps(r), "the value of an env that arrived is never relayed")
        lat = r["latencies"]
        self.assertEqual((lat["avgHttpLatency"], lat["retransmissionRate"], lat["isTesting"]), (120, 0.5, False))
        self.assertEqual(lat["nodes"], [{"id": "n1", "latency": 120, "success": 3, "attempts": 4, "udp": "usable"},
                                        {"id": "n2", "latency": -1, "success": 0, "attempts": 2, "udp": ""}])
        self.assertEqual(r["throughput"]["history"], [1.0, 2.5, 4.0])
        self.assertEqual(len(c.calls), 3)
        now[0] = sections.STATS_CACHE_SEC - 0.1
        self.assertIs(s.get(), r, "cached")
        self.assertEqual(len(c.calls), 3)
        now[0] = sections.STATS_CACHE_SEC + 0.1
        s.get()
        self.assertEqual(len(c.calls), 6, "asked again after the cache time")

    def test_log(self):
        c = StubClient({"/api/log-ingest": (200, {"status": "ok", "accepted": 1, "rateDropped": 0, "malformed": 0,
                                                  "truncated": False})})
        r = sections.log_write(c, 3)
        entry = c.calls[0][2]["entries"][0]
        self.assertEqual(set(c.calls[0][2]), {"entries"}, "the key is entries; no v")
        self.assertEqual({k: entry[k] for k in ("level", "src", "tag", "plane")}, sections.LOG_ASKED)
        self.assertIn("#3", entry["text"])
        self.assertEqual(r["answer"], {"status": 200, "accepted": 1, "rateDropped": 0, "malformed": 0,
                                       "truncated": False})
        c = StubClient({"/api/log-ingest": (200, {"accepted": 9, "rateDropped": 0, "malformed": 1, "truncated": False})})
        r = sections.log_burst(c, 1)
        sent = c.calls[0][2]["entries"]
        self.assertEqual(len(sent), sections.LOG_BURST)
        self.assertEqual([e["text"] == "" for e in sent], [False] * (sections.LOG_BURST - 1) + [True])
        self.assertEqual((r["sent"], r["answer"]["accepted"], r["answer"]["malformed"]), (10, 9, 1))
        r = sections.log_write(StubClient({"/api/log-ingest": (429, {"status": "error", "error": "rate_limited"})}), 1)
        self.assertEqual(r["answer"]["error"], "rate_limited")

    def test_icon(self):
        own = "/api/plugins/icon?id=" + PLUGIN_ID
        for label, answer, expected in (
                ("png", (200, ICON, "image/png"), ("image/png", ICON)),
                ("webp with params", (200, b"RIFF", "image/webp; x=1"), ("image/webp", b"RIFF")),
                ("html", (200, b"<b>", "text/html"), None),
                ("empty", (200, b"", "image/png"), None),
                ("too large", (200, b"x" * (sections.MAX_ICON_BYTES + 1), "image/png"), None),
                ("404", (404, b"{}", "image/png"), None)):
            with self.subTest(label):
                self.assertEqual(sections.fetch_own_icon(StubClient({own: answer}), PLUGIN_ID), expected)
        other = "/api/plugins/icon?id=" + sections.OTHER_PLUGIN_ID
        r = sections.other_icon(StubClient({other: (403, b'{"status":"error","error":"permission_denied"}', "")}))
        self.assertEqual(r, {"id": sections.OTHER_PLUGIN_ID, "status": 403, "error": "permission_denied"})


class RecordingGhost:
    """A tiny server answering 429 `n429` times, then 200 -- for the client."""

    def __init__(self, n429):
        self.left = n429
        self.hits = []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.hits.append(dict(self.headers.items()))
                code, body = (429, b'{"status":"error","error":"rate_limited"}') if fake.left > 0 else (200, b"{}")
                fake.left -= 1
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            do_POST = do_GET

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class UnitBackoff(unittest.TestCase):
    def run_with(self, n429):
        g = RecordingGhost(n429)
        self.addCleanup(g.close)
        slept = []
        c = ghost_api.GhostClient("127.0.0.1", g.port, TOKEN, sleep=slept.append)
        return c, c.request("GET", "/config"), slept, g

    def test_two_429_then_ok(self):
        c, reply, slept, g = self.run_with(2)
        self.assertEqual(reply.status, 200)
        self.assertEqual(slept, [0.25, 0.5], "exponential")
        self.assertEqual(len(g.hits), 3)
        self.assertEqual(c.counters(), {"calls": 3, "rateLimited": 2, "retries": 2, "gaveUp": 0})
        for h in g.hits:
            self.assertEqual(h.get("X-Ghost-Plugin-Token"), TOKEN)
            self.assertNotIn("Origin", h)
            self.assertNotIn("X-Ghost-Token", h)

    def test_gives_up(self):
        c, reply, slept, g = self.run_with(100)
        self.assertEqual(reply.status, 429)
        self.assertEqual(slept, list(ghost_api.RETRY_DELAYS_SEC))
        self.assertEqual(len(g.hits), 1 + len(ghost_api.RETRY_DELAYS_SEC), "bounded")
        self.assertEqual(c.counters()["gaveUp"], 1)

    def test_no_retry_on_other_refusals(self):
        c, reply, slept, g = self.run_with(0)
        self.assertEqual((reply.status, slept, len(g.hits)), (200, [], 1))

    def test_request_is_minimal(self):
        # The file a plugin copies unchanged has no way to send a wrong
        # header or an Origin: the showcase's deliberate 401s are built by
        # hand in sections.py.
        import inspect
        self.assertEqual(list(inspect.signature(ghost_api.GhostClient.request).parameters),
                         ["self", "method", "path", "body", "content_type"])
        src = open(os.path.join(PLUGIN, "ghost_api.py"), encoding="utf-8").read()
        for bad in ('"Origin"', "X-Ghost-Host-Token", "X-Ghost-Token"):
            self.assertNotIn(bad, src)

    def test_no_answer(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]                   # nothing listens once closed
        c = ghost_api.GhostClient("127.0.0.1", port, TOKEN, sleep=lambda _: None)
        self.assertEqual(c.request("GET", "/config").status, 0)


# =====================================================================================
# Process: main.py under a fake host and a fake Ghost
# =====================================================================================

class FakeGhost:
    """events_mode "frames": the first /events answers 200 with control 10,
    system 11 (warn) and data 12, a comment between, then closes; later ones
    stay open and carry whatever push() adds (the log-ingest echo does). "403":
    every /events is a 403. rate_limit: the next N authorised requests to any
    other route answer 429."""

    def __init__(self, events_mode="frames", icon_type="image/png"):
        self.events_mode = events_mode
        self.icon_type = icon_type
        self.requests = []           # (time, method, path, headers, body)
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.pushed = []
        self.stop = threading.Event()
        self.rate_limit = 0
        self.seq = 100
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def record(self, body=b""):
                with fake.lock:
                    fake.requests.append((time.monotonic(), self.command, self.path, dict(self.headers.items()), body))

            def authorised(self):
                return self.headers.get("X-Ghost-Plugin-Token") == TOKEN and "Origin" not in self.headers

            def answer(self, code, body, ctype="application/json"):
                if not isinstance(body, bytes):
                    body = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def limited(self):
                with fake.lock:
                    if fake.rate_limit > 0:
                        fake.rate_limit -= 1
                        return True
                return False

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.record(body)
                if not self.authorised():
                    return self.answer(401, {"status": "error", "error": "unauthorized"})
                if self.limited():
                    return self.answer(429, {"status": "error", "error": "rate_limited"})
                if self.path == "/api/log-ingest":
                    doc = json.loads(body)
                    good = [e for e in doc["entries"] if e.get("text")]
                    for e in good:          # what the real gate does to a plugin's line
                        fake.push(frame(fake.next_seq(), e["text"], src="plugin", tag=PLUGIN_ID,
                                        level="info" if e.get("level") == "debug" else e.get("level", "info")))
                    return self.answer(200, {"status": "ok", "accepted": len(good), "rateDropped": 0,
                                             "malformed": len(doc["entries"]) - len(good), "truncated": False})
                if self.path == "/save-config":
                    return self.answer(403, {"status": "error", "error": "permission_denied"})
                self.answer(403, {"status": "error", "error": "permission_denied"})

            def do_GET(self):
                self.record()
                if not self.authorised():
                    return self.answer(401, {"status": "error", "error": "unauthorized"})
                if self.path.startswith("/events"):
                    return self.events()
                if self.limited():
                    return self.answer(429, {"status": "error", "error": "rate_limited"})
                routes = {"/config": REDACTED_CONFIG, "/process-stats": PROCESS_STATS, "/latencies": LATENCIES,
                          "/throughput-history": THROUGHPUT}
                if self.path in routes:
                    return self.answer(200, routes[self.path])
                if self.path == "/api/plugins/icon?id=" + PLUGIN_ID:
                    return self.answer(200, ICON, fake.icon_type)
                if self.path.startswith("/api/plugins/icon?id="):
                    return self.answer(403, {"status": "error", "error": "permission_denied"})
                self.answer(403, {"status": "error", "error": "permission_denied"})

            def events(self):
                if fake.events_mode == "403":
                    return self.answer(403, {"status": "error", "error": "permission_denied"})
                self.close_connection = True
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                                 b"Cache-Control: no-cache\r\nConnection: keep-alive\r\n\r\n")
                if fake.count("GET", "/events") == 1:
                    self.wfile.write(frame(10, "target #1 launched") + b": keepalive\n\n" +
                                     frame(11, "slow node", plane="system", level="warn") +
                                     frame(12, "dns example.org", plane="data"))
                    self.wfile.flush()
                    return                     # close: the plugin must reconnect with after=12
                with fake.cond:
                    at = len(fake.pushed)
                while not fake.stop.is_set():
                    with fake.cond:
                        fake.cond.wait(0.2)
                        new, at = fake.pushed[at:], len(fake.pushed)
                    try:
                        for f in new:
                            self.wfile.write(f)
                        self.wfile.flush()
                    except OSError:
                        return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.api_base = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def next_seq(self):
        with self.lock:
            self.seq += 1
            return self.seq

    def push(self, raw):
        with self.cond:
            self.pushed.append(raw)
            self.cond.notify_all()

    def count(self, method, prefix):
        with self.lock:
            return sum(1 for r in self.requests if r[1] == method and r[2].startswith(prefix))

    def snapshot(self):
        with self.lock:
            return list(self.requests)

    def of(self, method, path):
        return [r for r in self.snapshot() if r[1] == method and r[2] == path]

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()


_n = [0]


class Host:
    """One plugin, started the way ghost_plugin_host.exe starts it."""

    def __init__(self, api_base, data_dir, overrides=None, hosted=True, extra_env=None, args=None, raw_line=None):
        _n[0] += 1
        # The test is the host here, so it names the event; the plugin must
        # only ever use the name it is handed.
        self.stop_name = "Local\\ShowcaseTest_%d_%d" % (os.getpid(), _n[0])
        self.event = k32.CreateEventW(None, True, False, self.stop_name)
        if not self.event:
            raise OSError("CreateEventW failed: %d" % ctypes.get_last_error())
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE") if k in os.environ}
        env["PATH"] = os.path.dirname(sys.executable)
        if hosted:
            env.update(GHOST_PLUGIN_ID=PLUGIN_ID, GHOST_PLUGIN_DIR=PLUGIN, GHOST_PLUGIN_DATA_DIR=data_dir,
                       GHOST_PLUGIN_API_BASE=api_base, GHOST_PLUGIN_STOP_EVENT=self.stop_name,
                       GHOST_PLUGIN_PYTHON=sys.executable)
        env.update(extra_env or {})
        self.stderr = tempfile.TemporaryFile()
        argv = MANIFEST["args"] if args is None else args
        self.proc = subprocess.Popen([sys.executable, MAIN] + list(argv), cwd=PLUGIN, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.stderr,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.handshake = {"v": 1, "pluginId": PLUGIN_ID, "pluginDir": PLUGIN, "dataDir": data_dir,
                          "apiBase": api_base, "token": TOKEN, "permissions": ALL_PERMS, "settings": {},
                          "license": {"licensed": False, "trial": False}, "lang": "zh", "stopEvent": self.stop_name}
        self.handshake.update(overrides or {})
        self.raw_line = raw_line
        self.lines = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.proc.stdout:
            self.lines.append(raw)

    def send_handshake(self):
        line = self.raw_line if self.raw_line is not None else (json.dumps(self.handshake) + "\n").encode("utf-8")
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def first_line(self, timeout=10):
        if not wait_until(lambda: self.lines, timeout):
            raise AssertionError("no line on stdout within %ss" % timeout)
        return self.lines[0]

    def receipt(self, timeout=10):
        return json.loads(self.first_line(timeout).decode("utf-8"))

    def stop(self):
        k32.SetEvent(self.event)

    def wait(self, timeout):
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def stderr_bytes(self):
        self.stderr.seek(0)
        return self.stderr.read()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        for f in (self.proc.stdin, self.proc.stdout, self.stderr):
            try:
                f.close()
            except OSError:
                pass
        k32.CloseHandle(self.event)


def call(port, method, path, host=None, origin="own", body=None, ctype="application/json"):
    """(status, body bytes, headers dict). origin "own" = the page's own."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host or "127.0.0.1:%d" % port)
        if origin == "own":
            origin = "http://127.0.0.1:%d" % port if method == "POST" else None
        if origin:
            conn.putheader("Origin", origin)
        if method == "POST":
            data = body if body is not None else b"{}"
            conn.putheader("Content-Type", ctype)
            conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
        else:
            conn.endheaders()
        r = conn.getresponse()
        return r.status, r.read(), dict(r.getheaders())
    finally:
        conn.close()


def url_of(url):
    m = re.fullmatch(r"http://127\.0\.0\.1:(\d{1,5})(/[0-9a-f]{32}/)", url)
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def port_closed(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return False
    except OSError:
        return True


GET_ROUTES = ("", "app.js", "app.css", "api/status", "api/protocol", "api/events", "api/state", "api/config",
              "api/stats", "api/icon")
POST_ROUTES = ("api/events/data", "api/log", "api/log/burst", "api/assets/other", "api/gate/403",
               "api/gate/401-header", "api/gate/401-origin", "api/state/reset", "api/restart")


class HostedBase(unittest.TestCase):
    events_mode = "frames"
    icon_type = "image/png"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmp.name, ".data")
        os.makedirs(self.data)
        self.ghost = FakeGhost(self.events_mode, self.icon_type)
        self.hosts = []

    def tearDown(self):
        for h in self.hosts:
            h.close()
        self.ghost.close()
        self.tmp.cleanup()

    def start(self, overrides=None, **kw):
        h = Host(self.ghost.api_base, self.data, overrides, **kw)
        self.hosts.append(h)
        h.send_handshake()
        return h

    def started(self, **kw):
        h = self.start(**kw)
        r = h.receipt()
        port, base = url_of(r.get("uiUrl", ""))
        self.assertIsNotNone(port, r)
        self.port, self.base = port, base
        return h

    def get(self, rest):
        code, body, _ = call(self.port, "GET", self.base + rest)
        self.assertNotIn(TOKEN_CORE, body)
        return code, json.loads(body.decode("utf-8"))

    def post(self, rest, obj=None):
        code, body, _ = call(self.port, "POST", self.base + rest, body=json.dumps(obj or {}).encode("utf-8"))
        self.assertNotIn(TOKEN_CORE, body)
        return code, json.loads(body.decode("utf-8"))

    def assert_plugin_request(self, headers):
        self.assertEqual(headers.get("X-Ghost-Plugin-Token"), TOKEN)
        self.assertNotIn("Origin", headers)
        self.assertNotIn("X-Ghost-Token", headers)
        self.assertNotIn("X-Ghost-Host-Token", headers)


class Hosted(HostedBase):
    def test_01_receipt(self):
        h = self.start()
        raw = h.first_line()
        self.assertTrue(raw.endswith(b"\n"))
        r = json.loads(raw.decode("utf-8"))
        self.assertEqual(set(r), {"v", "ok", "uiUrl"}, "exactly these keys")
        self.assertEqual((r["v"], r["ok"]), (1, True))
        port, base = url_of(r["uiUrl"])
        self.assertIsNotNone(port, r["uiUrl"])
        self.assertNotIn(port, (23551, 80))
        self.assertNotIn(TOKEN_CORE, raw)
        other = self.start()
        self.assertNotEqual(base, url_of(other.receipt()["uiUrl"])[1], "a new prefix per start")

    def test_02_page_guard(self):
        self.started()
        b, port = self.base, self.port
        for rest, marker in (("", b"<!doctype html>"), ("app.js", b"textContent"), ("app.css", b"prefers-color-scheme")):
            with self.subTest(rest=rest):
                code, body, headers = call(port, "GET", b + rest)
                self.assertEqual(code, 200)
                self.assertIn(marker, body)
                self.assertEqual(headers["Content-Security-Policy"], (
                    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
                    "base-uri 'none'; form-action 'none'; frame-ancestors " + self.ghost.api_base))
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for rest in ("main.py", "manifest.json", "../main.py", "ui/index.html", "index.html", "%2e%2e/main.py",
                     "..\\main.py", "tests/test_plugin.py", "api/", "api/config/", "protocol.py"):
            with self.subTest(rest=rest):
                self.assertEqual(call(port, "GET", b + rest)[0], 404)
        for path in ("/", "/app.js", "/api/status", b[:-1], b.upper(), "/" + "0" * 32 + "/"):
            with self.subTest(path=path):
                self.assertEqual(call(port, "GET", path)[0], 404, "nothing without the prefix")
        for host in ("evil.example:%d" % port, "localhost:%d" % port, "127.0.0.1"):
            with self.subTest(host=host):
                self.assertEqual(call(port, "GET", b, host=host)[0], 403, "DNS rebinding")

    def test_03_post_guard(self):
        self.started()
        time.sleep(0.5)
        before = [r for r in self.ghost.snapshot() if r[1] == "POST"]
        for rest in ("api/log", "api/gate/403", "api/state/reset"):
            for origin in ("http://evil.example", "http://127.0.0.1:%d" % (self.port % 65535 + 1), "null", None):
                with self.subTest(rest=rest, origin=origin):
                    self.assertEqual(call(self.port, "POST", self.base + rest, origin=origin)[0], 403)
        self.assertEqual(call(self.port, "POST", self.base + "api/log", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(call(self.port, "POST", "/api/log")[0], 404)
        self.assertEqual(call(self.port, "POST", self.base + "api/log", body=b"x" * 5000)[0], 413)
        self.assertEqual(call(self.port, "POST", self.base + "api/log", body=b"not json")[0], 400)
        self.assertEqual(call(self.port, "POST", self.base + "api/log", body=b"[]")[0], 400, "an object only")
        self.assertEqual(call(self.port, "POST", self.base + "api/nope")[0], 404)
        time.sleep(0.3)
        self.assertEqual([r for r in self.ghost.snapshot() if r[1] == "POST"], before, "not one POST reached Ghost")
        self.assertEqual(self.post("api/log")[0], 200, "its own page's Origin is fine")

    def test_04_protocol_view(self):
        self.started()
        code, p = self.get("api/protocol")
        self.assertEqual(code, 200)
        self.assertEqual(p["mode"], "hosted")
        hs = p["handshake"]
        self.assertEqual(set(hs), set(self.hosts[0].handshake), "every field is shown")
        for k in ("v", "pluginId", "pluginDir", "dataDir", "apiBase", "permissions", "settings", "license", "lang",
                  "stopEvent"):
            self.assertEqual(hs[k], self.hosts[0].handshake[k], k)
        self.assertNotEqual(hs["token"], TOKEN)
        self.assertEqual(p["receipt"], self.hosts[0].receipt())
        self.assertEqual(p["argv"], MANIFEST["args"])
        self.assertEqual(p["manifestArgs"], MANIFEST["args"])
        self.assertEqual(p["envMatches"], {k: True for k in ("GHOST_PLUGIN_ID", "GHOST_PLUGIN_DIR",
                                                               "GHOST_PLUGIN_DATA_DIR", "GHOST_PLUGIN_API_BASE",
                                                               "GHOST_PLUGIN_STOP_EVENT")})
        self.assertEqual(p["env"]["GHOST_PLUGIN_PYTHON"], sys.executable)
        self.assertIsNone(p["env"]["GHOST_PLUGIN_NODE"])
        self.assertIs(p["tokenInEnv"], False)
        rt = p["runtime"]
        self.assertEqual((rt["declared"], rt["meets"]), ({"kind": "python", "minVersion": "3.9"}, True))
        self.assertEqual(p["license"], {"present": True, "licensed": False, "trial": False, "expiresAt": None})
        self.assertEqual((p["settings"], p["stopEvent"]["name"], p["stopEvent"]["error"]),
                         ({}, self.hosts[0].stop_name, ""))

    def test_05_status(self):
        self.started()
        code, s = self.get("api/status")
        self.assertEqual(code, 200)
        self.assertEqual((s["hosted"], s["lang"], s["pluginId"], s["version"], s["permissions"], s["declared"]),
                         (True, "zh", PLUGIN_ID, "1.0.0", ALL_PERMS, MANIFEST["permissions"]))
        self.assertEqual(s["frameAncestor"], self.ghost.api_base)
        self.assertEqual(set(s["client"]), {"calls", "rateLimited", "retries", "gaveUp"})

    def test_06_config(self):
        self.started()
        time.sleep(0.3)
        self.assertEqual(self.ghost.of("GET", "/config"), [], "read when the page asks, not at start")
        code, r = self.get("api/config")
        self.assertEqual((code, r["status"], r["nodes"][0]["pass"], r["nodes"][1]["pass"]), (200, 200, "***", ""))
        gets = self.ghost.of("GET", "/config")
        self.assertEqual(len(gets), 1)
        self.assert_plugin_request(gets[0][3])

    def test_07_stats(self):
        self.started()
        code, r = self.get("api/stats")
        self.assertEqual(code, 200)
        self.assertEqual([g["hasEnv"] for g in r["processes"]["groups"]], [False, True])
        self.assertEqual(r["latencies"]["nodes"][0]["udp"], "usable")
        self.assertEqual(r["throughput"]["history"], [1.0, 2.5, 4.0])
        self.get("api/stats")
        for path in ("/process-stats", "/latencies", "/throughput-history"):
            with self.subTest(path=path):
                got = self.ghost.of("GET", path)
                self.assertEqual(len(got), 1, "asked once; the second page ask is cached")
                self.assert_plugin_request(got[0][3])

    def test_08_events(self):
        self.started()
        self.assertTrue(wait_until(lambda: self.ghost.count("GET", "/events") >= 2, 15), "reconnects")
        gets = [r for r in self.ghost.snapshot() if r[1] == "GET" and r[2].startswith("/events")]
        self.assertEqual((gets[0][2], gets[1][2]), ("/events", "/events?after=12"))
        for r in gets[:2]:
            self.assert_plugin_request(r[3])
            self.assertEqual(r[3].get("Accept"), "text/event-stream")
        self.assertTrue(wait_until(lambda: self.get("api/events")[1]["connected"], 5))
        _, v = self.get("api/events")
        self.assertEqual([e["seq"] for e in v["control"]], [10, 11], "control + system; the comment is no event")
        self.assertEqual((v["counts"], v["data"], v["dataIgnored"]), ({"system": 1, "control": 1, "data": 1}, [], 1))
        self.assertEqual(self.post("api/events/data", {"on": "yes"})[1], {"error": "on must be true or false"})
        self.assertEqual(self.post("api/events/data", {"on": True})[1], {"dataOn": True})
        self.ghost.push(frame(200, "dns example.com", plane="data"))
        self.assertTrue(wait_until(lambda: self.get("api/events")[1]["data"], 5))
        self.assertEqual(self.get("api/events")[1]["data"][0]["text"], "dns example.com")
        self.assertEqual(self.ghost.count("GET", "/events"), 2, "one stream, never a second")

    def test_09_log_and_echo(self):
        self.started()
        self.assertTrue(wait_until(lambda: self.ghost.count("GET", "/events") >= 2, 15))
        time.sleep(0.5)
        self.assertEqual(self.ghost.of("POST", "/api/log-ingest"), [], "nothing logged until the button")
        code, r = self.post("api/log")
        self.assertEqual((code, r["asked"]), (200, sections.LOG_ASKED))
        self.assertEqual(r["answer"]["accepted"], 1)
        _, _, _, headers, body = self.ghost.of("POST", "/api/log-ingest")[0]
        self.assert_plugin_request(headers)
        self.assertEqual(headers.get("Content-Type"), "application/json")
        entry = json.loads(body)["entries"][0]
        self.assertEqual((entry["src"], entry["tag"], entry["plane"], entry["level"]), ("ui", "Ghost", "data", "debug"))
        self.assertTrue(wait_until(lambda: self.get("api/events")[1]["ownEcho"], 5), "the line comes back")
        echo = self.get("api/events")[1]["ownEcho"]
        self.assertEqual((echo["src"], echo["tag"], echo["plane"], echo["level"]), ("plugin", PLUGIN_ID, "control", "info"))
        code, r = self.post("api/log/burst")
        self.assertEqual((r["sent"], r["answer"]["accepted"], r["answer"]["malformed"]), (10, 9, 1))

    def test_10_assets(self):
        self.started()
        self.assertTrue(wait_until(lambda: self.get("api/status")[1]["icon"], 10))
        own = self.ghost.of("GET", "/api/plugins/icon?id=" + PLUGIN_ID)
        self.assertEqual(len(own), 1)
        self.assert_plugin_request(own[0][3])
        code, body, headers = call(self.port, "GET", self.base + "api/icon")
        self.assertEqual((code, body, headers["Content-Type"]), (200, ICON, "image/png"))
        self.assertEqual(self.post("api/assets/other")[1],
                         {"id": sections.OTHER_PLUGIN_ID, "status": 403, "error": "permission_denied"})

    def test_11_gate(self):
        self.started()
        self.assertEqual(self.post("api/gate/403")[1], {"status": 403, "error": "permission_denied"})
        _, _, _, headers, body = self.ghost.of("POST", "/save-config")[0]
        self.assert_plugin_request(headers)
        with self.assertRaises(ValueError):
            json.loads(body.decode("utf-8"))              # could change nothing even if let through
        before = len(self.ghost.of("GET", "/config"))
        self.assertEqual(self.post("api/gate/401-header")[1], {"status": 401, "error": "unauthorized"})
        wrong = self.ghost.of("GET", "/config")[before][3]
        self.assertEqual(wrong.get("X-Ghost-Host-Token"), TOKEN)
        self.assertNotIn("X-Ghost-Plugin-Token", wrong)
        self.assertNotIn("X-Ghost-Token", wrong, "never the session header, not even to show a refusal")
        r = self.post("api/gate/401-origin")[1]
        self.assertEqual((r["status"], r["error"], r["origin"]), (401, "unauthorized", "http://127.0.0.1:%d" % self.port))
        self.assertEqual(self.ghost.of("GET", "/config")[before + 1][3].get("Origin"), r["origin"])

    def test_12_backoff_through_the_process(self):
        self.started()
        time.sleep(0.5)
        self.ghost.rate_limit = 2
        code, r = self.get("api/config")
        self.assertEqual(r["status"], 200, "retried past two 429s")
        times = [t for t, m, p, _, _ in self.ghost.snapshot() if p == "/config"]
        self.assertEqual(len(times), 3)
        self.assertGreaterEqual(times[1] - times[0], 0.2)
        self.assertGreaterEqual(times[2] - times[1], 0.45, "the second pause is longer")
        c = self.get("api/status")[1]["client"]
        self.assertEqual((c["rateLimited"], c["retries"], c["gaveUp"]), (2, 2, 0))

    def test_13_data_dir_and_stop(self):
        h = self.started()
        _, v = self.get("api/state")
        self.assertEqual((v["state"]["starts"], v["state"]["versions"], v["problem"]), (1, ["1.0.0"], ""))
        self.assertEqual(v["file"], os.path.join(self.data, "state.json"))
        h.stop()
        self.assertEqual(h.wait(10), 0, "a graceful stop exits 0")
        self.assertTrue(port_closed(self.port))
        with open(os.path.join(self.data, "state.json"), "rb") as f:
            saved = json.loads(f.read())
        self.assertIsNotNone(saved["lastStop"], "flushed on the stop event")
        self.started()                                   # the same dataDir: a restart, or an upgrade
        _, v = self.get("api/state")
        self.assertEqual((v["state"]["starts"], v["state"]["lastStop"]), (2, saved["lastStop"]))
        _, v = self.post("api/state/reset")
        self.assertEqual(v["state"]["starts"], 1)

    def test_14_restart_demo(self):
        h = self.started()
        self.assertEqual(call(self.port, "POST", self.base + "api/restart", body=b"{}")[0], 400, "confirm required")
        code, r = self.post("api/restart", {"confirm": True})
        self.assertEqual((code, r["exiting"], r["exitCode"], r["recentExits"]), (200, True, 3, 1))
        self.assertEqual(h.wait(10), 3, "the non-zero code the host reads as a crash")
        self.started()                                   # the host's restart
        _, v = self.get("api/state")
        self.assertEqual(v["state"]["starts"], 2)
        self.assertIsNotNone(v["state"]["lastRestart"])
        self.assertLess(v["state"]["lastRestart"]["delaySec"], 30)

    def test_15_token_never_leaves(self):
        h = self.started()
        self.assertTrue(wait_until(lambda: self.ghost.count("GET", "/events") >= 2, 15))
        for rest in GET_ROUTES:
            with self.subTest(get=rest):
                self.assertNotIn(TOKEN_CORE, call(self.port, "GET", self.base + rest)[1])
        for rest in POST_ROUTES:
            if rest == "api/restart":
                continue
            with self.subTest(post=rest):
                self.assertNotIn(TOKEN_CORE, call(self.port, "POST", self.base + rest)[1])
        h.stop()
        self.assertEqual(h.wait(10), 0)
        self.assertEqual(len(h.lines), 1, "nothing on stdout after the receipt")
        self.assertNotIn(TOKEN_CORE, b"".join(h.lines) + h.stderr_bytes())
        for name in os.listdir(self.data):
            with open(os.path.join(self.data, name), "rb") as f:
                self.assertNotIn(TOKEN_CORE, f.read(), name)
        self.assertEqual([n for n in os.listdir(PLUGIN) if n == "__pycache__"], [], "no bytecode next to the code")

    def test_16_bad_handshakes(self):
        rows = [r for r in BAD_HANDSHAKES if r[0] not in ("empty (EOF)",)]
        for label, line, reason in rows[:12] + rows[-6:]:
            with self.subTest(label):
                before = len(self.ghost.snapshot())
                h = Host(self.ghost.api_base, self.data, raw_line=line)
                self.hosts.append(h)
                h.send_handshake()
                h.proc.stdin.close()                       # EOF after the line: no-newline rows end here
                r = h.receipt()
                self.assertEqual((r.get("v"), r.get("ok")), (1, False))
                self.assertIn(reason, r.get("error", ""))
                self.assertNotIn("uiUrl", r)
                self.assertEqual(h.wait(10), 1)
                time.sleep(0.2)
                self.assertEqual(len(self.ghost.snapshot()), before, "not one request to Ghost")
        self.assertEqual(os.listdir(self.data), [], "nothing written for a refused handshake")


class NotAnImage(HostedBase):
    icon_type = "text/html"

    def test_icon_that_is_not_an_image_is_not_relayed(self):
        self.started()
        self.assertTrue(wait_until(lambda: self.ghost.of("GET", "/api/plugins/icon?id=" + PLUGIN_ID), 10))
        time.sleep(0.5)
        self.assertIs(self.get("api/status")[1]["icon"], False)
        self.assertEqual(call(self.port, "GET", self.base + "api/icon")[0], 404)


class RefusedStream(HostedBase):
    events_mode = "403"

    def test_refused_stream(self):
        h = self.started()
        self.assertTrue(wait_until(lambda: self.ghost.count("GET", "/events") >= 2, 10), "it retries")
        self.assertIsNone(h.proc.poll(), "a 403 does not end the plugin")
        v = self.get("api/events")[1]
        self.assertEqual((v["lastError"], v["connected"]), ("HTTP 403", False))
        h.stop()
        self.assertEqual(h.wait(10), 0)


class Standalone(unittest.TestCase):
    def test_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            ghost = FakeGhost()
            # GHOST_PLUGIN_API_BASE without GHOST_PLUGIN_ID: an address the
            # plugin must not use -- standalone has no Ghost.
            h = Host(ghost.api_base, os.path.join(tmp, "unused"), hosted=False, args=[],
                     extra_env={"LOCALAPPDATA": tmp, "GHOST_PLUGIN_API_BASE": ghost.api_base})
            try:
                # stdin stays open and silent: a plugin that read it would block here.
                line = h.first_line(10).decode("utf-8").strip()
                port, base = url_of(line)
                self.assertIsNotNone(port, line)
                code, body, headers = call(port, "GET", base)
                self.assertEqual(code, 200)
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                s = json.loads(call(port, "GET", base + "api/status")[1])
                self.assertEqual((s["hosted"], s["lang"], s["permissions"], s["client"]), (False, None, [], None))
                p = json.loads(call(port, "GET", base + "api/protocol")[1])
                self.assertEqual((p["mode"], p["handshake"], p["receipt"], p["license"]),
                                 ("standalone", None, None, {"present": False}))
                for rest in ("api/config", "api/stats"):
                    self.assertEqual(json.loads(call(port, "GET", base + rest)[1]), {"error": "standalone"})
                for rest in ("api/log", "api/log/burst", "api/assets/other", "api/gate/403", "api/gate/401-header",
                             "api/gate/401-origin", "api/restart"):
                    with self.subTest(rest=rest):
                        code, body, _ = call(port, "POST", base + rest)
                        self.assertEqual((code, json.loads(body)), (200, {"error": "standalone"}))
                v = json.loads(call(port, "GET", base + "api/state")[1])
                self.assertEqual(v["state"]["starts"], 1, "the data directory works standalone")
                self.assertTrue(os.path.isfile(os.path.join(tmp, PLUGIN_ID, "state.json")), "%LOCALAPPDATA%\\<id>\\")
                time.sleep(1.0)
                self.assertEqual(ghost.snapshot(), [], "not one request to Ghost")
                self.assertIsNone(h.proc.poll())
            finally:
                h.close()
                ghost.close()


if __name__ == "__main__":
    if sys.platform != "win32":
        print("SKIP: the stop event is a Windows named event")
        sys.exit(77)
    unittest.main()
