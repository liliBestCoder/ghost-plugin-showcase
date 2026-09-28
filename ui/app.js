// Plugin Showcase page.
//
// It talks ONLY to its own plugin process (same origin) -- never to Ghost: a
// request from this page's origin to Ghost is a 401 whatever it carries, and
// the page never has the token anyway (spec-plugin-api §8). Every path is
// RELATIVE ("api/status"): the page lives under the random prefix in uiUrl,
// and "/api/status" would be a 404.
//
// Every value from the server is written with textContent, never as HTML:
// event text, node names and paths are whatever somebody typed.
"use strict";

(function () {
    var TEXT = {
        zh: {
            title: "插件能力示例",
            standaloneBanner: "独立运行：没有 Ghost，也就没有 token。需要 Ghost 的区块已停用——想看它们，就在 Ghost 的插件页里启用本插件（spec-host-protocol §3.0）。数据目录区块照常工作。",
            hosted: "由 Ghost 宿主运行", standalone: "独立运行", streamOk: "事件流已连接", streamOff: "事件流未连接",
            streamConnecting: "事件流连接中……", streamReconnecting: "事件流断开，正在重连……", noGhost: "没有 Ghost：需要它的区块已停用",
            pageLost: "本页的插件进程没有应答（已停止，或被宿主重拉到了新地址）",
            lastError: "最近的错误", needsGhost: "需要 Ghost",
            hProtocol: "宿主协议与握手", nProtocol: "宿主在 stdin 写一行握手，插件在 stdout 回一行回执；此后 stdout 不再被读取。token 只在内存里，下表把它遮住了。",
            hHandshake: "收到的握手（逐字段）", hReceipt: "发出的回执", hArgs: "清单里的 args → 进程的 argv",
            manifestArgs: "manifest.json args", argv: "sys.argv[1:]", argsMatch: "一致",
            hEnv: "GHOST_PLUGIN_* 环境变量", nEnv: "与握手里的同名字段是同一个值的两种取法。token 不在环境里（子进程会继承环境）——下面最后一行是实测结果。",
            sameAsHandshake: "= 握手字段", differs: "≠ 握手字段", unset: "（未设置）", tokenInEnv: "token 在环境里？",
            no: "否", yes: "是", hRuntime: "runtime（清单）与实际解释器",
            declared: "清单声明", actual: "实际", meets: "满足 minVersion", interp: "解释器", ghostPython: "GHOST_PLUGIN_PYTHON",
            hPerms: "六个权限", nPerms: "清单声明了全部六个；只有用户在安装确认框里授予的才算数（握手的 permissions）。每一个都在下面某个区块里用到。",
            granted: "已授予", notGranted: "未授予", usedIn: "用在",
            hControl: "事件流：Control / System 平面", nControl: "一条 GET /events（SSE），断线以 ?after=<最后 id> 续上。平面由服务端按已授予的权限过滤；本插件只开一条流（每插件至多 2 条，第 3 条答 429）。",
            opened: "已打开", times: "次", received: "收到", noEvents: "还没有事件。",
            hData: "事件流：Data 平面", nData: "Data 平面 = 每个被管程序的每一次 DNS 查询与连接目的地，即用户的完整访问历史。默认关闭；打开后每秒至多保留 5 条、只在内存里、从不落盘或写日志。它与上面走的是同一条流。",
            dataSwitch: "显示 Data 平面事件", dataOffCounted: "开关关着：到达但未保留", dataShed: "超出每秒上限而丢弃", dataNotGranted: "未授予 events.read.data：服务端不会发 Data 帧。",
            hStats: "统计（stats.read）", nStats: "三条命令，本插件缓存 2 秒再问（每次调用都花预算）。对插件，每个目标的 env 键被 Ghost 整个删掉——Ghost 自己的页面才有它。",
            colTarget: "目标", colProcs: "进程", colTraffic: "上/下行", colNode: "节点", colLatency: "延迟", colSuccess: "成功/尝试",
            groups: "个被管目标", processes: "个进程行", envRemoved: "已删除", envPresent: "存在！",
            noGroups: "没有被管目标。", noLatNodes: "还没有测过任何节点。",
            avgLatency: "当前节点延迟", retrans: "重传率", points: "个采样点", last: "最新", max: "最大",
            hConfig: "配置（config.read，已脱敏）", nConfig: "插件拿到的是 RedactConfigForExport 的副本：非空的 user/pass 一律是 ***，空的保持空——填 *** 等于告诉读者这里本来有密码。",
            colName: "名称", colType: "类型", colAddr: "地址", refresh: "刷新", noNodes: "没有上游节点。", topKeys: "顶层键",
            hLog: "写日志（log.write）", nLog: "POST /api/log-ingest，键是 entries。本插件请求 src=ui、tag=Ghost、plane=data、level=debug——Ghost 强制改写前三个、把 debug 提升为 info。写下的行会从上面的事件流回来，下表是它回来时的样子。",
            btnLog: "写一行", asked: "请求的", arrived: "回来的", waitingEcho: "（等它从事件流回来……）",
            nBurst: "一次请求 10 条（最后一条故意没有 text，计入 malformed）。一次请求花一次调用预算；每条花一次日志预算：每插件每秒 5 条、突发 50。连按几次就会看到 rateDropped。",
            btnBurst: "一次写 10 条",
            hAssets: "自己的图标（plugin.assets）", nAssets: "GET /api/plugins/icon?id=<自己的 id>：Ghost 按字节嗅探，只答 PNG/WebP；本插件只转发图片。读别的插件的图标一律 403。",
            ownIconOk: "自己的图标：200，已显示在页头", ownIconNo: "自己的图标：没有拿到", btnOtherIcon: "读别的插件的图标",
            hGate: "闸门：401 / 403 / 429", nGate: "三种拒绝都不写 Ghost 的日志——只有插件自己收到的状态码能说明发生了什么。",
            btn401h: "401 · token 放在宿主的头里", btn401o: "401 · 带上本页的 Origin",
            n429: "每插件调用预算：每秒 20 次、突发 100，被 403 的请求也算，401 不算（没有身份）。超出答 429 rate_limited、不带 Retry-After。本插件的客户端遇到 429 按 0.25/0.5/1/2 秒指数退避重试，之后放弃。这里不提供故意刷爆预算的按钮。",
            budget: "本插件的调用计数", calls: "调用", rateLimited: "429", retries: "重试", gaveUp: "放弃",
            hDataDir: "私有数据目录", nDataDir: "dataDir 由宿主给出并已创建；升级不清空，卸载才删。本插件在里面存一个小文件：启动计数、见过的版本、上次停止的时间。写法是临时文件 + 原子替换。",
            starts: "启动次数", firstStart: "首次启动", lastStart: "本次启动", lastStop: "上次优雅停止", versions: "见过的版本",
            file: "文件", problem: "读取问题", writeError: "写入错误", never: "从未", btnReset: "清零",
            hLifecycle: "生命周期：崩溃与重拉", nLifecycle: "进程意外退出时，宿主按 1 / 4 / 9 秒退避重拉，至多 3 次；第 4 次退出之后状态是 crashed / plugin_restart_exhausted，直到用户再次启用。稳定运行 10 分钟后预算归零。崩溃重拉 token 不变；uiUrl 会变（新端口、新前缀），插件页会换一个新的 iframe。",
            lastRestart: "上一次演示退出后，宿主在 {s} 秒后重拉了本插件（本次启动是第 {n} 次）。", noRestart: "还没有演示过重拉。本次启动是第 {n} 次。",
            recentExits: "最近 10 分钟内的演示退出：{n} 次（宿主的预算是 3 次重拉）。",
            btnRestart: "退出（代码 3），让宿主重拉……", confirmRestart: "本进程将以代码 3 退出。宿主会在约 1 秒后重拉它，页面会短暂断开。如果最近已经这样做了 3 次，这一次之后宿主会放弃（plugin_restart_exhausted），需要在插件页里重新启用。",
            btnRestartYes: "确定退出", btnRestartNo: "取消", exiting: "正在退出……宿主重拉后，本页的地址会变：插件页会换上新的 iframe，并显示新地址。",
            hLicense: "许可声明", nLicense: "宿主把主进程的判定告诉插件，供展示或自检。执行点在主进程：没有许可根本不会 start。本插件免费，所以是 licensed:false、trial:false。付费插件会看到 licensed 或 trial 与 expiresAt。",
            present: "握手里有 license", licensed: "licensed", trial: "trial", expiresAt: "expiresAt", none: "（无）",
            freeMeaning: "含义：免费插件", licensedMeaning: "含义：已授权", trialMeaning: "含义：试用中",
            hEmbed: "嵌入、主题与安全习惯", nEmbed: "同一个页面既能嵌在 Ghost 插件页的 iframe（名为 ghost-plugin-<端口>）里，也能在浏览器里单独打开。深浅色跟随的是操作系统（prefers-color-scheme）：Ghost 的 WebView 报告的是 Windows 的设置，v1 没有任何途径让插件得知 Ghost 自己的主题。",
            framed: "在 iframe 里", topLevel: "顶层窗口", embedding: "当前", frameAnc: "CSP frame-ancestors", scheme: "系统配色（prefers-color-scheme）",
            dark: "深色", light: "浅色", langSource: "语言来源", fromHandshake: "握手的 lang", fromBrowser: "浏览器语言",
            hygiene: [
                "token 只在插件进程的内存里：不上命令行、不进环境变量、不写文件、不写日志、不进本页。",
                "页面服务只监听 127.0.0.1，端口由系统分配；路径带每次启动新生成的 128 位随机前缀。",
                "Host 头必须恰好是 127.0.0.1:<端口>（防 DNS 重绑定）；POST 必须带本页自己的 Origin。",
                "本页只用 textContent 写入外来文本；CSP 不允许任何外部资源。",
                "每个到 Ghost 的请求都有超时与大小上限；JSON 解析失败只会得到空值，不会抛出。"
            ],
            status: "HTTP", noAnswer: "没有应答", standaloneSection: "独立运行：这个区块需要 Ghost。",
            refusedOk: "被拒绝（预期）", notRefused: "没有被拒绝！"
        },
        en: {
            title: "Plugin Showcase",
            standaloneBanner: "Running standalone: no Ghost, so no token. The sections that need Ghost are disabled -- enable this plugin from Ghost's plugins page to see them (spec-host-protocol §3.0). The data-directory section still works.",
            hosted: "run by Ghost's host", standalone: "standalone", streamOk: "event stream connected", streamOff: "event stream not connected",
            streamConnecting: "event stream connecting...", streamReconnecting: "event stream lost, reconnecting...", noGhost: "no Ghost: the sections that need it are disabled",
            pageLost: "this page's plugin process does not answer (stopped, or restarted by the host at a new address)",
            lastError: "last error", needsGhost: "needs Ghost",
            hProtocol: "Host protocol and handshake", nProtocol: "The host writes one handshake line on stdin; the plugin answers one receipt line on stdout, and stdout is never read again. The token lives only in memory; it is masked below.",
            hHandshake: "The handshake received (every field)", hReceipt: "The receipt sent", hArgs: "manifest args -> the process's argv",
            manifestArgs: "manifest.json args", argv: "sys.argv[1:]", argsMatch: "match",
            hEnv: "GHOST_PLUGIN_* environment variables", nEnv: "The same values as the handshake's fields, a second way to read them. The token is NOT in the environment (child processes inherit it) -- the last row is measured, not assumed.",
            sameAsHandshake: "= handshake field", differs: "!= handshake field", unset: "(not set)", tokenInEnv: "token in the environment?",
            no: "no", yes: "yes", hRuntime: "runtime (manifest) and the actual interpreter",
            declared: "declared", actual: "actual", meets: "meets minVersion", interp: "interpreter", ghostPython: "GHOST_PLUGIN_PYTHON",
            hPerms: "The six permissions", nPerms: "The manifest declares all six; only what the user granted in the install dialog counts (the handshake's permissions). Each one is used by a section below.",
            granted: "granted", notGranted: "not granted", usedIn: "used in",
            hControl: "Event stream: Control / System planes", nControl: "One GET /events (SSE), resumed with ?after=<last id>. The server filters planes by the granted permissions; this plugin opens one stream (at most 2 per plugin; a third is answered 429).",
            opened: "opened", times: "times", received: "received", noEvents: "No events yet.",
            hData: "Event stream: Data plane", nData: "The Data plane is every DNS query and connection destination of every managed program: the user's browsing history. Off by default; when on, at most 5 events a second are kept, in memory only, never written to disk or logged. It arrives on the same stream as the section above.",
            dataSwitch: "Show Data-plane events", dataOffCounted: "switch off: arrived, not kept", dataShed: "shed over the per-second cap", dataNotGranted: "events.read.data is not granted: the server sends no Data frames.",
            hStats: "Statistics (stats.read)", nStats: "Three commands; this plugin caches the answers for 2 s (every call spends the budget). For a plugin, Ghost removes each target's env key WHOLE -- only Ghost's own page gets it.",
            colTarget: "target", colProcs: "processes", colTraffic: "up/down", colNode: "node", colLatency: "latency", colSuccess: "ok/tries",
            groups: "managed targets", processes: "process rows", envRemoved: "removed", envPresent: "PRESENT!",
            noGroups: "No managed targets.", noLatNodes: "No node measured yet.",
            avgLatency: "active node latency", retrans: "retransmission rate", points: "points", last: "last", max: "max",
            hConfig: "Configuration (config.read, redacted)", nConfig: "A plugin gets RedactConfigForExport's copy: every non-empty user/pass is ***, and an empty one stays empty -- *** there would tell the reader a password exists.",
            colName: "name", colType: "type", colAddr: "address", refresh: "Refresh", noNodes: "No upstream nodes.", topKeys: "top-level keys",
            hLog: "Writing to the log (log.write)", nLog: "POST /api/log-ingest, key entries. This plugin asks for src=ui, tag=Ghost, plane=data, level=debug -- Ghost forces the first three and promotes debug to info. The line comes back on the event stream above; the table shows it as it arrived.",
            btnLog: "Write one line", asked: "asked", arrived: "arrived", waitingEcho: "(waiting for it on the event stream...)",
            nBurst: "Ten entries in one request (the last deliberately has no text and is counted as malformed). One request spends one call of the budget; each entry spends one of the log budget: 5 a second per plugin, burst 50. Press it several times to see rateDropped.",
            btnBurst: "Write ten at once",
            hAssets: "Its own icon (plugin.assets)", nAssets: "GET /api/plugins/icon?id=<its own id>: Ghost sniffs the bytes and answers only PNG/WebP; this plugin relays only images. Another plugin's icon is always a 403.",
            ownIconOk: "own icon: 200, shown in the header", ownIconNo: "own icon: not received", btnOtherIcon: "Read another plugin's icon",
            hGate: "The gate: 401 / 403 / 429", nGate: "None of the three refusals is written to Ghost's log -- the status code the plugin receives is the only record.",
            btn401h: "401 · the token under the host's header", btn401o: "401 · with this page's Origin",
            n429: "The per-plugin call budget: 20 a second, burst 100; a refused 403 counts, a 401 does not (no identity). Over it: 429 rate_limited, no Retry-After. This plugin's client retries a 429 with exponential backoff, 0.25/0.5/1/2 s, then gives up. There is deliberately no button that floods the budget.",
            budget: "this plugin's call counters", calls: "calls", rateLimited: "429s", retries: "retries", gaveUp: "gave up",
            hDataDir: "The private data directory", nDataDir: "dataDir comes from the host, already created; kept across upgrades, deleted on uninstall. This plugin keeps one small file in it: the start count, the versions seen, the last stop. Written to a temporary file and replaced atomically.",
            starts: "starts", firstStart: "first start", lastStart: "this start", lastStop: "last graceful stop", versions: "versions seen",
            file: "file", problem: "read problem", writeError: "write error", never: "never", btnReset: "Reset",
            hLifecycle: "Lifecycle: crash and restart", nLifecycle: "When the process exits unexpectedly the host restarts it after 1 / 4 / 9 s, at most 3 times; after a fourth exit it stays crashed / plugin_restart_exhausted until the user enables it again. Ten minutes of stable running resets the budget. A crash restart keeps the token; uiUrl changes (a new port and prefix), and the plugins page swaps in a new iframe.",
            lastRestart: "After the last demo exit the host restarted this plugin {s} s later (this is start #{n}).", noRestart: "No restart demonstrated yet. This is start #{n}.",
            recentExits: "Demo exits in the last 10 minutes: {n} (the host's budget is 3 restarts).",
            btnRestart: "Exit (code 3) so the host restarts me...", confirmRestart: "This process will exit with code 3. The host restarts it after about 1 s; the page goes away briefly. If this was done 3 times recently, the host gives up after this one (plugin_restart_exhausted) and the plugin has to be enabled again from the plugins page.",
            btnRestartYes: "Exit now", btnRestartNo: "Cancel", exiting: "Exiting... after the restart this page has a new address: the plugins page swaps in a new iframe and shows it.",
            hLicense: "The licence declaration", nLicense: "The host tells the plugin what the main process decided, for display or self-checks. The main process is the enforcement point: without a licence the plugin is never started. This plugin is free, so licensed:false, trial:false. A paid plugin sees licensed or trial, and expiresAt.",
            present: "license in the handshake", licensed: "licensed", trial: "trial", expiresAt: "expiresAt", none: "(none)",
            freeMeaning: "meaning: a free plugin", licensedMeaning: "meaning: licensed", trialMeaning: "meaning: in its trial",
            hEmbed: "Embedding, theme and security habits", nEmbed: "The same page works framed in Ghost's plugins page (an iframe named ghost-plugin-<port>) and opened top-level in a browser. Light or dark follows the OPERATING SYSTEM (prefers-color-scheme): Ghost's WebView reports the Windows setting, and v1 gives a plugin no way to learn Ghost's own theme.",
            framed: "in an iframe", topLevel: "top-level window", embedding: "now", frameAnc: "CSP frame-ancestors", scheme: "OS colour scheme (prefers-color-scheme)",
            dark: "dark", light: "light", langSource: "language from", fromHandshake: "the handshake's lang", fromBrowser: "the browser's language",
            hygiene: [
                "The token lives only in the plugin process's memory: not on a command line, not in the environment, not in a file, not in a log, not in this page.",
                "The page server listens on 127.0.0.1 only, on a port the system picks, under a random 128-bit path prefix made new at every start.",
                "The Host header must be exactly 127.0.0.1:<port> (DNS rebinding); a POST must carry this page's own Origin.",
                "This page writes foreign text only with textContent; the CSP allows no external resource.",
                "Every request to Ghost has a timeout and a size limit; a JSON parse that fails yields nothing, never an exception."
            ],
            status: "HTTP", noAnswer: "no answer", standaloneSection: "Standalone: this section needs Ghost.",
            refusedOk: "refused (as expected)", notRefused: "NOT refused!"
        }
    };

    // Which section uses which permission (for the permissions table).
    var PERM_USE = {
        "events.read.control": "sec-control", "events.read.data": "sec-data", "stats.read": "sec-stats",
        "config.read": "sec-config", "log.write": "sec-log", "plugin.assets": "sec-assets"
    };

    var lang = null;               // from the handshake; null until known
    var hosted = null;
    var lastEventsKey = "";
    var ownId = "";

    function t(key) { return (TEXT[lang || "en"] || TEXT.en)[key]; }
    function fmt(key, vals) {
        return String(t(key)).replace(/\{(\w+)\}/g, function (_, k) { return vals[k] === undefined ? "" : String(vals[k]); });
    }
    function $(id) { return document.getElementById(id); }
    function setText(id, value) {
        var e = $(id);
        if (e) e.textContent = value === undefined || value === null ? "" : String(value);
    }
    function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); }
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined && text !== null) e.textContent = String(text);
        return e;
    }
    function show(v) {
        if (v === null || v === undefined) return t("none");
        return typeof v === "string" ? v : JSON.stringify(v);
    }
    function when(sec) {
        if (typeof sec !== "number" || !isFinite(sec)) return t("never");
        return new Date(sec * 1000).toLocaleString();
    }
    function clock(ms) {
        if (typeof ms !== "number" || !isFinite(ms)) return "";
        var d = new Date(ms);
        function two(n) { return (n < 10 ? "0" : "") + n; }
        return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
    }
    function bytes(n) {
        n = Number(n) || 0;
        if (n < 1024) return n + " B";
        if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
        return (n / 1048576).toFixed(1) + " MB";
    }
    // A key/value table: rows = [[key, value, class?], ...].
    function kv(id, rows) {
        var body = $(id);
        clear(body);
        rows.forEach(function (r) {
            var tr = el("tr");
            tr.appendChild(el("td", "", r[0]));
            tr.appendChild(el("td", r[2] || "", r[1]));
            body.appendChild(tr);
        });
    }

    function get(path) {
        return fetch(path, { cache: "no-store" }).then(function (r) { return r.json(); });
    }
    // POST with a JSON body. The browser adds this page's Origin, which the
    // plugin's server requires on every POST.
    function post(path, obj) {
        return fetch(path, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
                             body: JSON.stringify(obj || {}) }).then(function (r) { return r.json(); });
    }
    function button(id, fn) {
        $(id).addEventListener("click", function () {
            var b = $(id);
            b.disabled = true;
            Promise.resolve().then(fn).catch(function () {}).then(function () { b.disabled = false; });
        });
    }

    // ---- labels, language, standalone ------------------------------------------------------

    function renderLabels() {
        document.documentElement.lang = lang || "en";
        var nodes = document.querySelectorAll("[data-t]");
        for (var i = 0; i < nodes.length; i++) nodes[i].textContent = t(nodes[i].getAttribute("data-t"));
        var nav = $("nav");
        clear(nav);
        var cards = document.querySelectorAll("section.card");
        for (var j = 0; j < cards.length; j++) {
            var a = el("a", "", cards[j].querySelector("h2").textContent);
            a.href = "#" + cards[j].id;
            nav.appendChild(a);
        }
        var list = $("hygiene");
        clear(list);
        t("hygiene").forEach(function (line) { list.appendChild(el("li", "", line)); });
    }

    function applyMode() {
        $("standalone").hidden = hosted !== false;
        var cards = document.querySelectorAll("section.needs-ghost");
        for (var i = 0; i < cards.length; i++) cards[i].classList.toggle("disabled", hosted === false);
    }

    // ---- status (every second) ----------------------------------------------------------------

    function renderStatus(s) {
        var first = lang === null;
        ownId = s.pluginId || "";
        if (s.lang === "zh" || s.lang === "en") lang = s.lang;
        else if (lang === null) lang = /^zh\b/i.test(navigator.language || "") ? "zh" : "en";
        if (first || hosted !== !!s.hosted) {
            hosted = !!s.hosted;
            renderLabels();
            applyMode();
            loadStatic();
        }
        var icon = $("icon");
        if (s.icon && icon.hidden) { icon.src = "api/icon"; icon.hidden = false; }
        renderPerms(s);
        renderBudget(s.client);
        renderEmbed(s);
        setText("ownIcon", hosted ? (s.icon ? t("ownIconOk") : t("ownIconNo")) : t("standaloneSection"));
    }

    function renderPerms(s) {
        var granted = Array.isArray(s.permissions) ? s.permissions : [];
        kv("perms", (s.declared || []).map(function (p) {
            var ok = granted.indexOf(p) >= 0;
            var sec = document.getElementById(PERM_USE[p]);
            var where = sec ? sec.querySelector("h2").textContent : "";
            return [p, (ok ? t("granted") : t("notGranted")) + " · " + t("usedIn") + ": " + where, ok ? "good" : ""];
        }));
    }

    function renderBudget(c) {
        if (!c) { setText("budgetLine", t("standaloneSection")); return; }
        setText("budgetLine", t("budget") + ": " + t("calls") + " " + c.calls + " · " + t("rateLimited") + " " +
                c.rateLimited + " · " + t("retries") + " " + c.retries + " · " + t("gaveUp") + " " + c.gaveUp);
    }

    function renderEmbed(s) {
        var framed = window.self !== window.top;
        var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        kv("embed", [
            [t("embedding"), framed ? t("framed") + (window.name ? " (" + window.name + ")" : "") : t("topLevel")],
            [t("frameAnc"), s.frameAncestor],
            [t("scheme"), dark ? t("dark") : t("light")],
            [t("langSource"), s.lang ? t("fromHandshake") + " (" + s.lang + ")" : t("fromBrowser")]
        ]);
    }

    // ---- the protocol section (once) --------------------------------------------------------------

    function renderProtocol(p) {
        var hs = p.handshake;
        if (!hs) {
            kv("handshake", [["mode", t("standalone")]]);
        } else {
            kv("handshake", Object.keys(hs).map(function (k) { return [k, show(hs[k]), k === "token" ? "redacted" : ""]; }));
        }
        setText("receipt", p.receipt ? JSON.stringify(p.receipt) : t("standalone"));
        var same = JSON.stringify(p.argv || []) === JSON.stringify(p.manifestArgs || []);
        kv("args", [[t("manifestArgs"), show(p.manifestArgs)], [t("argv"), show(p.argv)],
                    [t("argsMatch"), same ? t("yes") : t("no"), same ? "good" : "bad"]]);
        var env = p.env || {};
        var rows = Object.keys(env).map(function (k) {
            var m = p.envMatches ? p.envMatches[k] : undefined;
            var note = m === true ? "  " + t("sameAsHandshake") : m === false ? "  " + t("differs") : "";
            return [k, (env[k] === null ? t("unset") : env[k]) + note, m === false ? "bad" : ""];
        });
        rows.push([t("tokenInEnv"), p.tokenInEnv ? t("yes") : t("no"), p.tokenInEnv ? "bad" : "good"]);
        kv("env", rows);
        var rt = p.runtime || {};
        var d = rt.declared || {};
        kv("runtime", [[t("declared"), d.kind + " >= " + d.minVersion], [t("actual"), "python " + rt.python],
                       [t("meets"), rt.meets ? t("yes") : t("no"), rt.meets ? "good" : "bad"],
                       [t("interp"), rt.executable], [t("ghostPython"), rt.ghostPluginPython || t("unset")]]);
        renderLicense(p.license || {});
    }

    function renderLicense(l) {
        if (!l.present) { kv("license", [[t("present"), t("no")]]); return; }
        var meaning = l.licensed ? t("licensedMeaning") : l.trial ? t("trialMeaning") : t("freeMeaning");
        kv("license", [[t("present"), t("yes")], [t("licensed"), String(l.licensed)], [t("trial"), String(l.trial)],
                       [t("expiresAt"), l.expiresAt || t("none")], ["", meaning]]);
    }

    // ---- events (every second) ----------------------------------------------------------------------

    function eventItem(e) {
        var li = el("li", "level-" + (e.level === "warn" || e.level === "error" ? e.level : "info"));
        li.appendChild(el("span", "when", clock(e.ts)));
        li.appendChild(el("span", "plane", e.plane));
        li.appendChild(el("span", "tag", e.src === "plugin" ? "[plugin:" + e.tag + "]" : e.tag));
        li.appendChild(el("span", "text", e.text));
        return li;
    }

    function fillList(id, list, emptyText) {
        var ol = $(id);
        var items = document.createDocumentFragment();
        for (var i = list.length - 1; i >= 0; i--) items.appendChild(eventItem(list[i] || {}));   // newest first
        clear(ol);
        ol.appendChild(items);
        if (!list.length) ol.appendChild(el("li", "empty", emptyText));
    }

    // The header's status line: who runs this plugin, and -- hosted -- the
    // stream's state. Written on every poll, so a lost stream shows at once.
    function renderStatusLine(v) {
        var line, ok;
        if (hosted === false) {
            line = t("standalone") + " · " + t("noGhost");
            ok = false;
        } else {
            ok = !!v.connected;
            line = t("hosted") + " · " + (v.connected ? t("streamOk") : v.opened ? t("streamReconnecting") : t("streamConnecting"));
            if (!v.connected && v.lastError) line += " (" + v.lastError + ")";
        }
        setText("status", line);
        $("status").className = "status " + (ok ? "ok" : "off");
    }

    function renderEvents(v) {
        renderStatusLine(v);
        if (hosted === false) return;
        var c = v.counts || {};
        setText("streamLine", (v.connected ? t("streamOk") : t("streamOff")) + " · " + t("opened") + " " + v.opened +
                " " + t("times") + " · " + t("received") + " system " + (c.system || 0) + ", control " + (c.control || 0) +
                (v.lastError ? " · " + t("lastError") + ": " + v.lastError : ""));
        $("dataSwitch").checked = !!v.dataOn;
        $("dataSwitch").disabled = !v.canData;
        setText("dataLine", !v.canData ? t("dataNotGranted") :
                t("received") + " data " + (c.data || 0) + " · " + t("dataOffCounted") + " " + v.dataIgnored + " · " +
                t("dataShed") + " " + v.dataShed + " (" + v.dataPerSec + "/s)");
        renderEcho(v.ownEcho);
        // Rebuilt only when something arrived: a list rebuilt every second
        // loses the reader's scroll position and flickers.
        var key = [lang, c.system, c.control, c.data, v.dataOn].join("|");
        if (key === lastEventsKey) return;
        lastEventsKey = key;
        fillList("controlList", v.control || [], t("noEvents"));
        fillList("dataList", v.data || [], v.dataOn ? t("noEvents") : t("dataOffCounted"));
    }

    var logAsked = null;
    function renderEcho(echo) {
        if (!logAsked) return;
        var rows = [["", t("asked") + "  →  " + t("arrived")]];
        ["src", "tag", "plane", "level"].forEach(function (k) {
            var got = echo ? echo[k] : t("waitingEcho");
            rows.push([k, logAsked[k] + "  →  " + got, echo && got !== logAsked[k] ? "redacted" : ""]);
        });
        kv("logForced", rows);
    }

    // ---- sections that ask Ghost --------------------------------------------------------------------

    function answerText(r, expect) {
        if (r.error === "standalone") return t("standaloneSection");
        var head = t("status") + " " + (r.status || t("noAnswer"));
        if (expect) head += " · " + (r.status === expect ? t("refusedOk") : t("notRefused"));
        return head + "\n" + JSON.stringify(r, null, 1);
    }

    function show403(id, expect, r) {
        setText(id, answerText(r, expect));
        $(id).className = "result " + (r.status === expect ? "good" : "bad");
    }

    function loadConfig() {
        return get("api/config").then(function (r) {
            var body = $("nodes");
            clear(body);
            if (r.error === "standalone") { setText("configLine", t("standaloneSection")); return; }
            (r.nodes || []).forEach(function (n) {
                var tr = el("tr");
                tr.appendChild(el("td", "", n.name));
                tr.appendChild(el("td", "", n.type));
                tr.appendChild(el("td", "", n.addr));
                tr.appendChild(el("td", n.user === "***" ? "redacted" : "", n.user === "" ? "—" : n.user));
                tr.appendChild(el("td", n.pass === "***" ? "redacted" : "", n.pass === "" ? "—" : n.pass));
                body.appendChild(tr);
            });
            setText("configLine", r.status !== 200 ? t("status") + " " + (r.status || t("noAnswer")) + " " + (r.error || "") :
                    (r.nodes && r.nodes.length ? t("status") + " 200 · " + t("topKeys") + ": " + (r.keys || []).join(", ")
                                               : t("noNodes")));
        });
    }

    function loadStats() {
        return get("api/stats").then(function (r) {
            if (r.error === "standalone") {
                ["procLine", "latLine", "tpLine"].forEach(function (id) { setText(id, t("standaloneSection")); });
                return;
            }
            var p = r.processes || {};
            setText("procLine", t("status") + " " + (p.status || t("noAnswer")) + (p.error ? " " + p.error : "") + " · " +
                    (p.groups || []).length + " " + t("groups") + " · " + (p.statsCount || 0) + " " + t("processes"));
            var gb = $("groups");
            clear(gb);
            (p.groups || []).forEach(function (g) {
                var tr = el("tr");
                tr.appendChild(el("td", "", (g.alias || g.name) + "\n" + g.path));
                tr.appendChild(el("td", "", g.activeCount + (g.children.length ? " (" + g.children.map(function (c) {
                    return c.name + " #" + c.pid; }).join(", ") + ")" : "")));
                tr.appendChild(el("td", "", bytes(g.totalUp) + " / " + bytes(g.totalDown)));
                tr.appendChild(el("td", g.hasEnv ? "bad" : "good", g.hasEnv ? t("envPresent") : t("envRemoved")));
                gb.appendChild(tr);
            });
            if (!(p.groups || []).length) {
                var tr0 = el("tr");
                var td0 = el("td", "", t("noGroups"));
                td0.colSpan = 4;
                tr0.appendChild(td0);
                gb.appendChild(tr0);
            }
            var l = r.latencies || {};
            setText("latLine", t("status") + " " + (l.status || t("noAnswer")) + (l.error ? " " + l.error : "") + " · " +
                    t("avgLatency") + " " + (l.avgHttpLatency || 0) + " ms · " + t("retrans") + " " +
                    Number(l.retransmissionRate || 0).toFixed(2) + "%");
            var lb = $("latNodes");
            clear(lb);
            (l.nodes || []).forEach(function (n) {
                var tr = el("tr");
                tr.appendChild(el("td", "", n.id));
                tr.appendChild(el("td", "", n.latency + " ms"));
                tr.appendChild(el("td", "", n.success + " / " + n.attempts));
                tr.appendChild(el("td", "", n.udp || "—"));
                lb.appendChild(tr);
            });
            if (!(l.nodes || []).length) {
                var tr1 = el("tr");
                var td1 = el("td", "", t("noLatNodes"));
                td1.colSpan = 4;
                tr1.appendChild(td1);
                lb.appendChild(tr1);
            }
            var h = (r.throughput || {}).history || [];
            var max = h.reduce(function (m, v) { return Math.max(m, v); }, 0);
            setText("tpLine", t("status") + " " + ((r.throughput || {}).status || t("noAnswer")) + " · " + h.length + " " +
                    t("points") + (h.length ? " · " + t("last") + " " + bytes(h[h.length - 1]) + "/s · " + t("max") + " " +
                    bytes(max) + "/s" : ""));
            drawSpark(h, max);
        });
    }

    // Built with DOM calls -- no markup string, and nothing the CSP would stop.
    function drawSpark(h, max) {
        var svg = $("spark");
        clear(svg);
        if (h.length < 2) return;
        var pts = h.map(function (v, i) {
            return (i * 240 / (h.length - 1)).toFixed(1) + "," + (38 - (max ? v / max : 0) * 36).toFixed(1);
        }).join(" ");
        var line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
        line.setAttribute("points", pts);
        svg.appendChild(line);
    }

    function renderState(v) {
        var s = v.state || {};
        kv("stateRows", [[t("starts"), s.starts], [t("firstStart"), when(s.firstStart)], [t("lastStart"), when(s.lastStart)],
                         [t("lastStop"), when(s.lastStop)], [t("versions"), (s.versions || []).join(", ")], [t("file"), v.file],
                         [t("problem"), v.problem || t("none"), v.problem ? "bad" : ""],
                         [t("writeError"), v.writeError || t("none"), v.writeError ? "bad" : ""]]);
        var line = s.lastRestart ? fmt("lastRestart", { s: s.lastRestart.delaySec, n: s.starts }) : fmt("noRestart", { n: s.starts });
        setText("restartLine", line + " " + fmt("recentExits", { n: s.recentDemoExits || 0 }));
    }

    function loadStatic() {
        get("api/protocol").then(renderProtocol).catch(function () {});
        get("api/state").then(renderState).catch(function () {});
        loadConfig().catch(function () {});
        loadStats().catch(function () {});
    }

    // Nothing answers when this page's own process is gone: stopped, or
    // restarted by the host under a NEW address (port and prefix) -- this
    // address is then dead for good. Say so instead of showing the last state.
    function pageLost() {
        setText("status", t("pageLost"));
        $("status").className = "status off";
    }

    function tick() {
        get("api/status").then(renderStatus).then(function () {
            return get("api/events").then(renderEvents);
        }).catch(pageLost);
    }

    document.addEventListener("DOMContentLoaded", function () {
        button("btnConfig", loadConfig);
        $("dataSwitch").addEventListener("change", function () {
            post("api/events/data", { on: $("dataSwitch").checked }).then(function () { lastEventsKey = ""; });
        });
        button("btnLog", function () {
            return post("api/log").then(function (r) {
                if (r.error === "standalone") { setText("logResult", t("standaloneSection")); return; }
                logAsked = r.asked;
                setText("logResult", answerText(r.answer || {}));
            });
        });
        button("btnBurst", function () {
            return post("api/log/burst").then(function (r) {
                setText("burstResult", r.error === "standalone" ? t("standaloneSection") : answerText(r.answer || {}));
            });
        });
        button("btnOtherIcon", function () { return post("api/assets/other").then(show403.bind(null, "otherIconResult", 403)); });
        button("btn403", function () { return post("api/gate/403").then(show403.bind(null, "r403", 403)); });
        button("btn401h", function () { return post("api/gate/401-header").then(show403.bind(null, "r401h", 401)); });
        button("btn401o", function () { return post("api/gate/401-origin").then(show403.bind(null, "r401o", 401)); });
        button("btnReset", function () { return post("api/state/reset").then(renderState); });
        $("btnRestart").addEventListener("click", function () { $("confirmRestart").hidden = false; });
        $("btnRestartNo").addEventListener("click", function () { $("confirmRestart").hidden = true; });
        button("btnRestartYes", function () {
            $("confirmRestart").hidden = true;
            return post("api/restart", { confirm: true }).then(function (r) {
                setText("restartResult", r.exiting ? t("exiting") : answerText(r));
            });
        });
        tick();
        setInterval(tick, 1000);
        setInterval(function () { if (hosted) loadStats().catch(function () {}); }, 5000);
        setInterval(function () { get("api/state").then(renderState).catch(function () {}); }, 5000);
    });
})();
