"""PROTOCOL -- the part every plugin does the same way (spec-host-protocol.md).

Three things, and nothing else in this file:

  1. hosted or standalone?  `GHOST_PLUGIN_ID` in the environment decides
     (§3.0) -- never "is stdin readable": in a terminal stdin is always
     readable and readline() would block forever.
  2. the handshake: one JSON line in on stdin, one JSON line out on stdout
     (§3.1, §3.2). Checked field by field; anything off is answered with
     {"v":1,"ok":false,"error":...} and the process exits. The host reads that
     as `plugin_declined` and does NOT restart it.
  3. the stop event: the host sets a named event to ask for a graceful stop
     (§2, §2.1). Its name comes from the handshake. Never build it yourself:
     the process the host started may be a launcher (cmd.exe, a venv's
     python.exe) whose pid is not yours, and the names would never meet.

Copy this file as it is into your own plugin; change PLUGIN_ID in main.py
(read_handshake refuses a handshake for any other id).
"""

import json
import re
import sys
import urllib.parse

PROTOCOL_VERSION = 1

# The host writes one line; 64 KB is far more than a handshake needs and small
# enough that a runaway writer cannot make this process hold gigabytes.
MAX_HANDSHAKE_BYTES = 64 * 1024

# The token goes into an HTTP header, so it must be header-safe. This is the
# host's own rule for the tokens it mints (spec-host-protocol.md §1): a value
# with CR/LF in it would be a header injection, and refusing it here means no
# later line of this plugin ever has to think about it.
TOKEN_RE = re.compile(r"\A[0-9A-Za-z{}-]{1,128}\Z")

# Field -> the Python type it must have. `v` and `token` are checked apart.
REQUIRED_STRINGS = ("pluginId", "pluginDir", "dataDir", "apiBase", "stopEvent")
OPTIONAL_TYPES = {"permissions": list, "settings": dict, "license": dict, "lang": str}


def is_hosted(environ):
    """§3.0: the host sets GHOST_PLUGIN_ID; nobody else does."""
    return "GHOST_PLUGIN_ID" in environ


def write_line(obj, out=None):
    """One JSON line, UTF-8, flushed.

    The flush is not optional: on a pipe Python's stdout is BLOCK buffered, so
    without it the host never sees the line and reports a handshake timeout --
    the symptom is "the plugin fails to start", not "you forgot to flush"."""
    out = out or sys.stdout.buffer
    out.write((json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()


def split_api_base(api_base):
    """(host, port) of an http://127.0.0.1:<port> address, or None.

    The token is sent to exactly this address, so it must be loopback: a
    handshake naming anything else is refused rather than trusted."""
    parts = urllib.parse.urlsplit(api_base)
    try:
        port = parts.port              # ValueError for a port outside 0..65535
    except ValueError:
        return None
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not port:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username or parts.password:
        return None
    return "127.0.0.1", port


def check_handshake(line, expected_id):
    """(handshake dict, None) or (None, why). `line` is the raw bytes read."""
    if not line.endswith(b"\n"):
        return None, "the handshake line is missing or too long"
    try:
        # UTF-8 bytes, not text mode: stdin's text encoding on Windows is the
        # ANSI code page, and a Chinese path in dataDir would be mangled.
        hs = json.loads(line.decode("utf-8"), parse_constant=_no_constants)
    except ValueError:
        return None, "the handshake is not a JSON line"
    # `type(...) is int`: in Python True == 1 and 1.0 == 1, and neither is the
    # integer 1 the protocol says (§6: an unknown v is refused, not guessed).
    if not isinstance(hs, dict) or type(hs.get("v")) is not int or hs["v"] != PROTOCOL_VERSION:
        return None, "unsupported protocol version"
    for key in REQUIRED_STRINGS:
        if not isinstance(hs.get(key), str) or not hs[key]:
            return None, "the handshake has no %s" % key
    if hs["pluginId"] != expected_id:
        return None, "this handshake is for another plugin"
    if not isinstance(hs.get("token"), str) or not TOKEN_RE.match(hs["token"]):
        return None, "the token is missing or not header-safe"
    if split_api_base(hs["apiBase"]) is None:
        return None, "apiBase is not a loopback http address"
    for key, kind in OPTIONAL_TYPES.items():
        if key in hs and not isinstance(hs[key], kind):
            return None, "%s has the wrong type" % key
    if not all(isinstance(p, str) for p in hs.get("permissions", [])):
        return None, "permissions must be strings"
    return hs, None


def read_handshake(stream, expected_id):
    """Reads ONE line (bounded) from `stream` (stdin's bytes) and checks it."""
    return check_handshake(stream.readline(MAX_HANDSHAKE_BYTES), expected_id)


def masked(hs):
    """The handshake as it may be SHOWN: every field, the token replaced.

    What replaces it says what the plugin did with it, not any of its
    characters -- not even a prefix: part of a secret is still a secret."""
    view = dict(hs)
    if "token" in view:
        view["token"] = "(hidden: kept in this process's memory only)"
    return view


def _no_constants(name):
    # json.loads accepts NaN, Infinity and -Infinity by default; the protocol
    # is JSON, which has none of them.
    raise ValueError("not JSON: " + name)


# ---- the stop event -----------------------------------------------------------------

SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0


class StopEvent:
    """The host's named event, opened by the name the handshake gave.

    open() -> None on success, or the reason it could not be opened. Without
    it there is no graceful stop: the host ends the job after its timeout
    (kGracefulStopMs, 3 s) -- the plugin must NOT exit on its own because of
    this, since the host would read that as a crash and restart it."""

    def __init__(self, name):
        self.name = name
        self._handle = None
        self._k32 = None

    def open(self):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenEventW.restype = wintypes.HANDLE
        k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = k32.OpenEventW(SYNCHRONIZE, False, self.name)
        if not handle:
            return "OpenEventW failed with error %d" % ctypes.get_last_error()
        self._k32, self._handle = k32, handle
        return None

    def wait(self, timeout_ms=0xFFFFFFFF):
        """True once the host has set the event."""
        if self._handle is None:
            return False
        return self._k32.WaitForSingleObject(self._handle, timeout_ms) == WAIT_OBJECT_0
