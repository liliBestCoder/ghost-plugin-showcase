# 插件能力示例（Plugin Showcase）

`com.ghostproxifier.showcase` —— Ghost Proxifier 的**官方参考插件**。v1 插件能做的每一件事，它都在自己页面的一个区块里做一遍，并标出对应的规范章节与代码位置。想写插件，从这里抄起。

Python 标准库、Python ≥ 3.9，没有任何第三方依赖。这个目录就是将来独立仓库 `liliBestCoder/ghost-plugin-showcase` 的全部内容。

> 规范在 SDK 仓库的 [`docs/plugin-sdk/`](https://github.com/liliBestCoder/ghost-plugin-sdk/blob/4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a/docs/plugin-sdk/README.md)；下文的 `spec-*.md` 都指那里。（链接钉在 SDK 仓库 `liliBestCoder/ghost-plugin-sdk` 的提交 `4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a`，与 `release.yml` 的 `SDK_REPO`/`SDK_REF` 相同。）

## 它演示什么

页面只和插件自己的进程说话（同源）；插件进程持有 token、去调 Ghost。**token 从不进页面**，也不上命令行、不进环境变量、不打印、不写日志、不落盘。

| 能力 | 页面区块 | 规范 | 代码 |
|---|---|---|---|
| 判断有没有宿主（`GHOST_PLUGIN_ID`） | 宿主协议与握手 | `spec-host-protocol` §3.0 | `protocol.py` `is_hosted` |
| 握手：逐字段校验，不对就回 `ok:false` | 宿主协议与握手 | `spec-host-protocol` §3.1–§3.2、§6 | `protocol.py` `check_handshake` |
| 回执恰好 `{v, ok, uiUrl}`，写完即 flush | 宿主协议与握手 | `spec-host-protocol` §3.2 | `protocol.py` `write_line`、`main.py` `run_hosted` |
| 清单 `args` 到达 `argv` | 宿主协议与握手 | `spec-manifest` §2 | `main.py` `protocol_view` |
| `GHOST_PLUGIN_*` 环境变量（与握手同值；token 不在其中，实测） | 宿主协议与握手 | `spec-host-protocol` §2 | `main.py` `protocol_view` |
| `runtime {kind: python, minVersion}` 与实际解释器 | 宿主协议与握手 | `spec-manifest` §4 | `main.py` `runtime_view` |
| 停止事件：按握手给的名字等待，优雅退出 | 私有数据目录（上次优雅停止） | `spec-host-protocol` §2.1 | `protocol.py` `StopEvent`、`main.py` `watch_stop` |
| 六个权限（声明 vs 授予） | 六个权限 | `spec-plugin-api` §2 | `manifest.json` |
| `events.read.control`：System + Control 平面 | 事件流：Control / System | `spec-plugin-api` §3 | `events.py` |
| `events.read.data`：Data 平面（默认关、每秒至多 5 条、只在内存） | 事件流：Data | `spec-plugin-api` §3 | `events.py` `EventHub` |
| `stats.read`：`/process-stats`（`env` 被删）、`/latencies`、`/throughput-history` | 统计 | `spec-plugin-api` §2、§4 末 | `sections.py` `StatsSection` |
| `config.read`：`user`/`pass` 为 `***`，空的保持空 | 配置 | `spec-plugin-api` §4 | `sections.py` `config_section` |
| `log.write`：`src`/`tag`/`plane` 被强制改写、`debug`→`info`；一次 10 条看条目预算 | 写日志 | `spec-plugin-api` §5、`spec-limits` §7 | `sections.py` `log_write`、`log_burst` |
| `plugin.assets`：自己的图标；读别人的 → 403 | 自己的图标 | `spec-plugin-api` §6 | `sections.py` `fetch_own_icon`、`other_icon` |
| 403 `permission_denied`（`POST /save-config`，请求体不是 JSON） | 闸门 | `spec-plugin-api` §2.1 | `sections.py` `gate_403` |
| 401：token 放错头、带了外源 `Origin` | 闸门 | `spec-plugin-api` §1、§8 | `sections.py` `gate_401_header`、`gate_401_origin` |
| 429 `rate_limited`：指数退避（0.25/0.5/1/2 秒） | 闸门 | `spec-limits` §7.1 | `ghost_api.py` `GhostClient.request` |
| 私有数据目录：启动计数、见过的版本，临时文件 + 原子替换 | 私有数据目录 | `spec-host-protocol` §3.1 | `state_store.py` |
| 崩溃重拉：故意以代码 3 退出，看宿主 1/4/9 秒重拉 | 生命周期 | `spec-host-protocol` §2、`spec-limits` §1 | `main.py` `App.restart` |
| 许可声明 `license {licensed, trial, expiresAt}`（本插件免费） | 许可声明 | `spec-host-protocol` §3.1、`spec-license` §7 | `main.py` `license_view` |
| 嵌入：`frame-ancestors` 恰好是 Ghost 的源；深浅色跟随**操作系统**（`prefers-color-scheme`——Ghost 的 WebView 报告的是 Windows 的设置，v1 没有途径让插件得知 Ghost 自己的主题）；语言跟随握手的 `lang` | 嵌入、主题与安全习惯 | `spec-manifest` §5、`spec-plugin-api` §8 | `ui_server.py`、`ui/` |
| 独立运行：没有 Ghost 时相关区块停用而不是出错 | 顶部横幅 | `spec-host-protocol` §3.0 | `main.py` `needs_ghost`、`run_standalone` |
| 页面服务的安全习惯：随机 128 位前缀、Host 校验、POST 的 Origin 校验、CSP、只用 `textContent` | 嵌入、主题与安全习惯 | `spec-plugin-api` §8 | `ui_server.py`、`ui/app.js` |

`/events` 只开一条：服务端按**已授予**的权限决定发哪些平面，插件选不了，第二条流只会是同样帧的第二份；而每个插件至多同时开 2 条，第 3 条答 429。

## 独立运行

```bash
python main.py --open      # 打印页面地址并用浏览器打开；Ctrl+C 退出
```

没有 `GHOST_PLUGIN_ID` 就是独立模式：不读 stdin、没有 token。需要 Ghost 的区块显示为停用；数据目录区块照常工作（存在 `%LOCALAPPDATA%\com.ghostproxifier.showcase\`）。

## 现场演示（在 SDK 仓库里）

```powershell
pwsh -File examples\demo\run-showcase-demo.ps1                 # 默认 600 秒，中文
pwsh -File examples\demo\run-showcase-demo.ps1 -Seconds 120 -Lang en
```

它启动 x64 测试构建里的 `bin\ghost_plugin_demo.exe`：两把**一次性**钥匙签名、假网络、真 `PluginService` 安装、真宿主 `ghost_plugin_host.exe`、真闸门（临时端口、临时数据目录）。内存里有一份演示配置（一个带凭据的上游、一个凭据为空的上游）、一个带 `env` 的被管目标，每 2 秒一条 Control 事件与一条 Data 事件。它打印插件页地址；点「生命周期」区块的退出按钮，控制台会打印宿主重拉后的新地址。不碰 `%LOCALAPPDATA%\GhostProxifier`、真注册表与 23551/23552 端口。

## 发版与上架

见 SDK 的 [`publish-walkthrough.md`](https://github.com/liliBestCoder/ghost-plugin-sdk/blob/4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a/docs/plugin-sdk/publish-walkthrough.md)。简述：

1. `.github/workflows/release.yml` 的 `SDK_REPO` 与 `SDK_REF` 已填为 `liliBestCoder/ghost-plugin-sdk` 与 `4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a`（占位符不填，第一步就失败）；本 README 里的 SDK 文档链接指向同一次提交；
2. `gpkg.py keygen` 在仓库**之外**生成钥匙对，`dev-public.b64` 提交到仓库根，`dev-private.pem` 的全部内容存进仓库 secret `GHOST_DEV_KEY_PEM`；
3. 把 `id`、仓库 `owner/name`、`dev-public.b64` 交给官方注册表；
4. `git tag v1.0.0 && git push origin v1.0.0`。

工作流比模板多一步：打包前删掉 `tests/` 与 `.gitignore`——包里只有插件需要的东西（`manifest.json`、`*.py`、`ui/`、`icon.png`、`README.md`、`CHANGELOG.md`，以及 `dev-public.b64`）。手动打包时也请从一份删掉它们的副本打。

## 拿它当起点

1. 复制整个目录，改 `manifest.json` 的 `id`（上架后不能改）、`name`、`description`、`author`、`homepage`，以及 `main.py` 的 `PLUGIN_ID`；
2. `protocol.py` 与 `ghost_api.py` **原样保留**——它们是每个插件都一样的部分；
3. `permissions` 只留你真的用到的那几个（每一个都会在安装时展示给用户确认；`events.read.data` 等于用户的完整访问历史，要有真实理由）；
4. 删掉用不到的区块：`sections.py` 里对应的函数、`main.py` 的 `get_routes`/`post_routes` 里对应的行、`ui/` 里对应的 `<section>` 与 `app.js` 里的渲染函数；
5. 生命周期区块（故意退出）与闸门区块（故意被拒）只是演示，你的插件不需要它们；
6. `tests/test_plugin.py` 的 `FakeGhost` 与 `Host` 可以直接拿去测你自己的插件。

## 测试

```bash
python tests/test_plugin.py      # CTest: ghost_example_showcase_test
```

两层：单元层直接导入各模块（握手的每一种拒绝、安全的 JSON 解析、SSE 的上限、事件平面与 Data 的每秒上限、数据目录、429 退避、各区块的转交规则）；进程层把 `main.py` 当真进程跑，测试自己扮演宿主（命名停止事件、干净的环境、清单的 `args`、一行握手）与 Ghost 的控制接口（每条路由按真闸门对插件的答法应答，没有 `X-Ghost-Plugin-Token` 或带了 `Origin` 就是 401）。断言包括：token 不出现在任何页面响应、stdout、stderr 或数据目录里；前缀、Host、Origin 三道检查；429 退避的间隔；停止事件后退出 0 并写下停止时间；故意退出的代码是 3。

## License / 许可

尚未选定许可证；保留所有权利。如需使用，请联系维护者。

---

# Plugin Showcase

`com.ghostproxifier.showcase` -- the **official reference plugin** for Ghost Proxifier. Every thing a v1 plugin can do, it does once, in its own section of its page, labelled with the spec section and the code that does it. To write a plugin, start from here.

Python standard library, Python 3.9 or later, no third-party dependency. This directory is the whole of the future standalone repository `liliBestCoder/ghost-plugin-showcase`.

> The specifications are in the SDK repository's [`docs/plugin-sdk/`](https://github.com/liliBestCoder/ghost-plugin-sdk/blob/4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a/docs/plugin-sdk/README.md); every `spec-*.md` below means that directory. (The link is pinned to commit `4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a` of the SDK repository `liliBestCoder/ghost-plugin-sdk`, the same `SDK_REPO`/`SDK_REF` as `release.yml`'s.)

## What it demonstrates

The page talks only to the plugin's own process (same origin); the process holds the token and calls Ghost. **The token never reaches the page**, and is never on a command line, in the environment, printed, logged or written to disk.

| Capability | Page section | Spec | Code |
|---|---|---|---|
| Hosted or not (`GHOST_PLUGIN_ID`) | Host protocol and handshake | `spec-host-protocol` §3.0 | `protocol.py` `is_hosted` |
| The handshake, checked field by field; `ok:false` otherwise | Host protocol and handshake | `spec-host-protocol` §3.1–§3.2, §6 | `protocol.py` `check_handshake` |
| The receipt, exactly `{v, ok, uiUrl}`, flushed | Host protocol and handshake | `spec-host-protocol` §3.2 | `protocol.py` `write_line`, `main.py` `run_hosted` |
| The manifest's `args` reaching `argv` | Host protocol and handshake | `spec-manifest` §2 | `main.py` `protocol_view` |
| The `GHOST_PLUGIN_*` environment (same values as the handshake; the token is not among them, measured) | Host protocol and handshake | `spec-host-protocol` §2 | `main.py` `protocol_view` |
| `runtime {kind: python, minVersion}` and the actual interpreter | Host protocol and handshake | `spec-manifest` §4 | `main.py` `runtime_view` |
| The stop event: waited on by the handshake's name, a graceful exit | The private data directory (last graceful stop) | `spec-host-protocol` §2.1 | `protocol.py` `StopEvent`, `main.py` `watch_stop` |
| The six permissions (declared vs granted) | The six permissions | `spec-plugin-api` §2 | `manifest.json` |
| `events.read.control`: the System + Control planes | Event stream: Control / System | `spec-plugin-api` §3 | `events.py` |
| `events.read.data`: the Data plane (off by default, at most 5 a second, memory only) | Event stream: Data | `spec-plugin-api` §3 | `events.py` `EventHub` |
| `stats.read`: `/process-stats` (`env` removed), `/latencies`, `/throughput-history` | Statistics | `spec-plugin-api` §2, end of §4 | `sections.py` `StatsSection` |
| `config.read`: `user`/`pass` are `***`, an empty one stays empty | Configuration | `spec-plugin-api` §4 | `sections.py` `config_section` |
| `log.write`: `src`/`tag`/`plane` forced, `debug` -> `info`; ten at once to see the entry budget | Writing to the log | `spec-plugin-api` §5, `spec-limits` §7 | `sections.py` `log_write`, `log_burst` |
| `plugin.assets`: its own icon; another plugin's -> 403 | Its own icon | `spec-plugin-api` §6 | `sections.py` `fetch_own_icon`, `other_icon` |
| 403 `permission_denied` (`POST /save-config`, a body that is not JSON) | The gate | `spec-plugin-api` §2.1 | `sections.py` `gate_403` |
| 401: the token under the wrong header; a foreign `Origin` | The gate | `spec-plugin-api` §1, §8 | `sections.py` `gate_401_header`, `gate_401_origin` |
| 429 `rate_limited`: exponential backoff (0.25/0.5/1/2 s) | The gate | `spec-limits` §7.1 | `ghost_api.py` `GhostClient.request` |
| The private data directory: start count, versions seen, temp file + atomic replace | The private data directory | `spec-host-protocol` §3.1 | `state_store.py` |
| Crash restart: an exit with code 3 on purpose, to watch the host's 1/4/9 s restart | Lifecycle | `spec-host-protocol` §2, `spec-limits` §1 | `main.py` `App.restart` |
| The licence declaration `license {licensed, trial, expiresAt}` (this plugin is free) | The licence declaration | `spec-host-protocol` §3.1, `spec-license` §7 | `main.py` `license_view` |
| Embedding: `frame-ancestors` exactly Ghost's origin; light/dark follows the **operating system** (`prefers-color-scheme` -- Ghost's WebView reports the Windows setting, and v1 gives a plugin no way to learn Ghost's own theme); the language follows the handshake's `lang` | Embedding, theme and security habits | `spec-manifest` §5, `spec-plugin-api` §8 | `ui_server.py`, `ui/` |
| Standalone: without Ghost the sections that need it are disabled, not broken | The banner at the top | `spec-host-protocol` §3.0 | `main.py` `needs_ghost`, `run_standalone` |
| The page server's habits: a random 128-bit prefix, the Host check, the Origin check on POSTs, a CSP, `textContent` only | Embedding, theme and security habits | `spec-plugin-api` §8 | `ui_server.py`, `ui/app.js` |

One `/events` stream: the server decides which planes to send from the **granted** permissions, the plugin cannot choose, so a second stream would only be a second copy of the same frames -- and a plugin may have at most 2 open at once, the third is answered 429.

## Running standalone

```bash
python main.py --open      # prints the page address and opens it in a browser; Ctrl+C to quit
```

Without `GHOST_PLUGIN_ID` it is standalone: stdin is not read, there is no token. The sections that need Ghost show as disabled; the data-directory section works (in `%LOCALAPPDATA%\com.ghostproxifier.showcase\`).

## The live demo (in the SDK repository)

```powershell
pwsh -File examples\demo\run-showcase-demo.ps1                 # 600 s by default, Chinese
pwsh -File examples\demo\run-showcase-demo.ps1 -Seconds 120 -Lang en
```

It starts `bin\ghost_plugin_demo.exe` from an x64 test build: two **throwaway** keys, a fake network, the real `PluginService` installing it, the real host `ghost_plugin_host.exe`, the real gate (an ephemeral port, a temp data directory). In memory: a demo configuration (one upstream with a credential, one with empty ones), a managed target carrying an `env`, and a Control and a Data event every 2 s. It prints the plugin page's address; press the exit button in the Lifecycle section and the console prints the new address after the host's restart. It never touches `%LOCALAPPDATA%\GhostProxifier`, the real registry, or ports 23551/23552.

## Releasing and listing

See the SDK's [`publish-walkthrough.md`](https://github.com/liliBestCoder/ghost-plugin-sdk/blob/4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a/docs/plugin-sdk/publish-walkthrough.md). In short:

1. `SDK_REPO` and `SDK_REF` in `.github/workflows/release.yml` are set to `liliBestCoder/ghost-plugin-sdk` and `4a6fc4b7d593a7b9c1fdd905a42d81a5a5baad6a` (with the placeholders the first step fails); this README's SDK links point at the same commit;
2. `gpkg.py keygen` OUTSIDE the repository; commit `dev-public.b64` at the root, put the whole of `dev-private.pem` into the repository secret `GHOST_DEV_KEY_PEM`;
3. hand the `id`, the repository `owner/name` and `dev-public.b64` to the official registry;
4. `git tag v1.0.0 && git push origin v1.0.0`.

The workflow has one step more than the template's: before packing it removes `tests/` and `.gitignore`, so the package holds only what the plugin needs (`manifest.json`, `*.py`, `ui/`, `icon.png`, `README.md`, `CHANGELOG.md`, and `dev-public.b64`). Packing by hand, pack a copy without them too.

## Copy this as your starting point

1. Copy the whole directory; change the manifest's `id` (fixed once listed), `name`, `description`, `author`, `homepage`, and `PLUGIN_ID` in `main.py`;
2. keep `protocol.py` and `ghost_api.py` **as they are** -- they are the part every plugin does the same way;
3. keep only the `permissions` you really use (each is shown to the user for consent at install; `events.read.data` is the user's whole browsing history and needs a real reason);
4. delete the sections you do not need: the function in `sections.py`, its lines in `main.py`'s `get_routes`/`post_routes`, its `<section>` in `ui/` and its render function in `app.js`;
5. the Lifecycle section (an exit on purpose) and the gate section (refusals on purpose) are demonstrations; your plugin needs neither;
6. `FakeGhost` and `Host` in `tests/test_plugin.py` can test your own plugin as they are.

## Tests

```bash
python tests/test_plugin.py      # CTest: ghost_example_showcase_test
```

Two layers: the unit layer imports the modules (every handshake refusal, the safe JSON parse, the SSE bounds, the planes and the Data-plane cap, the data directory, the 429 backoff, each section's relay rules); the process layer runs `main.py` as a real process, the test being its host (a named stop event, a clean environment, the manifest's `args`, one handshake line) and Ghost's control interface (every route answered the way the real gate answers a plugin; without `X-Ghost-Plugin-Token`, or with an `Origin`, a 401). Among the assertions: the token never appears in any page response, stdout, stderr or the data directory; the prefix, Host and Origin checks; the 429 backoff's pauses; the stop event -> exit 0 with the stop time written; the exit on purpose uses code 3.

## License

No licence has been chosen yet; all rights reserved. Contact the maintainer before reusing this code.
