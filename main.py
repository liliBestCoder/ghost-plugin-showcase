#!/usr/bin/env python3
"""Plugin Showcase -- the reference Ghost Proxifier plugin.

It does every v1 thing a plugin can do, each in its own section of its page,
so that a developer can see it working and find the code for it:

  file              what is in it                                spec
  ----------------  -------------------------------------------  -----------------------------
  protocol.py       hosted or standalone, the handshake,        spec-host-protocol §2.1, §3
                    the stop event
  ghost_api.py      the one object holding the token; timeouts,  spec-plugin-api §1
                    429 backoff, a safe JSON parse
  events.py         /events: Control/System and Data planes      spec-plugin-api §3
  sections.py       config.read, stats.read, log.write,          spec-plugin-api §2, §4-§6
                    plugin.assets, and the gate's refusals
  state_store.py    the private data directory                   spec-host-protocol §3.1
  ui_server.py      the page server behind uiUrl                 spec-plugin-api §8
  main.py (here)    wiring: which section answers which route

The page (ui/) talks ONLY to this process; this process holds the token and
talks to Ghost. Standard library only; Python 3.9 or later
(manifest.json runtime.minVersion).
"""

import os
import sys
import threading
import time

# Before this plugin's own modules are imported: no __pycache__ next to the
# code. Installed, that directory is Ghost's package directory -- a plugin
# writes only in its dataDir.
sys.dont_write_bytecode = True

import events                                  # noqa: E402
import ghost_api                               # noqa: E402
import protocol                                # noqa: E402
import sections                                # noqa: E402
import state_store                             # noqa: E402
import ui_server                               # noqa: E402
from ui_server import json_result              # noqa: E402

PLUGIN_ID = "com.ghostproxifier.showcase"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_KEYS = ("GHOST_PLUGIN_ID", "GHOST_PLUGIN_DIR", "GHOST_PLUGIN_DATA_DIR", "GHOST_PLUGIN_API_BASE",
            "GHOST_PLUGIN_STOP_EVENT", "GHOST_PLUGIN_PYTHON", "GHOST_PLUGIN_NODE")
# The environment variable -> the handshake field that carries the same value
# (spec-host-protocol §2: "one value, two ways to read it").
ENV_TO_FIELD = {"GHOST_PLUGIN_ID": "pluginId", "GHOST_PLUGIN_DIR": "pluginDir",
                "GHOST_PLUGIN_DATA_DIR": "dataDir", "GHOST_PLUGIN_API_BASE": "apiBase",
                "GHOST_PLUGIN_STOP_EVENT": "stopEvent"}
DEMO_EXIT_CODE = 3


def read_manifest():
    """This plugin's own manifest.json, for the page to compare with what
    reached it (args, runtime). Bounded, and never fatal."""
    path = os.path.join(HERE, "manifest.json")
    try:
        with open(path, "rb") as f:
            doc = ghost_api.parse_json(f.read(64 * 1024 + 1), 64 * 1024)
    except OSError:
        doc = None
    return doc if isinstance(doc, dict) else {}


def runtime_view(manifest):
    declared = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
    want = str(declared.get("minVersion", ""))
    try:
        need = tuple(int(p) for p in want.split("."))
    except ValueError:
        need = ()
    return {"declared": {"kind": str(declared.get("kind", "")), "minVersion": want},
            "python": "%d.%d.%d" % sys.version_info[:3], "executable": sys.executable,
            "ghostPluginPython": os.environ.get("GHOST_PLUGIN_PYTHON"),
            "meets": bool(need) and sys.version_info[:len(need)] >= need}


def license_view(hs):
    """The declaration the host passes (spec-host-protocol §3.1,
    spec-license.md §7). Shown, never enforced here: Ghost is the enforcement
    point -- without a licence it never starts the plugin at all."""
    lic = hs.get("license") if hs else None
    if not isinstance(lic, dict):
        return {"present": False}
    return {"present": True, "licensed": lic.get("licensed") is True, "trial": lic.get("trial") is True,
            "expiresAt": lic["expiresAt"] if isinstance(lic.get("expiresAt"), str) else None}


class App:
    """Everything one run holds. `hs` is None standalone."""

    def __init__(self, hs, data_dir, argv, stop_event=None):
        self.hs = hs
        self.hosted = hs is not None
        self.manifest = read_manifest()
        self.version = str(self.manifest.get("version", "?"))
        # Declared: what manifest.json asks for (one list, in one file). Granted:
        # what the user confirmed, from the handshake -- the only set that counts.
        perms = self.manifest.get("permissions")
        self.declared = [p for p in perms if isinstance(p, str)] if isinstance(perms, list) else []
        self.permissions = [p for p in (hs or {}).get("permissions", []) if isinstance(p, str)]
        self.lang = hs.get("lang") if hs and hs.get("lang") in ("zh", "en") else None
        self.argv = list(argv)
        self.store = state_store.StateStore(data_dir, self.version)
        self.store.load()
        self.store.record_start()
        self.stop = threading.Event()
        self.stop_event = stop_event
        self.stop_event_error = ""
        self.hub = events.EventHub(PLUGIN_ID, self.permissions)
        self.ghost = None
        self.api = None                  # (host, port) of apiBase, hosted only
        self.stats = None
        self.icon = None
        self.log_n = 0
        self.burst_n = 0
        self._lock = threading.Lock()
        self.receipt = None
        if self.hosted:
            self.api = protocol.split_api_base(hs["apiBase"])
            self.ghost = ghost_api.GhostClient(self.api[0], self.api[1], hs["token"])
            self.stats = sections.StatsSection(self.ghost)
        # frame-ancestors: exactly Ghost's own origin -- the one its plugins
        # page is served from -- and nothing else. Standalone, nobody.
        self.frame_ancestor = self.ghost.api_base if self.hosted else "'none'"
        self.ui = ui_server.UiServer(self.get_routes(), self.post_routes(), self.frame_ancestor)

    # ---- routes -----------------------------------------------------------------------

    def get_routes(self):
        return {"api/status": lambda: json_result(self.status()),
                "api/protocol": lambda: json_result(self.protocol_view()),
                "api/events": lambda: json_result(self.hub.view()),
                "api/state": lambda: json_result(self.store.view()),
                "api/config": self.needs_ghost(lambda: sections.config_section(self.ghost)),
                "api/stats": self.needs_ghost(lambda: self.stats.get()),
                "api/icon": self.icon_file}

    def post_routes(self):
        return {"api/events/data": lambda body: json_result(self.set_data(body)),
                "api/log": self.needs_ghost(self.write_log, body=True),
                "api/log/burst": self.needs_ghost(self.write_burst, body=True),
                "api/assets/other": self.needs_ghost(lambda _: sections.other_icon(self.ghost), body=True),
                "api/gate/403": self.needs_ghost(lambda _: sections.gate_403(self.ghost), body=True),
                "api/gate/401-header": self.needs_ghost(
                    lambda _: sections.gate_401_header(self.api, self.hs["token"]), body=True),
                "api/gate/401-origin": self.needs_ghost(
                    lambda _: sections.gate_401_origin(self.api, self.hs["token"], self.ui.origin), body=True),
                "api/state/reset": lambda body: json_result(self.reset_state()),
                "api/restart": self.restart}

    def needs_ghost(self, fn, body=False):
        """Standalone there is no token and no Ghost (spec-host-protocol
        §3.0): the section answers "standalone" and the page shows it
        disabled -- not broken."""
        if body:
            return lambda b: json_result({"error": "standalone"} if self.ghost is None else fn(b))
        return lambda: json_result({"error": "standalone"} if self.ghost is None else fn())

    # ---- what the page reads ------------------------------------------------------------

    def status(self):
        view = {"hosted": self.hosted, "lang": self.lang, "pluginId": PLUGIN_ID, "version": self.version,
                "permissions": self.permissions, "declared": list(self.declared),
                "icon": self.icon is not None, "frameAncestor": self.frame_ancestor}
        view["client"] = self.ghost.counters() if self.ghost else None
        return view

    def protocol_view(self):
        env = {k: os.environ.get(k) for k in ENV_KEYS}
        hs = self.hs or {}
        token = hs.get("token")
        return {
            "mode": "hosted" if self.hosted else "standalone",
            "handshake": protocol.masked(self.hs) if self.hs else None,
            "receipt": self.receipt,
            "argv": self.argv,
            "manifestArgs": self.manifest.get("args") if isinstance(self.manifest.get("args"), list) else [],
            "env": env,
            "envMatches": {k: env[k] == hs.get(f) for k, f in ENV_TO_FIELD.items()} if self.hosted else {},
            # The token is handed over on stdin only; the environment (which
            # every child process inherits) must not carry it. Checked, not
            # assumed -- and only the answer is shown.
            "tokenInEnv": bool(token) and any(v == token for v in os.environ.values()),
            "runtime": runtime_view(self.manifest),
            "license": license_view(self.hs),
            "settings": hs.get("settings") if self.hosted else None,
            "stopEvent": {"name": hs.get("stopEvent"), "error": self.stop_event_error} if self.hosted else None,
        }

    def icon_file(self):
        with self._lock:
            icon = self.icon
        if icon is None:
            return json_result({"error": "not_found"}, 404)
        return 200, icon[1], icon[0]

    # ---- what the page asks for -----------------------------------------------------------

    def set_data(self, body):
        on = body.get("on")
        if not isinstance(on, bool):
            return {"error": "on must be true or false"}
        if not self.hub.can_data:
            return {"error": "events.read.data is not granted"}
        self.hub.set_data(on)
        return {"dataOn": on}

    def write_log(self, _body):
        with self._lock:
            self.log_n += 1
            n = self.log_n
        return sections.log_write(self.ghost, n)

    def write_burst(self, _body):
        with self._lock:
            self.burst_n += 1
            n = self.burst_n
        return sections.log_burst(self.ghost, n)

    def reset_state(self):
        self.store.reset()
        return self.store.view()

    def restart(self, body):
        """The lifecycle demonstration: exit with a non-zero code on purpose.
        The host reads that as a crash and restarts the plugin after 1, 4, 9
        seconds (spec-limits.md §1); a fourth exit inside the budget ends in
        plugin_restart_exhausted and it stays stopped until the user enables
        it again. Only when asked with {"confirm": true} -- the page shows the
        consequences first."""
        if not self.hosted:
            return json_result({"error": "standalone"})
        if body.get("confirm") is not True:
            return json_result({"error": "confirm must be true"}, 400)
        used = self.store.record_demo_exit()
        threading.Thread(target=self._exit_soon, daemon=True).start()
        return json_result({"exiting": True, "exitCode": DEMO_EXIT_CODE, "recentExits": used})

    def _exit_soon(self):
        time.sleep(0.5)                  # let the answer reach the page first
        os._exit(DEMO_EXIT_CODE)         # no cleanup: this is what a crash looks like

    # ---- running ------------------------------------------------------------------------------

    def fetch_icon(self):
        icon = sections.fetch_own_icon(self.ghost, PLUGIN_ID)
        with self._lock:
            self.icon = icon

    def watch_stop(self):
        """PROTOCOL: the graceful stop. Flush what must survive, close the
        page server; main() then exits 0 -- inside the host's 3 s."""
        if self.stop_event is not None and self.stop_event.wait():
            self.shut_down()

    def shut_down(self):
        self.stop.set()
        self.store.record_stop()
        self.ui.shutdown()

    def run(self):
        if self.hosted:
            threading.Thread(target=self.fetch_icon, daemon=True).start()
            threading.Thread(target=events.events_loop, args=(self.ghost, self.hub, self.stop), daemon=True).start()
            threading.Thread(target=self.watch_stop, daemon=True).start()
        self.ui.serve()


# ---- PROTOCOL: the two modes (spec-host-protocol.md §3.0) --------------------------------------

def run_hosted(argv):
    hs, why = protocol.read_handshake(sys.stdin.buffer, PLUGIN_ID)
    if hs is None:
        # ok:false = plugin_declined: the host does not restart it. The reason
        # does not reach Ghost's log (only the code does); run standalone to see it.
        protocol.write_line({"v": 1, "ok": False, "error": why})
        return 1
    stop_event = protocol.StopEvent(hs["stopEvent"])
    stop_error = stop_event.open()
    app = App(hs, hs["dataDir"], argv, stop_event)
    app.stop_event_error = stop_error or ""
    # The receipt: exactly {v, ok, uiUrl}. After it, stdout is never written
    # again -- the host reads one line and discards the rest.
    app.receipt = {"v": 1, "ok": True, "uiUrl": app.ui.url}
    protocol.write_line(app.receipt)
    # If the event could not be opened there is no graceful stop: wait() then
    # answers False at once and nothing else changes. Do NOT exit because of
    # it -- the host would read that as a crash and restart the plugin; it
    # ends the job itself when it stops the plugin.
    app.run()
    return 0


def run_standalone(argv):
    """No Ghost, no token, and stdin is left alone (in a terminal readline()
    would block forever). The page works; the Ghost-backed sections say so."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(base, PLUGIN_ID)
    os.makedirs(data_dir, exist_ok=True)
    app = App(None, data_dir, argv)
    print(app.ui.url, flush=True)
    if "--open" in argv:
        import webbrowser
        webbrowser.open(app.ui.url)
    try:
        app.run()
    except KeyboardInterrupt:
        app.store.record_stop()
    return 0


def main(argv):
    if protocol.is_hosted(os.environ):
        return run_hosted(argv)
    return run_standalone(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
