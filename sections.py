"""One function per Ghost-backed section of the page: what the plugin asks
Ghost, and what it hands the page. Each is spec-plugin-api.md made concrete.

Every answer the page gets is built HERE, field by field, from what Ghost
said -- a plugin relays data it has looked at, never a response body
verbatim: a relayed body is how an extra field (tomorrow's) ends up somewhere
nobody meant to show it.
"""

import http.client
import threading
import time

import ghost_api

# Another plugin's id, for the plugin.assets refusal. Any valid id works: the
# gate answers 403 before it looks whether that plugin is installed.
OTHER_PLUGIN_ID = "com.ghostproxifier.events-viewer"
MAX_ICON_BYTES = 256 * 1024              # spec-limits.md: kMaxIconBytes
ICON_TYPES = ("image/png", "image/webp")
STATS_CACHE_SEC = 2.0
LOG_BURST = 10                           # entries per burst press -- small on purpose


def _str(v):
    return v if isinstance(v, str) else ""


def _int(v):
    return v if type(v) is int else 0


def _num(v):
    return v if type(v) in (int, float) else 0


def _error_of(status, doc):
    """Ghost's refusal code, or a description when there is none."""
    if isinstance(doc, dict) and isinstance(doc.get("error"), str):
        return doc["error"]
    return "no answer" if status == 0 else ""


# ---- config.read (§4) ------------------------------------------------------------------

def config_section(ghost):
    """GET /config: the plugin gets RedactConfigForExport's copy -- every
    non-empty upstream user and pass is "***", and an EMPTY one stays empty
    ("***" there would tell the reader a password exists)."""
    status, doc = ghost.get_json("/config")
    out = {"status": status, "nodes": [], "keys": []}
    if status != 200 or not isinstance(doc, dict):
        out["error"] = _error_of(status, doc)
        return out
    upstream = doc.get("upstream")
    for node in upstream if isinstance(upstream, list) else []:
        if isinstance(node, dict):
            out["nodes"].append({k: _str(node.get(k)) for k in ("name", "type", "addr", "user", "pass")})
    out["keys"] = sorted(k for k in doc if isinstance(k, str))
    return out


# ---- stats.read (§2, §4 end) --------------------------------------------------------------

def _processes(status, doc):
    out = {"status": status, "groups": [], "statsCount": 0}
    if status != 200 or not isinstance(doc, dict):
        out["error"] = _error_of(status, doc)
        return out
    out["statsCount"] = len(doc["stats"]) if isinstance(doc.get("stats"), list) else 0
    for g in doc.get("groups") if isinstance(doc.get("groups"), list) else []:
        if not isinstance(g, dict):
            continue
        children = [{"pid": _int(c.get("pid")), "name": _str(c.get("name")), "up": _num(c.get("up")),
                     "down": _num(c.get("down"))}
                    for c in (g.get("children") if isinstance(g.get("children"), list) else [])
                    if isinstance(c, dict)][:20]
        out["groups"].append({
            "name": _str(g.get("name")), "alias": _str(g.get("alias")), "path": _str(g.get("path")),
            "nodeName": _str(g.get("nodeName")), "activeCount": _int(g.get("activeCount")),
            "totalUp": _num(g.get("totalUp")), "totalDown": _num(g.get("totalDown")),
            # The point of this row: Ghost's own page gets each target's
            # environment; a plugin gets the group WITHOUT the key.
            "hasEnv": "env" in g,
            "keys": sorted(k for k in g if isinstance(k, str) and k != "icon"),
            "children": children,
        })
    return out


def _latencies(status, doc):
    out = {"status": status, "nodes": []}
    if status != 200 or not isinstance(doc, dict):
        out["error"] = _error_of(status, doc)
        return out
    out["avgHttpLatency"] = _num(doc.get("avg_http_latency"))
    out["retransmissionRate"] = _num(doc.get("retransmission_rate"))
    out["isTesting"] = doc.get("is_testing") is True
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), dict) else {}
    for node_id, n in sorted(nodes.items()):
        if isinstance(n, dict):
            udp = n.get("udp") if isinstance(n.get("udp"), dict) else None
            out["nodes"].append({"id": str(node_id), "latency": _num(n.get("latency")),
                                 "success": _int(n.get("success")), "attempts": _int(n.get("attempts")),
                                 "udp": _str(udp.get("state")) if udp else ""})
    return out


def _throughput(status, doc):
    out = {"status": status, "history": []}
    if status != 200 or not isinstance(doc, dict):
        out["error"] = _error_of(status, doc)
        return out
    hist = doc.get("history") if isinstance(doc.get("history"), list) else []
    out["history"] = [float(v) for v in hist if type(v) in (int, float)][-120:]
    return out


class StatsSection:
    """The three stats.read commands, cached for STATS_CACHE_SEC: the page
    polls, possibly from two tabs, and every call to Ghost spends the budget.
    Serving a two-second-old answer is cheaper than asking again."""

    def __init__(self, ghost, clock=time.monotonic):
        self._ghost = ghost
        self._clock = clock
        self._lock = threading.Lock()
        self._at = None
        self._value = None

    def get(self):
        with self._lock:
            if self._at is not None and self._clock() - self._at < STATS_CACHE_SEC:
                return self._value
            value = {
                "processes": _processes(*self._ghost.get_json("/process-stats")),
                "latencies": _latencies(*self._ghost.get_json("/latencies")),
                "throughput": _throughput(*self._ghost.get_json("/throughput-history")),
            }
            self._at, self._value = self._clock(), value
            return value


# ---- log.write (§5) ---------------------------------------------------------------------

def _ingest_answer(status, doc):
    out = {"status": status}
    if isinstance(doc, dict):
        for k in ("accepted", "rateDropped", "malformed"):
            out[k] = _int(doc.get(k))
        out["truncated"] = doc.get("truncated") is True
        if isinstance(doc.get("error"), str):
            out["error"] = doc["error"]
    elif status != 200:
        out["error"] = _error_of(status, doc)
    return out


# What this plugin ASKS for in the one-line write. Ghost overwrites three of
# them (src -> plugin, tag -> this plugin's id, plane -> control) and promotes
# debug to info: a plugin cannot make its line look like Ghost's own.
LOG_ASKED = {"level": "debug", "src": "ui", "tag": "Ghost", "plane": "data"}


def log_write(ghost, n):
    entry = dict(LOG_ASKED)
    entry["text"] = "showcase: log.write #%d (asked for src=ui, tag=Ghost, plane=data, level=debug)" % n
    entry["fields"] = {"showcase": "log.write", "n": str(n)}
    status, doc = ghost.post_json("/api/log-ingest", {"entries": [entry]})
    return {"asked": LOG_ASKED, "answer": _ingest_answer(status, doc)}


def log_burst(ghost, n):
    """LOG_BURST entries in ONE request: one request spends one call of the
    API budget; each entry spends one of the per-plugin LOG budget (5 a
    second, burst 50). The last entry has no text on purpose: Ghost skips it
    and counts it in `malformed` -- a bad entry never costs the good ones."""
    entries = [{"level": "info", "text": "showcase: burst %d, entry %d of %d" % (n, i + 1, LOG_BURST)}
               for i in range(LOG_BURST - 1)]
    entries.append({"level": "info", "text": ""})
    status, doc = ghost.post_json("/api/log-ingest", {"entries": entries})
    return {"sent": LOG_BURST, "answer": _ingest_answer(status, doc)}


# ---- plugin.assets (§6) -----------------------------------------------------------------

def fetch_own_icon(ghost, own_id):
    """(content type, bytes) of this plugin's own icon, or None. Ghost sniffs
    the bytes and answers image/png or image/webp; anything else -- or
    anything over the size limit -- is not relayed to the page."""
    reply = ghost.request("GET", "/api/plugins/icon?id=" + own_id)
    ctype = reply.ctype.split(";")[0].strip().lower()
    if reply.status == 200 and ctype in ICON_TYPES and 0 < len(reply.body) <= MAX_ICON_BYTES:
        return ctype, reply.body
    return None


def other_icon(ghost):
    """Another plugin's icon: 403 permission_denied -- plugin.assets is YOUR
    icon only."""
    reply = ghost.request("GET", "/api/plugins/icon?id=" + OTHER_PLUGIN_ID)
    doc = reply.json() if reply.status != 200 else None
    return {"id": OTHER_PLUGIN_ID, "status": reply.status, "error": _error_of(reply.status, doc)}


# ---- the gate's refusals (§1, §2.1) ----------------------------------------------------------

def gate_403(ghost):
    """POST /save-config: no v1 permission reaches it, so the gate answers 403
    permission_denied before the command runs. The body is deliberately NOT a
    configuration -- not even JSON -- so that, were the gate ever to let it
    through, config.save would refuse it ({"status":"error","error":"Invalid
    JSON"}) rather than change anything. A demonstration must not depend on
    the refusal it demonstrates."""
    reply = ghost.request("POST", "/save-config", b"showcase: not a configuration", "text/plain")
    return {"status": reply.status, "error": _error_of(reply.status, reply.json())}


# The two 401s are requests that are WRONG ON PURPOSE, so they are built here
# by hand rather than through GhostClient: ghost_api.py is the part a plugin
# copies unchanged, and it has no way to send a wrong header or an Origin.
# One GET /config each, bounded in time and size like any request, no retry
# (a 401 is an answer). A 401 has no identity, so it spends nobody's budget.

def _deliberately_refused(api, headers):
    host, port = api
    conn = http.client.HTTPConnection(host, port, timeout=ghost_api.REQUEST_TIMEOUT_SEC)
    try:
        conn.request("GET", "/config", headers=headers)
        resp = conn.getresponse()
        return resp.status, ghost_api.parse_json(resp.read(64 * 1024))
    except (OSError, http.client.HTTPException, ValueError):
        return 0, None
    finally:
        conn.close()


def gate_401_header(api, token):
    """The token under the HOST's header: identity is decided by the header's
    name, and under that name this token matches nothing -> 401. (Never under
    the session header either: same answer, and it is the one header a plugin
    must never send.)"""
    status, doc = _deliberately_refused(api, {"X-Ghost-Host-Token": token})
    return {"status": status, "error": _error_of(status, doc)}


def gate_401_origin(api, token, ui_origin):
    """The right header, but with this plugin's own page's Origin: 401 before
    the token is even looked at. This is why the page cannot call Ghost
    directly, token or not (spec-plugin-api §8)."""
    status, doc = _deliberately_refused(api, {ghost_api.PLUGIN_HEADER: token, "Origin": ui_origin})
    return {"status": status, "origin": ui_origin, "error": _error_of(status, doc)}
