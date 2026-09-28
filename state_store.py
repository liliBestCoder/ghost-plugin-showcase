"""The plugin's private data directory (spec-host-protocol.md §3.1: `dataDir`).

Hosted, Ghost hands over `plugins\\<id>\\.data\\`: already created, KEPT across
upgrades (it is not inside the versioned package directory), deleted only on
uninstall. Standalone, the plugin picks its own, %LOCALAPPDATA%\\<id>\\ -- never
Ghost's directory, which Ghost owns and deletes on uninstall (§3.0).

What is kept here is small and shows the three things a data directory is
for: it survives a restart (the start counter), an upgrade (the versions
seen), and a crash (the restart demonstration's bookkeeping).

Two habits worth copying:
  * write to a temporary file and os.replace() it over the old one, so a crash
    in the middle of a write leaves the old file, never half a file;
  * read defensively: a file that is missing, too large, not JSON, or has a
    field of the wrong type is started over (and says so) -- never an
    exception on the way up.
"""

import json
import os
import threading
import time

STATE_FILE = "state.json"
MAX_STATE_BYTES = 64 * 1024
MAX_VERSIONS = 10
RESTART_WINDOW_SEC = 120        # a start this soon after a demo exit is its restart
BUDGET_WINDOW_SEC = 600         # the host's restart budget resets after 10 min stable


def fresh():
    return {"v": 1, "starts": 0, "firstStart": None, "lastStart": None, "lastStop": None,
            "versions": [], "restartRequestedAt": None, "lastRestart": None, "demoExits": []}


def _number_or_none(v):
    return v if type(v) in (int, float) else None


def sanitize(doc):
    """(state, problem): a state with every field of its type, and "" or why
    the document could not be used as it was."""
    if not isinstance(doc, dict) or doc.get("v") != 1 or type(doc.get("v")) is not int:
        return fresh(), "unknown or missing version"
    s = fresh()
    s["starts"] = doc["starts"] if type(doc.get("starts")) is int and doc["starts"] >= 0 else 0
    for key in ("firstStart", "lastStart", "lastStop", "restartRequestedAt"):
        s[key] = _number_or_none(doc.get(key))
    versions = doc.get("versions")
    s["versions"] = [v for v in versions if isinstance(v, str)][-MAX_VERSIONS:] if isinstance(versions, list) else []
    exits = doc.get("demoExits")
    s["demoExits"] = [t for t in exits if type(t) in (int, float)][-10:] if isinstance(exits, list) else []
    last = doc.get("lastRestart")
    if isinstance(last, dict) and _number_or_none(last.get("delaySec")) is not None:
        s["lastRestart"] = {"delaySec": last["delaySec"], "at": _number_or_none(last.get("at"))}
    return s, ""


class StateStore:
    def __init__(self, directory, version, clock=time.time):
        self.path = os.path.join(directory, STATE_FILE)
        self.version = version
        self._clock = clock
        self._lock = threading.Lock()
        self.problem = ""               # why the file on disk was not used, if it was not
        self.write_error = ""
        self.state = fresh()

    def load(self):
        try:
            if os.path.getsize(self.path) > MAX_STATE_BYTES:
                self.state, self.problem = fresh(), "state.json is larger than %d bytes" % MAX_STATE_BYTES
                return
            with open(self.path, "rb") as f:
                raw = f.read(MAX_STATE_BYTES + 1)
        except FileNotFoundError:
            self.state, self.problem = fresh(), ""
            return
        except OSError as e:
            self.state, self.problem = fresh(), "state.json could not be read (%s)" % type(e).__name__
            return
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError:
            doc = None
        self.state, self.problem = sanitize(doc)

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=1)
            os.replace(tmp, self.path)         # atomic on the same volume
            self.write_error = ""
        except OSError as e:
            self.write_error = type(e).__name__

    def record_start(self):
        """Called once per process start, before anything is shown."""
        now = self._clock()
        with self._lock:
            s = self.state
            s["starts"] += 1
            s["firstStart"] = s["firstStart"] or now
            s["lastStart"] = now
            if self.version not in s["versions"]:
                s["versions"] = (s["versions"] + [self.version])[-MAX_VERSIONS:]
            asked = s["restartRequestedAt"]
            if asked is not None and 0 <= now - asked <= RESTART_WINDOW_SEC:
                # The previous process exited on purpose (the lifecycle demo)
                # and this start is the host's restart of it.
                s["lastRestart"] = {"delaySec": round(now - asked, 1), "at": now}
            s["restartRequestedAt"] = None
            self._save()

    def record_stop(self):
        with self._lock:
            self.state["lastStop"] = self._clock()
            self._save()

    def record_demo_exit(self):
        """The lifecycle demo is about to exit on purpose; returns how many
        such exits fall inside the host's budget window, this one included."""
        now = self._clock()
        with self._lock:
            s = self.state
            s["restartRequestedAt"] = now
            s["demoExits"] = [t for t in s["demoExits"] if now - t < BUDGET_WINDOW_SEC][-9:] + [now]
            self._save()
            return len(s["demoExits"])

    def reset(self):
        with self._lock:
            self.state = fresh()
            self.state["starts"] = 1          # this process is still one start
            self.state["firstStart"] = self.state["lastStart"] = self._clock()
            self.state["versions"] = [self.version]
            self.problem = ""
            self._save()

    def view(self):
        now = self._clock()
        with self._lock:
            s = dict(self.state)
            s["recentDemoExits"] = len([t for t in s["demoExits"] if now - t < BUDGET_WINDOW_SEC])
            return {"state": s, "file": self.path, "problem": self.problem, "writeError": self.write_error}
