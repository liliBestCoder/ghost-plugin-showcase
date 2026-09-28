"""events.read.control + events.read.data: Ghost's event stream
(docs/plugin-sdk/spec-plugin-api.md §3).

ONE stream, split here by plane. Which planes arrive is decided by Ghost from
the GRANTED permissions -- events.read.control gives System + Control,
events.read.data gives Data only, both give everything -- and the filtering
happens on the server: a plugin cannot ask for a plane it was not granted, and
there is no query parameter to choose. So a second stream would only be a
second copy of the same frames. It would also spend a slot: a plugin may have
at most TWO /events streams open at once, and the third is answered 429
(spec-limits.md §7.1). This plugin opens exactly one.

The Data plane is every DNS query and connection destination of every managed
program -- the user's browsing history. So it is OFF here until the user
switches it on in the page, and even then kept to DATA_PER_SEC events a second
and DATA_KEEP in memory: "rate-limit and drop yourself; never relay it as is"
(§3). Nothing from it is ever written to disk or logged.

The stream is standard server-sent events, parsed here to the letter: a
frame is the "data:" lines up to a blank line, ':' lines are comments (Ghost's
keepalives, one every 15 s), "id:" is the cursor a reconnect resumes from.
"""

import collections
import threading
import time

from ghost_api import parse_json

READ_TIMEOUT_SEC = 45            # Ghost sends a keepalive every 15 s
RECONNECT_DELAYS_SEC = (1, 2, 5, 10, 30)
MAX_LINE_BYTES = 64 * 1024
MAX_FRAME_BYTES = 256 * 1024
CONTROL_KEEP = 40
DATA_KEEP = 40
DATA_PER_SEC = 5
TEXT_KEEP_CHARS = 500
PLANES = ("system", "control", "data")


def clean_event(ev):
    """Only the ten wire keys (wire_event_json.h), each of its expected type:
    what reaches the page is data this process has looked at, not whatever
    arrived."""
    fields = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
    return {
        "seq": ev["seq"] if type(ev.get("seq")) is int else None,
        "ts": ev["ts"] if type(ev.get("ts")) in (int, float) else None,
        "plane": ev.get("plane") if ev.get("plane") in PLANES else "?",
        "level": ev.get("level") if ev.get("level") in ("debug", "info", "warn", "error") else "info",
        "src": str(ev.get("src", ""))[:32],
        "pid": ev["pid"] if type(ev.get("pid")) is int else 0,
        "targetId": str(ev.get("targetId", ""))[:64],
        "tag": str(ev.get("tag", ""))[:64],
        "fields": {str(k)[:64]: str(v)[:200] for k, v in list(fields.items())[:16]},
        "text": str(ev.get("text", ""))[:TEXT_KEEP_CHARS],
    }


class EventHub:
    """What the page reads about the stream. One lock."""

    def __init__(self, own_id, permissions, clock=time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self.own_id = own_id
        self.can_control = "events.read.control" in permissions
        self.can_data = "events.read.data" in permissions
        self.control = collections.deque(maxlen=CONTROL_KEEP)   # System + Control
        self.data = collections.deque(maxlen=DATA_KEEP)
        self.counts = dict.fromkeys(PLANES, 0)
        self.data_on = False
        self.data_ignored = 0       # arrived while the switch was off: counted, not kept
        self.data_shed = 0          # over DATA_PER_SEC while on: counted, not kept
        self._data_window = (0, 0)  # (second, events kept in it)
        self.connected = False
        self.last_error = ""
        self.last_seq = None
        self.opened = 0
        self.own_echo = None        # the latest line this plugin wrote, as it came back

    def add(self, raw_event, frame_id):
        ev = clean_event(raw_event)
        seq = frame_id if frame_id is not None else ev["seq"]
        with self._lock:
            if seq is not None:
                self.last_seq = seq
            plane = ev["plane"]
            if plane not in PLANES:
                return
            self.counts[plane] += 1
            if plane != "data":
                self.control.append(ev)
                if ev["src"] == "plugin" and ev["tag"] == self.own_id:
                    self.own_echo = ev
                return
            if not self.data_on:
                self.data_ignored += 1
                return
            second = int(self._clock())
            start, kept = self._data_window
            if second != start:
                start, kept = second, 0
            if kept >= DATA_PER_SEC:
                self.data_shed += 1
            else:
                kept += 1
                self.data.append(ev)
            self._data_window = (start, kept)

    def set_data(self, on):
        with self._lock:
            self.data_on = bool(on)
            if not self.data_on:
                self.data.clear()          # switched off: forget what was shown

    def set_connected(self, connected, error=None):
        with self._lock:
            self.connected = connected
            if connected:
                self.opened += 1
            if error is not None:
                self.last_error = error

    def resume_after(self):
        with self._lock:
            return self.last_seq

    def view(self):
        with self._lock:
            return {"connected": self.connected, "lastError": self.last_error, "opened": self.opened,
                    "streamsOpen": 1 if self.connected else 0, "maxStreams": 2,
                    "canControl": self.can_control, "canData": self.can_data,
                    "counts": dict(self.counts), "control": list(self.control),
                    "dataOn": self.data_on, "data": list(self.data), "dataIgnored": self.data_ignored,
                    "dataShed": self.data_shed, "dataPerSec": DATA_PER_SEC, "ownEcho": self.own_echo}


def read_frames(resp, on_event):
    """Reads SSE frames from `resp` until it ends. Lines and frames are
    bounded: an oversize one is skipped whole, never cut and parsed."""
    data, size, frame_id, skipping = [], 0, None, False
    while True:
        raw = resp.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
            skipping = True            # the rest of this line is still coming
            continue
        if skipping:
            skipping = False           # this is the tail of the oversize line
            data, size, frame_id = [], 0, None
            continue
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line == "":
            if data and size <= MAX_FRAME_BYTES:
                ev = parse_json("\n".join(data).encode("utf-8"))
                if isinstance(ev, dict):
                    on_event(ev, int(frame_id) if frame_id and frame_id.isdigit() else None)
            data, size, frame_id = [], 0, None
            continue
        if line.startswith(":"):
            continue                   # a comment: Ghost's keepalive
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data.append(value)
            size += len(value)
        elif field == "id":
            frame_id = value


def events_loop(client, hub, stop):
    """For as long as `stop` (a threading.Event) is not set. A refusal
    (401/403/429) or a broken connection goes into lastError and is retried
    after a growing pause -- it never ends the plugin. A reconnect resumes with
    ?after=<last id>, so nothing in between is lost or repeated."""
    failures = 0
    while not stop.is_set():
        try:
            conn, resp = client.open_events(hub.resume_after(), READ_TIMEOUT_SEC)
            try:
                if resp.status != 200:
                    resp.read(64 * 1024)
                    hub.set_connected(False, "HTTP %d" % resp.status)
                    failures += 1
                else:
                    hub.set_connected(True, "")
                    failures = 0
                    read_frames(resp, hub.add)
                    hub.set_connected(False)
            finally:
                conn.close()
        except (OSError, ValueError) as e:
            hub.set_connected(False, type(e).__name__)
            failures += 1
        except Exception as e:           # http.client errors and anything else:
            hub.set_connected(False, type(e).__name__)   # never end the thread
            failures += 1
        stop.wait(RECONNECT_DELAYS_SEC[min(max(failures - 1, 0), len(RECONNECT_DELAYS_SEC) - 1)])
