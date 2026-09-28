# Changelog

All notable changes to the Plugin Showcase (`com.ghostproxifier.showcase`).
Versions follow the manifest's `version`; each release is the tag `v<version>`
(spec-release.md §3.1).

## 1.0.0 -- 2026-09-28

First release: the reference implementation of every v1 plugin capability.

- The six permissions, each used by its own section: `events.read.control`
  and `events.read.data` (one `/events` stream split by plane; the Data plane
  off by default and capped at 5 events a second), `stats.read`
  (`/process-stats`, `/latencies`, `/throughput-history`, cached 2 s),
  `config.read` (the redacted configuration), `log.write` (one line, and a
  10-entry burst) and `plugin.assets` (its own icon; another plugin's is a 403).
- The gate's refusals: 403 `permission_denied` (`POST /save-config` with a
  body that is not JSON), 401 for the token under the wrong header and for a
  foreign `Origin`, and exponential backoff on 429 `rate_limited`.
- The host protocol shown field by field: the handshake (token masked), the
  receipt, the manifest's `args` in `argv`, the `GHOST_PLUGIN_*` environment,
  the runtime, the licence declaration, the stop event; malformed handshakes
  answered `ok:false`.
- The private data directory: a start counter and the versions seen, written
  atomically; kept across restarts and upgrades.
- The lifecycle: an exit on purpose (code 3) so the host's 1/4/9 s restart
  can be watched.
- Works embedded in Ghost's plugins page and top-level; light/dark follows
  the operating system (v1 gives a plugin no way to learn Ghost's own theme),
  the language follows the handshake; runs standalone without Ghost.
