/* MoE Judge · 只读视图（CONTRACT §5）
 *
 * 铁律：本文件不含任何题面公式实现。
 * - 时长、内存、调度、Time / lb / 相对分 / 排名，全部来自 judge 服务；
 * - 唯一的算术是画图用的比例与显示用的 Δ（服务端数值的格式化）；
 * - 连不上服务时只显示「后端未连接」空态，不回退本地计算；
 * - 演示模式（?demo=1）加载 ui/fixtures.js 的静态夹具，仍然走同一套 API 形状，
 *   并始终标注「演示夹具」。
 *
 * 数据来源（CONTRACT §2）：
 *   GET /api/health                            （可选：账本条数，§5.3）
 *   GET /api/versions                          （score / rank / 来源）
 *   run 列表 = /api/versions + /api/meta（last_run/active_runs）+ SSE
 *   GET /api/runs/{id}                         （run 状态与进度）
 *   GET /api/runs/{id}/cases/{case}            （展示字段）
 *   GET /api/runs/{id}/cases/{case}/ops        （切片：since/until/group/mb/limit/cursor）
 *   GET /api/runs/{id}/cases/{case}/output     （可选：编辑器载入原文）
 *   GET /api/events                            （SSE 运行态）
 *   POST /api/evaluate                         （编辑器预览，服务端判题）
 */
(function () {
  "use strict";

  /* ── 操作分类（只用于画泳道，不计算时长） ─────────────────────── */
  var COMP_OPS = { s: 1, gemm: 1, s_bwd: 1, gemm_dx: 1, gemm_dw: 1, s_dw: 1 };
  var COMM_OPS = { disp: 1, comb: 1, comb_bwd: 1, disp_bwd: 1 };
  var BACKWARD = { s_bwd: 1, comb_bwd: 1, gemm_dx: 1, gemm_dw: 1, s_dw: 1, disp_bwd: 1 };
  var STATES = ["queued", "running", "done", "failed", "timeout"];
  var STATE_LABEL = {
    queued: "queued", running: "running", done: "done",
    failed: "failed", timeout: "timeout"
  };
  var CHECK_ITEMS = [
    { cat: "field", name: "字段 · 网格 · 切点", hint: "V P / PSI / MAP 计数" },
    { cat: "missing", name: "调度守恒 · 缺失", hint: "每层 × 卡组 × 操作恰好一条" },
    { cat: "duplicate", name: "调度守恒 · 重复", hint: "同一 mb:l:op 只能出现一次" },
    { cat: "dependency", name: "依赖与因果", hint: "层内链 / 反向链 / 跨层约束" },
    { cat: "engine", name: "卡组引擎互斥", hint: "计算与通信各一套，零时长不占引擎" },
    { cat: "memory", name: "内存三块上限", hint: "三块内存之和不得超过上限" }
  ];

  var DEMO = /[?&]demo=1(?:&|$)/.test(location.search);

  /* ── 状态 ─────────────────────────────────────────────────────── */
  var S = {
    mode: DEMO ? "demo" : "live",
    base: "",
    connected: false,
    health: null,
    versions: [],
    runList: [],
    runs: new Map(),
    runId: "",
    caseName: "",
    detail: null,
    ops: null,
    range: { t0: 0, t1: 1 },
    window: null,
    zoom: 1,
    filters: { layer: "all", kind: "all" },
    sel: null,
    ab: { runId: "", detail: null, ops: null, scale: "abs" },
    sse: "off",
    es: null,
    viewTimer: null,
    pollTimer: null,
    updatedAt: "",
    preview: null
  };

  /* ── 基础工具 ─────────────────────────────────────────────────── */
  function $(id) { return document.getElementById(id); }
  function setText(id, value) { var el = $(id); if (el) el.textContent = value; }
  function setHTML(id, value) { var el = $(id); if (el) el.innerHTML = value; }
  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    return null;
  }
  function fmtInt(value) {
    var n = num(value);
    return n === null ? "—" : String(n);
  }
  function fmtScore(value) {
    var n = num(value);
    return n === null ? "null" : n.toFixed(3);
  }
  function pad2(n) { return n < 10 ? "0" + n : String(n); }
  function stamp() {
    var d = new Date();
    return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
  }
  function pct(value, total) {
    var v = num(value), t = num(total);
    if (v === null || t === null || t <= 0) return "0";
    var p = (v / t) * 100;
    if (p < 0) p = 0;
    if (p > 100) p = 100;
    return p.toFixed(2);
  }
  function clampPct(value, total) {
    var v = num(value), t = num(total);
    if (v === null || t === null || t <= 0) return "0";
    var p = (v / t) * 100;
    if (p < 0) p = 0;
    if (p > 100) p = 100;
    return p.toFixed(2);
  }
  function statePill(state) {
    var s = String(state || "");
    var label = STATE_LABEL[s] || s || "—";
    return '<span class="pill" data-state="' + esc(s) + '">' + esc(label) + "</span>";
  }
  function badge3(kind, text) {
    return '<span class="badge3 ' + kind + '">' + esc(text) + "</span>";
  }
  function setFooter(text) { setText("footer-state", text); }
  function markUpdated() {
    S.updatedAt = stamp();
    setText("st-updated", S.updatedAt);
  }
  function setSSE(state) {
    S.sse = state;
    var el = $("st-sse");
    if (!el) return;
    el.dataset.state = state;
    el.textContent = {
      off: "未连接", connecting: "连接中", open: "已连接",
      demo: "演示（模拟事件）", error: "已断开"
    }[state] || state;
  }
  function renderMode() {
    var el = $("st-mode");
    if (!el) return;
    el.dataset.state = S.mode;
    el.textContent = S.mode === "demo" ? "演示夹具（静态）" : "实时 API";
  }

  /* ── 服务地址 ─────────────────────────────────────────────────── */
  function defaultBase() {
    if (location.protocol === "http:" || location.protocol === "https:") return location.origin;
    return "http://127.0.0.1:3081";
  }
  function normalizeBase(raw) {
    var u = String(raw || "").trim();
    while (u.charAt(u.length - 1) === "/") u = u.slice(0, -1);
    if (!/^https?:\/\//.test(u)) u = "http://" + u;
    return u;
  }
  function loadBase() {
    var saved = null;
    try { saved = localStorage.getItem("moe.judge.base"); } catch (e) { saved = null; }
    return normalizeBase(saved || defaultBase());
  }
  function saveBase(value) {
    try { localStorage.setItem("moe.judge.base", value); } catch (e) { /* file:// 下可能不可用 */ }
  }

  /* ── API 层 ───────────────────────────────────────────────────── */
  function ApiError(status, path, body) {
    this.name = "ApiError";
    this.status = status;
    this.path = path;
    this.body = body;
    this.message = "HTTP " + status + " · " + path;
  }
  ApiError.prototype = Object.create(Error.prototype);

  function qs(params) {
    if (!params) return "";
    var parts = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === "") return;
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function describeError(err) {
    if (!err) return "未知错误";
    if (err.name === "AbortError") return "请求超时（8s）";
    if (err instanceof ApiError) {
      var extra = err.body && err.body.error ? "（" + err.body.error + "）" : "";
      return "GET " + err.path + " 失败 · HTTP " + err.status + extra;
    }
    return "请求失败：" + (err.message || String(err)) + "（服务未启动，或浏览器因跨源拒绝）";
  }

  function api(path, params) {
    if (S.mode === "demo") return DemoAPI.get(path, params);
    var url = S.base + path + qs(params);
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = null;
    if (ctrl) timer = setTimeout(function () { ctrl.abort(); }, 8000);
    return fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      if (timer) clearTimeout(timer);
      if (!res.ok) {
        return res.text().then(function (txt) {
          var body = null;
          try { body = JSON.parse(txt); } catch (e) { body = txt; }
          throw new ApiError(res.status, path, body);
        });
      }
      return res.json();
    }, function (err) {
      if (timer) clearTimeout(timer);
      throw err;
    });
  }

  function apiPost(path, payload) {
    if (S.mode === "demo") return DemoAPI.post(path, payload);
    var url = S.base + path;
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = null;
    if (ctrl) timer = setTimeout(function () { ctrl.abort(); }, 8000);
    return fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      if (timer) clearTimeout(timer);
      if (!res.ok) {
        return res.text().then(function (txt) {
          var body = null;
          try { body = JSON.parse(txt); } catch (e) { body = txt; }
          throw new ApiError(res.status, path, body);
        });
      }
      return res.json();
    }, function (err) {
      if (timer) clearTimeout(timer);
      throw err;
    });
  }

  /* ── 演示夹具（DEMO-ONLY） ────────────────────────────────────── */
  var DemoAPI = {
    get: function (path, params) {
      return new Promise(function (resolve, reject) {
        setTimeout(function () {
          try { resolve(demoGet(path, params || {})); } catch (err) { reject(err); }
        }, 40);
      });
    },
    post: function (path, payload) {
      return new Promise(function (resolve, reject) {
        setTimeout(function () {
          try { resolve(demoPost(path, payload || {})); } catch (err) { reject(err); }
        }, 60);
      });
    }
  };

  function fixtures() {
    var data = window.__UI_FIXTURES__;
    if (!data) throw new Error("演示夹具未加载（ui/fixtures.js）");
    return data;
  }

  function demoGet(path, params) {
    var F = fixtures();
    if (path === "/api/health") return F.health;
    if (path === "/api/meta") return F.meta;
    if (path === "/api/versions") return F.versions;
    var m = /^\/api\/runs\/([^/]+)$/.exec(path);
    if (m) {
      var run = null;
      F.runs.forEach(function (item) { if (item.run_id === m[1]) run = item; });
      if (!run) throw new ApiError(404, path, { error: "run-not-found" });
      return run;
    }
    m = /^\/api\/runs\/([^/]+)\/cases\/([^/]+)\/ops$/.exec(path);
    if (m) return demoOps(m[1], m[2], params, path);
    m = /^\/api\/runs\/([^/]+)\/cases\/([^/]+)\/output$/.exec(path);
    if (m) {
      var text = F.outputs[m[1] + "/" + m[2]];
      if (typeof text !== "string") throw new ApiError(404, path, { error: "output-not-retained" });
      return { case: m[2], text: text };
    }
    m = /^\/api\/runs\/([^/]+)\/cases\/([^/]+)$/.exec(path);
    if (m) {
      var detail = F.cases[m[1] + "/" + m[2]];
      if (!detail) throw new ApiError(404, path, { error: "case-not-found" });
      return detail;
    }
    throw new ApiError(404, path, { error: "demo-route" });
  }

  function demoOps(runId, caseName, params, path) {
    var F = fixtures();
    var entry = F.ops[runId + "/" + caseName];
    var all = null;
    var fakeTotal = null;
    var fakeNext = null;
    if (Array.isArray(entry)) {
      all = entry;
    } else if (entry && Array.isArray(entry.items)) {
      // 演示专用的“截断切片”形态：items 是真实数据，total/next_cursor 用于展示徽标。
      all = entry.items;
      fakeTotal = num(entry.total) === null ? null : entry.total;
      fakeNext = entry.next_cursor === undefined ? null : entry.next_cursor;
    }
    if (!all) throw new ApiError(404, path, { error: "case-not-found" });
    var since = num(Number(params.since)) === null ? 0 : Number(params.since);
    var until = params.until === undefined ? null : Number(params.until);
    var group = params.group === undefined ? null : Number(params.group);
    var mb = params.mb === undefined ? null : Number(params.mb);
    var limit = params.limit === undefined ? 5000 : Number(params.limit);
    var cursor = params.cursor === undefined ? 0 : Number(params.cursor);
    var picked = all.filter(function (o) {
      if (until !== null && o.t >= until) return false;
      if (o.t < since) return false;
      if (group !== null && o.g !== group) return false;
      if (mb !== null && o.mb !== mb) return false;
      return true;
    });
    var page = picked.slice(cursor, cursor + limit);
    var total = fakeTotal === null ? picked.length : fakeTotal;
    var next;
    if (fakeNext !== null) next = cursor === 0 ? fakeNext : null;
    else next = cursor + page.length < picked.length ? cursor + page.length : null;
    return { total: total, returned: page.length, next_cursor: next, ops: page };
  }

  function demoPost(path, payload) {
    var F = fixtures();
    if (path === "/api/evaluate") {
      var table = F.evaluate[payload.case] || {};
      var hit = table[payload.output];
      if (hit) return hit;
      return {
        ok: false, time: null, lb: null, groups: [], engines: [], grid: null,
        K: null, psi: [],
        errors: [{
          category: "demo", t: null, at: null,
          message: "演示夹具只自带有限条判题响应；请连真实服务（?demo=1 仅用于界面预览）。"
        }]
      };
    }
    throw new ApiError(404, path, { error: "demo-route" });
  }

  function DemoEventSource(events) {
    var self = this;
    this._listeners = {};
    this._timers = [];
    this.onopen = null;
    this.onerror = null;
    this._timers.push(setTimeout(function () { if (self.onopen) self.onopen(); }, 120));
    (events || []).forEach(function (event, index) {
      self._timers.push(setTimeout(function () {
        self._emit(event.type, event.data);
      }, 700 * (index + 1)));
    });
  }
  DemoEventSource.prototype.addEventListener = function (type, fn) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(fn);
  };
  DemoEventSource.prototype._emit = function (type, data) {
    var listeners = this._listeners[type] || [];
    listeners.forEach(function (fn) {
      fn({ type: type, data: JSON.stringify(data) });
    });
  };
  DemoEventSource.prototype.close = function () {
    this._timers.forEach(function (id) { clearTimeout(id); });
    this._timers = [];
  };

  /* ── 数据访问 ─────────────────────────────────────────────────── */
  function rememberRun(run) {
    if (!run || !run.run_id) return;
    var merged = {};
    var old = S.runs.get(run.run_id);
    if (old) Object.keys(old).forEach(function (k) { merged[k] = old[k]; });
    Object.keys(run).forEach(function (k) {
      if (run[k] !== undefined) merged[k] = run[k];
    });
    S.runs.set(run.run_id, merged);
  }

  function versionOfRun(runId) {
    var found = null;
    S.versions.forEach(function (v) { if (v.run_id === runId) found = v; });
    return found;
  }

  function runOf(runId) { return S.runs.get(runId) || null; }

  function runSeq(r) {
    var match = /(\d+)/.exec(String((r && r.run_id) || ""));
    return match ? parseInt(match[1], 10) : 0;
  }

  function isNewerRun(a, b) {
    var ta = String((a && a.created_at) || "");
    var tb = String((b && b.created_at) || "");
    if (ta && tb) return ta > tb || (ta === tb && runSeq(a) > runSeq(b));
    // meta.active_runs / SSE 不带 created_at：用 run_id 序号兜底。
    return runSeq(a) > runSeq(b);
  }

  function newestRun() {
    var act = activeRuns();
    var best = null;
    if (act.length) {
      // §5.3 / F4：只要有 queued/running 的 run，状态条必须显示它（优先最新提交的那个）。
      act.forEach(function (r) { if (!best || isNewerRun(r, best)) best = r; });
      return best;
    }
    function scan(r) {
      if (!r || !r.run_id) return;
      if (!best || isNewerRun(r, best)) best = r;
    }
    S.runList.forEach(scan);
    S.runs.forEach(scan);
    if (!best && S.meta && S.meta.last_run) best = S.meta.last_run;
    return best;
  }

  function activeRuns() {
    var out = [];
    function add(r) {
      if (!r || !r.run_id) return;
      var merged = S.runs.get(r.run_id) || r;
      var state = merged.state || "";
      if (state !== "queued" && state !== "running") return;
      var exists = false;
      out.forEach(function (x) { if (x.run_id === r.run_id) exists = true; });
      if (!exists) out.push(merged);
    }
    S.runs.forEach(add);
    S.runList.forEach(add);
    return out;
  }

  function casesOfRun(runId) {
    var out = [];
    var run = runOf(runId);
    if (run && run.case_states && typeof run.case_states === "object") {
      Object.keys(run.case_states).forEach(function (c) {
        if (out.indexOf(c) < 0) out.push(c);
      });
    }
    if (run && Array.isArray(run.results)) {
      run.results.forEach(function (r) { if (r && r.case && out.indexOf(r.case) < 0) out.push(r.case); });
    }
    var v = versionOfRun(runId);
    if (v && v.cases) {
      Object.keys(v.cases).forEach(function (c) { if (out.indexOf(c) < 0) out.push(c); });
    }
    return out;
  }

  function caseOk(runId, caseName) {
    var run = runOf(runId);
    if (run && Array.isArray(run.results)) {
      for (var i = 0; i < run.results.length; i += 1) {
        if (run.results[i] && run.results[i].case === caseName) {
          if (run.results[i].state === "timeout") return "timeout";
          return run.results[i].ok ? "ok" : "bad";
        }
      }
    }
    var v = versionOfRun(runId);
    if (v && v.cases && v.cases[caseName]) return v.cases[caseName].ok ? "ok" : "bad";
    return "";
  }

  function baseOfCase(runId, caseName) {
    var v = versionOfRun(runId);
    if (v && v.cases && v.cases[caseName]) return num(v.cases[caseName].base);
    return null;
  }

  function pickInitialRun() {
    if (S.runId && S.runs.has(S.runId)) return S.runId;
    var best = null;
    S.versions.forEach(function (v) {
      if (v.rank === 1 && v.run_id) best = v.run_id;
    });
    if (best) return best;
    var done = null;
    S.runList.forEach(function (r) {
      if (r && r.state === "done" && !done) done = r.run_id;
    });
    if (done) return done;
    if (S.versions.length) return S.versions[0].run_id;
    if (S.runList.length) return S.runList[0].run_id;
    return "";
  }

  /* ── 加载 ─────────────────────────────────────────────────────── */
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var tag = document.createElement("script");
      tag.src = src;
      tag.onload = function () { resolve(); };
      tag.onerror = function () { reject(new Error("无法加载 " + src)); };
      document.head.appendChild(tag);
    });
  }

  function connected() {
    S.connected = true;
    var es = $("emptystate");
    if (es) es.hidden = true;
  }

  function disconnected(err) {
    S.connected = false;
    setSSE("off");
    if (S.es) { try { S.es.close(); } catch (e) { /* ignore */ } S.es = null; }
    var box = $("emptystate");
    if (box) box.hidden = false;
    setText("es-detail", describeError(err));
    var input = $("es-base");
    if (input) input.value = S.base;
    setText("es-title", "后端未连接");
    setFooter("后端未连接 · " + S.base);
    renderEmptyAll();
  }

  function renderEmptyAll() {
    var verdict = $("verdict");
    if (verdict) verdict.dataset.state = "empty";
    setText("vbadge", "无数据");
    setText("vtime", "—");
    setText("vdiff", "—");
    setHTML("vstats", "");
    setHTML("vbars", "");
    setHTML("casebar", "");
    setHTML("checks", '<div class="empty">后端未连接</div>');
    setHTML("memory", '<div class="empty">后端未连接</div>');
    setHTML("engines", '<div class="empty">后端未连接</div>');
    setHTML("gridinfo", '<div class="empty">后端未连接</div>');
    setHTML("errors", '<div class="empty">后端未连接</div>');
    setHTML("gantt", '<div class="empty">后端未连接 · 不做本地计算</div>');
    setHTML("oplbody", '<div class="empty">后端未连接</div>');
    setHTML("usepane", '<div class="empty">后端未连接</div>');
    setHTML("timepane", '<div class="empty">后端未连接</div>');
    setHTML("runhead", '<div class="empty">后端未连接</div>');
    setHTML("versions", '<div class="empty">后端未连接</div>');
    setHTML("runs", '<div class="empty">后端未连接</div>');
    setHTML("trend", '<div class="empty">后端未连接</div>');
    setHTML("diffpane", '<div class="empty">后端未连接</div>');
    setHTML("vpop", "");
    setHTML("ftabs", "");
    setText("oplcnt", "");
    setText("st-ledger", "—");
    setText("st-run", "—");
    setText("st-runstate", "—");
    setText("file-run", "—");
    setText("file-run-meta", "");
    setText("file-case", "—");
    setText("file-case-meta", "");
  }

  async function refreshData() {
    var health = await api("/api/health").catch(function () { return null; });
    var versions = await api("/api/versions");
    if (!Array.isArray(versions)) throw new Error("/api/versions 未返回数组");
    var meta = await api("/api/meta").catch(function () { return null; });
    S.health = health;
    S.meta = meta;
    S.versions = versions;
    S.runList = [];
    versions.forEach(function (v) {
      var row = {
        run_id: v.run_id, state: v.state || "done", version: v.version, commit: v.commit,
        actor: v.actor, created_at: v.created_at, score: v.score, rank: v.rank, ok: v.ok
      };
      rememberRun(row);
      S.runList.push(row);
    });
    if (meta) {
      [meta.last_run].concat(Array.isArray(meta.active_runs) ? meta.active_runs : []).forEach(function (r) {
        if (!r || !r.run_id) return;
        rememberRun(r);
        var exists = false;
        S.runList.forEach(function (x) { if (x && x.run_id === r.run_id) exists = true; });
        if (!exists) S.runList.push(r);
      });
    }
    if (!S.runList.length) S.runList = Array.from(S.runs.values());
    renderStatus();
    renderVersions();
    renderRuns();
    renderTrend();
    renderVersionPopover();
    renderCompareOptions();
    markUpdated();
  }

  async function ensureSelection() {
    var runId = S.runId;
    if (!runId || !S.runs.has(runId)) runId = pickInitialRun();
    if (!runId) {
      renderEmptyAll();
      setFooter("服务已连接，但账本里还没有 run");
      return;
    }
    await selectRun(runId, S.caseName);
  }

  async function selectRun(runId, caseName) {
    if (!runId) return;
    S.runId = runId;
    renderStatus();
    setFooter("加载 " + runId + " …");
    var run = null;
    try {
      run = await api("/api/runs/" + encodeURIComponent(runId));
      rememberRun(run);
    } catch (err) {
      if (err.status !== 404 && err.status !== 409) { disconnected(err); return; }
      if (err.status === 409) setFooter(runId + " 尚未就绪（" + (err.body && err.body.state ? err.body.state : "running") + "）");
    }
    renderRunHead();
    renderCaseTabs();
    var cases = casesOfRun(runId);
    var nextCase = caseName && cases.indexOf(caseName) >= 0 ? caseName : cases[0];
    if (!nextCase) {
      S.detail = null;
      S.caseName = "";
      renderAll();
      setFooter(runId + " 暂无已完成的用例（state=" + ((run && run.state) || "?") + "）");
      return;
    }
    S.caseName = nextCase;
    await loadCase();
  }

  async function selectCase(caseName) {
    if (!caseName || caseName === S.caseName) return;
    S.caseName = caseName;
    await loadCase();
  }

  function rangeFor(detail, items) {
    var end = num(detail && detail.time);
    if (end === null || end < 0) {
      var maxT = 0;
      (items || []).forEach(function (o) {
        var t = num(o.t);
        if (t !== null && t > maxT) maxT = t;
      });
      end = maxT;
    }
    if (end < 1) end = 1;
    return { t0: 0, t1: end + 1 };
  }

  async function loadOps(win) {
    var params = { limit: 4000 };
    if (win && num(win.since) !== null) params.since = win.since;
    if (win && num(win.until) !== null) params.until = win.until;
    if (S.filters.group !== "all") params.group = S.filters.group;
    if (S.filters.mb !== "all") params.mb = S.filters.mb;
    var data = await api("/api/runs/" + encodeURIComponent(S.runId) + "/cases/" +
      encodeURIComponent(S.caseName) + "/ops", params);
    S.ops = {
      total: num(data.total) === null ? 0 : data.total,
      returned: num(data.returned) === null ? (data.ops || []).length : data.returned,
      next: num(data.next_cursor) === null ? null : data.next_cursor,
      items: Array.isArray(data.ops) ? data.ops : [],
      window: win || null
    };
    S.window = win || null;
  }

  async function loadCompareOptionsAndData() {
    renderCompareOptions();
    var select = $("cmpsel");
    var wanted = select && select.value ? select.value : S.ab.runId;
    if (wanted && wanted === S.runId) wanted = "";
    if (wanted) {
      await loadCompare(wanted);
    } else {
      S.ab = { runId: "", detail: null, ops: null, scale: S.ab.scale || "abs" };
    }
  }

  async function loadCompare(runId) {
    if (!runId || runId === S.runId) {
      S.ab = { runId: "", detail: null, ops: null, scale: S.ab.scale || "abs" };
      return;
    }
    try {
      var detail = await api("/api/runs/" + encodeURIComponent(runId) + "/cases/" +
        encodeURIComponent(S.caseName));
      var win = S.window || { since: 0, until: S.range.t1 };
      var ops = await api("/api/runs/" + encodeURIComponent(runId) + "/cases/" +
        encodeURIComponent(S.caseName) + "/ops", {
        limit: 4000, since: win.since, until: win.until
      });
      S.ab = {
        runId: runId, detail: detail,
        ops: Array.isArray(ops.ops) ? ops.ops : [],
        total: num(ops.total) === null ? 0 : ops.total,
        scale: S.ab.scale || "abs"
      };
      renderCompareOptions();
    } catch (err) {
      S.ab = {
        runId: "", detail: null, ops: null, scale: S.ab.scale || "abs",
        error: "B 不可用：" + (err.status === 404 ? "该 run 没有这个用例" : describeError(err))
      };
      var select = $("cmpsel");
      if (select) select.value = "";
      renderGantt();
      renderDiff();
    }
  }

  async function loadCase() {
    var runId = S.runId, caseName = S.caseName;
    setFooter("加载 " + runId + " · " + caseName + " …");
    try {
      var detail = await api("/api/runs/" + encodeURIComponent(runId) + "/cases/" + encodeURIComponent(caseName));
      S.detail = detail;
      S.sel = null;
      S.ops = null;
      S.range = rangeFor(detail, []);
      S.window = { since: 0, until: S.range.t1 };
      try {
        await loadOps(S.window);
      } catch (opsErr) {
        // 用例详情有了、ops 取不到（服务未保留 / 切片失败）：保留详情，只把 ops 面板置空。
        S.ops = { total: 0, returned: 0, next: null, items: [], window: S.window, error: describeError(opsErr) };
        setFooter("用例已加载，但 ops 不可用：" + describeError(opsErr));
      }
      if (num(detail.time) === null) S.range = rangeFor(detail, S.ops.items);
      await loadCompareOptionsAndData();
      renderAll();
      renderTrunc();
      setFooter("已加载 " + runId + " · " + caseName + " · 所有数值来自服务端");
      markUpdated();
    } catch (err) {
      if (err.status === 409) {
        S.detail = null;
        renderAll();
        setFooter("结果未就绪：" + caseName + "（" + ((err.body && err.body.state) || "running") + "）");
      } else if (err.status === 404) {
        S.detail = null;
        renderAll();
        setFooter("用例不存在：" + caseName + "（服务端 404）");
      } else {
        disconnected(err);
      }
    }
  }

  /* ── SSE ──────────────────────────────────────────────────────── */
  function connectEvents() {
    if (S.es) { try { S.es.close(); } catch (e) { /* ignore */ } S.es = null; }
    setSSE("connecting");
    if (S.mode === "demo") {
      S.es = new DemoEventSource(fixtures().events || []);
      bindEvents(S.es);
      setSSE("demo");
      return;
    }
    var es;
    try {
      es = new EventSource(S.base + "/api/events");
    } catch (err) {
      setSSE("error");
      return;
    }
    S.es = es;
    bindEvents(es);
    es.onopen = function () { setSSE("open"); };
    es.onerror = function () { setSSE("error"); };
  }

  function bindEvents(es) {
    STATES.forEach(function (state) {
      es.addEventListener("run." + state, function (event) {
        onRunEvent(state, event);
      });
    });
    es.addEventListener("message", function (event) {
      var data = parseEvent(event);
      if (data && data.state) onRunEvent(data.state, event);
    });
    // hello / snapshot：服务端给的活动 run 快照（queued / running）。历史 run 仍从
    // /api/versions 与 /api/runs/{id} 取，绝不把快照当“全部 run”。
    es.addEventListener("hello", function (event) {
      var data = parseEvent(event) || {};
      var list = Array.isArray(data.runs) ? data.runs
        : (Array.isArray(data.active_runs) ? data.active_runs : []);
      list.forEach(rememberRun);
      renderStatus();
      renderRuns();
    });
  }

  function parseEvent(event) {
    try { return JSON.parse(event.data); } catch (e) { return null; }
  }

  function onRunEvent(state, event) {
    var data = parseEvent(event) || {};
    var runId = data.run_id || (data.run && data.run.run_id);
    if (!runId) return;
    var patch = { run_id: runId, state: state };
    if (num(data.done) !== null) patch.done = data.done;
    if (num(data.total) !== null) patch.total = data.total;
    if (data.case) patch.last_case = data.case;
    rememberRun(patch);
    if (S.mode === "demo") setSSE("demo");
    renderStatus();
    renderRuns();
    renderRunHead();
    if (runId === S.runId) {
      if (state === "running" || state === "queued") {
        pollRun(runId);
        scheduleSoftRefresh(900);
      } else {
        scheduleSoftRefresh(300);
      }
    } else if (state === "done" || state === "failed" || state === "timeout") {
      scheduleSoftRefresh(600);
    }
  }

  function scheduleSoftRefresh(delay) {
    if (S.pollTimer) clearTimeout(S.pollTimer);
    S.pollTimer = setTimeout(function () {
      S.pollTimer = null;
      softRefresh();
    }, delay);
  }

  async function softRefresh() {
    try {
      if (S.mode === "demo") {
        // 静态夹具没有“服务端新状态”，重拉会把 SSE 演示出来的终态覆盖回旧值。
        renderStatus();
        renderRuns();
        return;
      }
      await refreshData();
      await ensureSelection();
    } catch (err) {
      disconnected(err);
    }
  }

  function pollRun(runId) {
    api("/api/runs/" + encodeURIComponent(runId)).then(function (run) {
      rememberRun(run);
      renderStatus();
      renderRuns();
      renderRunHead();
      renderCaseTabs();
    }).catch(function () { /* 轮询失败不升级为空态，SSE 仍在 */ });
  }

  /* ── 渲染：状态条 / 用例标签 / 判分条 ─────────────────────────── */
  function renderStatus() {
    setText("st-base", S.base);
    var lines = S.health && num(S.health.ledger_lines) !== null ? S.health.ledger_lines : null;
    setText("st-ledger", lines === null ? "—" : String(lines));
    var ledger = $("st-ledger");
    if (ledger) ledger.title = lines === null ? "服务未提供 /api/health.ledger_lines" : "账本行数（服务端）";
    var newest = newestRun();
    var shownId = newest && newest.run_id ? newest.run_id : S.runId;
    var run = shownId ? runOf(shownId) : null;
    setText("st-run", shownId || "—");
    var stateEl = $("st-runstate");
    if (stateEl) {
      stateEl.dataset.state = run && run.state ? run.state : "";
      stateEl.textContent = run && run.state ? STATE_LABEL[run.state] || run.state : "—";
      stateEl.title = "created_at 最新的 run（S.runs ∪ runList，SSE 实时维护）";
    }
    var actEl = $("st-active");
    if (actEl) {
      var act = activeRuns();
      if (!act.length) {
        actEl.dataset.state = "";
        actEl.textContent = "—";
        actEl.title = "没有 queued / running 的 run";
      } else {
        var first = act[0];
        var prog = num(first.done) !== null && num(first.total) !== null ?
          " " + first.done + "/" + first.total : "";
        actEl.dataset.state = first.state || "";
        actEl.textContent = (act.length > 1 ? act.length + " · " : "") + first.run_id +
          " " + (STATE_LABEL[first.state] || first.state) + prog;
        actEl.title = act.map(function (r) { return r.run_id + " · " + r.state; }).join("\n");
      }
    }
    setText("st-updated", S.updatedAt || "—");
    renderMode();
  }

  function renderCaseTabs() {
    var box = $("casebar");
    if (!box) return;
    if (!S.runId) { box.innerHTML = ""; return; }
    var cases = casesOfRun(S.runId);
    box.innerHTML = cases.map(function (c) {
      var kind = caseOk(S.runId, c);
      var mark = kind === "bad" ? ' <span class="bad">✕</span>' : kind === "timeout" ? ' <span class="bad">⏱</span>' : "";
      return '<button class="case-tab" data-case="' + esc(c) + '" aria-selected="' +
        (c === S.caseName ? "true" : "false") + '">' + esc(c) + mark + "</button>";
    }).join("");
    setText("file-run", S.runId || "—");
    var run = runOf(S.runId);
    setText("file-run-meta", run ? "state " + (run.state || "?") + " · " + (run.version || "?") : "");
    setText("file-case", S.caseName || "—");
    var detail = S.detail;
    setText("file-case-meta", detail ? "grid " + gridText(detail) + " · ops " + fmtInt(detail.ops_total) : "");
  }

  function gridText(detail) {
    if (!detail || !detail.grid) return "—";
    var g = detail.grid;
    return fmtInt(g.V) + "×" + fmtInt(g.P);  // 2026-10 版题面取消了 D
  }

  function renderVerdict() {
    var box = $("verdict");
    var detail = S.detail;
    if (!detail) {
      if (box) box.dataset.state = "empty";
      setText("vbadge", "无数据");
      setText("vtime", "—");
      setText("vdiff", "—");
      setHTML("vstats", "");
      setHTML("vbars", "");
      return;
    }
    var ok = !!detail.ok;
    if (box) box.dataset.state = ok ? "ok" : "bad";
    var badge = $("vbadge");
    if (badge) badge.textContent = ok ? "合法 · 服务端判定" :
      "非法 · " + ((detail.errors || []).length) + " 条错误";
    var time = num(detail.time);
    setText("vtime", time === null ? "—" : String(time));
    var base = baseOfCase(S.runId, S.caseName);
    var diffEl = $("vdiff");
    if (diffEl) {
      if (time !== null && base !== null) {
        var delta = time - base;
        diffEl.className = "vdiff " + (delta < 0 ? "better" : delta > 0 ? "worse" : "flat");
        diffEl.textContent = "基线 " + base + " · Δ " + (delta > 0 ? "+" : "") + delta;
        diffEl.title = "Δ 仅为显示：服务端 time 与版本基线 base 的差";
      } else {
        diffEl.className = "vdiff flat";
        diffEl.textContent = "基线 —";
        diffEl.title = "版本 / 基线来自 /api/versions";
      }
    }
    var version = versionOfRun(S.runId);
    var lbValue = num(detail.lb);
    setHTML("vstats",
      '<div class="stat"><div class="k">下界 lb</div><div class="v">' + fmtInt(lbValue) + "</div></div>" +
      '<div class="stat"><div class="k">网格 V×P</div><div class="v">' + esc(gridText(detail)) + "</div></div>" +
      '<div class="stat"><div class="k">卡组 K</div><div class="v">' + fmtInt(detail.K) + "</div></div>" +
      '<div class="stat"><div class="k">ops</div><div class="v">' + fmtInt(detail.ops_total) + "</div></div>");
    var lb = lbValue;
    var den = time !== null ? time : (lb !== null ? lb : 1);
    var bars = "";
    if (time !== null) {
      bars += '<div class="vbar-row"><span class="cap">Time</span><span class="vbar"><i class="tm" style="width:' +
        pct(time, den) + '%"></i></span><span class="val">' + time + "</span></div>";
    }
    if (lb !== null) {
      bars += '<div class="vbar-row"><span class="cap">lb</span><span class="vbar"><i class="lb" style="width:' +
        pct(lb, den) + '%"></i></span><span class="val">' + lb + "</span></div>";
    }
    if (version) {
      var vScore = version.score;
      bars += '<div class="vnote">相对分 ' + fmtScore(vScore) + " · 排名 " +
        (num(version.rank) === null ? "—" : "#" + version.rank) + "（服务端）</div>";
    } else {
      bars += '<div class="vnote">该 run 无版本记录（/api/versions）</div>';
    }
    setHTML("vbars", bars);
  }

  /* ── 渲染：左栏 ───────────────────────────────────────────────── */
  function renderChecks() {
    var detail = S.detail;
    var tag = $("checks-tag");
    if (!detail) {
      setHTML("checks", '<div class="empty">无数据</div>');
      if (tag) tag.textContent = "—";
      return;
    }
    var errors = Array.isArray(detail.errors) ? detail.errors : [];
    if (tag) tag.textContent = detail.ok ? "全部通过" : errors.length + " 条错误";
    var html = "";
    CHECK_ITEMS.forEach(function (item) {
      var hits = errors.filter(function (e) { return e && e.category === item.cat; });
      var cls = detail.ok || hits.length === 0 ? "ok" : "bad";
      var icon = cls === "ok" ? "✓" : "✕";
      var detailText = hits.length === 0 ? "无 " + item.cat + " 类错误" :
        esc(hits[0].message || "") + (hits[0].at ? " · " + esc(hits[0].at) : "");
      html += '<div class="check ' + cls + '"><span class="ic">' + icon + "</span><div>" +
        '<div class="n">' + esc(item.name) + "</div>" +
        '<div class="d"><em>' + esc(item.hint) + "</em> · " + detailText + "</div></div></div>";
    });
    setHTML("checks", html);
  }

  function renderMemory() {
    var detail = S.detail;
    var tag = $("memory-tag");
    if (!detail || !Array.isArray(detail.groups) || !detail.groups.length) {
      setHTML("memory", '<div class="empty">服务端未返回 groups</div>');
      if (tag) tag.textContent = "—";
      return;
    }
    if (tag) tag.textContent = detail.groups.length + " 个卡组";
    var html = "";
    detail.groups.forEach(function (g) {
      var limit = num(g.limit);
      var den = limit !== null && limit > 0 ? limit : 1;
      var parts = [
        { cls: "e", key: "Mexp", value: num(g.mexp) },
        { cls: "o", key: "Movl", value: num(g.movl) },
        { cls: "a", key: "Mact", value: num(g.mact) }
      ];
      html += '<div class="memgrp"><div class="hd"><span>卡组 v' + esc(g.v) + "</span>" +
        '<span class="lim">上限 ' + fmtInt(limit) + "</span></div>";
      html += '<div class="stack">';
      parts.forEach(function (p) {
        if (p.value === null || p.value <= 0) return;
        html += '<i class="' + p.cls + '" style="width:' + clampPct(p.value, den) + '%"></i>';
      });
      html += "</div><div class=\"memkey\">";
      parts.forEach(function (p) {
        html += "<span><b style=\"background:" + (p.cls === "e" ? "#5b8ec9" : p.cls === "o" ? "#d98b3a" : "#8a5cc4") +
          "\"></b>" + p.key + " " + fmtInt(p.value) + "</span>";
      });
      html += "</div></div>";
    });
    html += '<div class="note">三个数值均由服务端 <code>groups[]</code> 给出；' +
      "本页只画三段长度，<b>不计算内存峰值</b>。</div>";
    setHTML("memory", html);
  }

  function renderEngines() {
    var detail = S.detail;
    var tag = $("engines-tag");
    if (!detail || !Array.isArray(detail.engines) || !detail.engines.length) {
      setHTML("engines", '<div class="empty">服务端未返回 engines</div>');
      if (tag) tag.textContent = "—";
      return;
    }
    if (tag) tag.textContent = detail.engines.length + " 组";
    var span = S.range.t1 - S.range.t0;
    if (span < 1) span = 1;
    var html = "";
    detail.engines.forEach(function (e) {
      var comp = num(e.comp), comm = num(e.comm);
      html += '<div class="eng"><div class="hd"><span>卡组 v' + esc(e.v) + "</span>" +
        '<span class="m">comp ' + fmtInt(comp) + " · comm " + fmtInt(comm) + "</span></div>";
      html += '<div class="row"><span>计算</span><span class="track"><i class="c" style="width:' +
        clampPct(comp, span) + '%"></i></span><span class="v">' + fmtInt(comp) + "</span></div>";
      html += '<div class="row"><span>通信</span><span class="track"><i class="m" style="width:' +
        clampPct(comm, span) + '%"></i></span><span class="v">' + fmtInt(comm) + "</span></div>";
      html += '<div class="sub">comm_first ' + fmtInt(e.comm_first) + " → comm_last " +
        fmtInt(e.comm_last) + "</div></div>";
    });
    html += '<div class="note">占用条只按服务端数值缩放，<b>不重算引擎时长</b>。</div>';
    setHTML("engines", html);
  }

  function renderGridinfo() {
    var detail = S.detail;
    if (!detail) {
      setHTML("gridinfo", '<div class="empty">无数据</div>');
      setText("gridinfo-tag", "—");
      return;
    }
    var version = versionOfRun(S.runId);
    var run = runOf(S.runId);
    var rows = [
      ["用例", esc(S.caseName)],
      ["run", esc(S.runId)],
      ["版本", esc(version ? version.version : (run ? run.version : "—"))],
      ["commit", esc(version ? version.commit : (run ? run.commit : "—"))],
      ["actor", esc(version ? version.actor : (run ? run.actor : "—"))],
      ["网格", esc(gridText(detail))],
      ["K", fmtInt(detail.K)],
      ["psi", Array.isArray(detail.psi) && detail.psi.length ? esc(detail.psi.join(", ")) : "—"],
      ["ops_total", fmtInt(detail.ops_total)],
      ["solve_ms", fmtInt(detail.solve_ms)],
      ["output_sha256", esc(detail.output_sha256 || "—")]
    ];
    setHTML("gridinfo", '<div class="kv">' + rows.map(function (row) {
      return '<span class="k">' + row[0] + '</span><span class="v">' + row[1] + "</span>";
    }).join("") + "</div>" +
      '<div class="srcnote">来源字段全部来自 <code>/api/versions</code> 与 <code>/api/runs</code>；' +
      "运行态见右栏。</div>");
    setText("gridinfo-tag", S.caseName || "—");
  }

  function renderErrors() {
    var detail = S.detail;
    var tag = $("errors-tag");
    var errors = detail && Array.isArray(detail.errors) ? detail.errors : [];
    if (!detail) {
      setHTML("errors", '<div class="empty">无数据</div>');
      if (tag) tag.textContent = "—";
      return;
    }
    if (!errors.length) {
      setHTML("errors", '<div class="empty">服务端未返回错误（' +
        (detail.ok ? "合法" : "ok:false 但 errors 为空") + "）</div>");
      if (tag) tag.textContent = "0";
      return;
    }
    if (tag) tag.textContent = String(errors.length);
    var html = "";
    errors.slice(0, 40).forEach(function (e) {
      var t = num(e.t);
      var at = e.at ? ' · <span>' + esc(e.at) + "</span>" : "";
      var extra = "";
      Object.keys(e).forEach(function (key) {
        if (key === "category" || key === "message" || key === "t" || key === "at") return;
        if (e[key] === null || e[key] === undefined) return;
        extra += " " + key + "=" + esc(e[key]);
      });
      html += '<div class="err" data-t="' + (t === null ? "" : t) + '">' +
        '<div class="t"><span class="cat">' + esc(e.category || "error") + "</span>" +
        (t === null ? "" : "<span>t=" + t + "</span>") + at + "</div>" +
        '<div class="m">' + esc(e.message || "") + "</div>" +
        (extra ? '<div class="fix">' + extra.trim() + "</div>" : "") + "</div>";
    });
    if (errors.length > 40) html += '<div class="empty">还有 ' + (errors.length - 40) + " 条，见服务端响应</div>";
    setHTML("errors", html);
  }

  /* ── 渲染：Gantt ──────────────────────────────────────────────── */
  function trackMetrics() {
    var wrap = $("ganttwrap");
    var width = wrap && wrap.clientWidth ? wrap.clientWidth : 900;
    var total = width * S.zoom;
    var lane = total - 56;
    if (lane < 1) lane = 1;
    return { total: total, lane: lane };
  }

  function rangeSpan(range) {
    var span = range.t1 - range.t0;
    return span > 0 ? span : 1;
  }

  function xFor(t, range, lane) {
    return 56 + ((t - range.t0) * lane) / rangeSpan(range);
  }

  function niceStep(span) {
    var steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500,
      5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000];
    for (var i = 0; i < steps.length; i += 1) {
      if (span / steps[i] <= 10) return steps[i];
    }
    return steps[steps.length - 1];
  }

  function rulerHTML(metrics) {
    var step = niceStep(rangeSpan(S.range));
    var html = '<div class="ruler" style="width:' + metrics.total + 'px">';
    var t = 0;
    while (t <= S.range.t1) {
      var x = xFor(t, S.range, metrics.lane);
      var major = t % (step * 5) === 0 ? " major" : "";
      html += '<div class="tick' + major + '" style="left:' + x.toFixed(1) +
        'px"><span>' + t + "</span></div>";
      t += step;
    }
    return html + "</div>";
  }

  function groupIds() {
    var ids = [];
    var detail = S.detail;
    if (detail && Array.isArray(detail.groups)) {
      detail.groups.forEach(function (g) {
        if (ids.indexOf(g.v) < 0) ids.push(g.v);
      });
    }
    if (S.ops) {
      S.ops.items.forEach(function (o) {
        if (ids.indexOf(o.g) < 0) ids.push(o.g);
      });
    }
    return ids.sort(function (a, b) { return a - b; });
  }

  function opKind(op) {
    if (COMP_OPS[op]) return "comp";
    if (COMM_OPS[op]) return "comm";
    return "";
  }

  function opPhase(op) { return BACKWARD[op] ? "bwd" : "fwd"; }

  function matchFilters(o) {
    if (S.filters.layer !== "all" && String(o.l) !== String(S.filters.layer)) return false;
    var kind = S.filters.kind;
    if (kind === "all") return true;
    if (kind === "comp" || kind === "comm") return opKind(o.op) === kind;
    return opPhase(o.op) === kind;
  }

  function visibleLanes() {
    if (S.filters.kind === "comp") return ["comp"];
    if (S.filters.kind === "comm") return ["comm"];
    return ["comp", "comm"];
  }

  function lanesLabel(kind, ghost) {
    var base = kind === "comp" ? "计算引擎" : "通信引擎";
    return ghost ? "B·" + (kind === "comp" ? "算" : "通") : base;
  }

  function isSelected(o, ghost) {
    if (!S.sel || ghost) return false;
    return S.sel.t === o.t && S.sel.mb === o.mb && S.sel.l === o.l && S.sel.op === o.op;
  }

  function opTip(o) {
    var kind = opKind(o.op);
    var t = o.t, dur = o.dur, mb = o.mb, l = o.l, g = o.g;
    return t + " · " + mb + ":" + l + ":" + o.op + "\n" +
      (kind === "comp" ? "计算引擎" : "通信引擎") + " · dur " + dur + " · 卡组 " + g;
  }

  function opsHTML(list, range, metrics, ghost) {
    var html = "";
    list.forEach(function (o) {
      var t = num(o.t);
      var dur = num(o.dur);
      if (t === null || dur === null) return;
      var x = xFor(t, range, metrics.lane);
      var kind = opKind(o.op);
      var sel = isSelected(o, ghost) ? " sel" : "";
      var ghostCls = ghost ? " ghost" : "";
      var phaseCls = BACKWARD[o.op] ? " bwd" : "";
      var attrs = ' data-t="' + t + '" data-mb="' + o.mb + '" data-l="' + o.l +
        '" data-op="' + esc(o.op) + '" data-g="' + o.g + '" data-e="' + kind + '"' +
        ' data-tip="' + esc(opTip(o)) + '"' + (ghost ? ' data-ghost="1"' : "");
      if (dur <= 0) {
        html += '<span class="zm' + ghostCls + sel + '" style="left:' + (x - 2.5).toFixed(1) +
          'px"' + attrs + "></span>";
      } else {
        var width = (dur * metrics.lane) / rangeSpan(range);
        if (width < 3) width = 3;
        html += '<div class="op' + phaseCls + ghostCls + sel + '" style="left:' + x.toFixed(1) +
          "px;width:" + width.toFixed(1) + 'px"' + attrs + ">" + esc(o.op) + "</div>";
      }
    });
    return html;
  }

  function activationHTML(groupId, metrics, range, items, ghost) {
    // 激活存活 = 同一 (mb, 层) 的 comb 结束 → s_bwd 开始，闭区间（题面 §4.6）。
    // 这里只是把服务端 ops 的两个时刻画成区间/点；内存峰值由 groups[].mact 给出。
    var keys = [];
    items.forEach(function (o) {
      if (o.g !== groupId) return;
      var key = o.mb + ":" + o.l;
      if (keys.indexOf(key) < 0) keys.push(key);
    });
    var html = "";
    keys.forEach(function (key) {
      var parts = key.split(":");
      var mb = Number(parts[0]);
      var layer = Number(parts[1]);
      var combEnd = null;
      var bwdStart = null;
      items.forEach(function (o) {
        if (o.g !== groupId || o.mb !== mb || o.l !== layer) return;
        var t = num(o.t), dur = num(o.dur);
        if (t === null) return;
        if (o.op === "comb") {
          var finish = t + (dur === null ? 0 : dur);
          if (combEnd === null || finish > combEnd) combEnd = finish;
        }
        if (o.op === "s_bwd") {
          if (bwdStart === null || t < bwdStart) bwdStart = t;
        }
      });
      if (combEnd === null || bwdStart === null || bwdStart < combEnd) return;
      var x = xFor(combEnd, range, metrics.lane);
      var tip = "激活存活（闭区间）· mb " + mb + " · 层 " + layer +
        " · [" + combEnd + ", " + bwdStart + "]";
      if (bwdStart === combEnd) {
        html += '<span class="span point' + (ghost ? " ghost" : "") + '" style="left:' +
          (x - 2.5).toFixed(1) + 'px" data-tip="' + esc(tip) + '"></span>';
        return;
      }
      var width = (bwdStart - combEnd) * metrics.lane / rangeSpan(range);
      html += '<span class="span' + (ghost ? " ghost" : "") + '" style="left:' + x.toFixed(1) +
        "px;width:" + width.toFixed(1) + 'px" data-tip="' + esc(tip) + '"><span>L' + layer +
        "</span></span>";
    });
    return html;
  }

  function groupUtilHTML(groupId) {
    var engine = null;
    if (S.detail && Array.isArray(S.detail.engines)) {
      S.detail.engines.forEach(function (e) { if (e.v === groupId) engine = e; });
    }
    if (!engine) return "";
    var span = rangeSpan(S.range);
    return '<span class="util"><i>计算 <span class="bar"><b style="width:' +
      clampPct(engine.comp, span) + '%;background:var(--comp)"></b></span></i>' +
      "<i>通信 <span class=\"bar\"><b style=\"width:" + clampPct(engine.comm, span) +
      '%"></b></span></i></span>';
  }

  function groupHTML(groupId, metrics) {
    var items = S.ops ? S.ops.items : [];
    var layers = [];
    items.forEach(function (o) {
      if (o.g === groupId && layers.indexOf(o.l) < 0) layers.push(o.l);
    });
    layers.sort(function (a, b) { return a - b; });
    var html = '<div class="grp"><div class="grphd"><span class="nm">卡组 v' + esc(groupId) +
      '</span><span class="ly">层 ' + (layers.length ? esc(layers.join(",")) : "—") + "</span>" +
      groupUtilHTML(groupId) + "</div>";
    var lanes = visibleLanes();
    lanes.forEach(function (kind) {
      var list = items.filter(function (o) {
        return o.g === groupId && matchFilters(o) && opKind(o.op) === kind;
      });
      html += '<div class="lane" data-lane="' + kind + '"><div class="ll">' +
        lanesLabel(kind, false) + '</div><div class="track" style="left:56px;width:' +
        (metrics.lane) + 'px">' + opsHTML(list, S.range, metrics, false) + "</div></div>";
    });
    html += '<div class="lane act"><div class="ll">激活存活</div>' +
      '<div class="track" style="left:56px;width:' + metrics.lane + 'px">' +
      activationHTML(groupId, metrics, S.range, items.filter(matchFilters), false) + "</div></div>";
    if (S.ab.detail && Array.isArray(S.ab.ops)) {
      var bRange = S.ab.scale === "norm" ? rangeFor(S.ab.detail, S.ab.ops) : S.range;
      lanes.forEach(function (kind) {
        var ghostList = S.ab.ops.filter(function (o) {
          return o.g === groupId && matchFilters(o) && opKind(o.op) === kind;
        });
        if (!ghostList.length) return;
        html += '<div class="lane ghost" data-lane="' + kind + '"><div class="ll">' +
          lanesLabel(kind, true) + '</div><div class="track" style="left:56px;width:' +
          metrics.lane + 'px">' + opsHTML(ghostList, bRange, metrics, true) + "</div></div>";
      });
      html += '<div class="lane ghost act"><div class="ll">B·激活</div><div class="track" style="left:56px;width:' +
        metrics.lane + 'px">' + activationHTML(groupId, metrics, bRange,
          S.ab.ops.filter(matchFilters), true) + "</div></div>";
    }
    return html + "</div>";
  }

  function renderTrunc() {
    var box = $("gtrunc");
    if (!box) return;
    if (!S.ops || S.ops.total <= S.ops.returned) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    var more = S.ops.next !== null && S.ops.next !== undefined;
    box.innerHTML = '<span class="gtrunc-t">Gantt 截断：本页 <b>' + S.ops.returned +
      "</b> / <b>" + S.ops.total + "</b> 条 ops" +
      (S.ops.window ? " · 视口 [" + S.ops.window.since + ", " + S.ops.window.until + ")" : "") +
      "</span>" + (more ? '<button class="mini" id="gtrunc-more">载入下一页</button>' :
        '<span class="gtrunc-t">已到末页</span>');
  }

  async function loadMoreOps() {
    if (!S.ops || S.ops.next === null || S.ops.next === undefined) return;
    var win = S.ops.window;
    var params = { limit: 4000, cursor: S.ops.next };
    if (win) {
      params.since = win.since;
      params.until = win.until;
    }
    try {
      var data = await api("/api/runs/" + encodeURIComponent(S.runId) + "/cases/" +
        encodeURIComponent(S.caseName) + "/ops", params);
      var items = S.ops.items.concat(Array.isArray(data.ops) ? data.ops : []);
      S.ops = {
        total: num(data.total) === null ? S.ops.total : data.total,
        returned: items.length,
        next: num(data.next_cursor) === null ? null : data.next_cursor,
        items: items,
        window: win
      };
      renderGantt();
      renderOps();
      renderTrunc();
      setFooter("已追加下一页 ops（本页 " + items.length + " / " + S.ops.total + "）");
    } catch (err) {
      setFooter("载入下一页失败：" + describeError(err));
    }
  }

  function renderGantt() {
    var box = $("gantt");
    var wrap = $("ganttwrap");
    if (!box || !wrap) return;
    var left = wrap.scrollLeft;
    if (!S.detail) {
      box.innerHTML = '<div class="empty">无数据</div>';
      box.style.width = "auto";
      return;
    }
    var metrics = trackMetrics();
    var ids = groupIds();
    var html = rulerHTML(metrics);
    if (!S.ops) {
      html += '<div class="empty">正在按视口加载 ops …</div>';
    } else if (S.ops.error) {
      html += '<div class="empty">ops 不可用：' + esc(S.ops.error) + "</div>";
    } else if (!S.ops.items.length) {
      html += '<div class="empty">该切片内没有操作（since/until/筛选条件见操作清单）</div>';
    } else {
      ids.forEach(function (id) { html += groupHTML(id, metrics); });
    }
    box.style.width = metrics.total + "px";
    box.innerHTML = html;
    wrap.scrollLeft = left;
  }

  function renderOps() {
    var items = S.ops ? S.ops.items.filter(matchFilters) : [];
    var tag = $("oplcnt");
    if (tag) {
      var win = S.ops && S.ops.window ? " · 视口 [" + S.ops.window.since + ", " + S.ops.window.until + ")" : "";
      tag.textContent = S.ops
        ? "匹配 total " + S.ops.total + " · 本页 " + S.ops.returned + " · 显示 " + items.length + win
        : "—";
    }
    renderFilterTabs();
    if (!S.ops) {
      setHTML("oplbody", '<div class="empty">无 ops 数据</div>');
      return;
    }
    if (S.ops.error) {
      setHTML("oplbody", '<div class="empty">ops 不可用：' + esc(S.ops.error) +
        "<br>用例字段仍来自 /cases 接口；本页不回退本地计算。</div>");
      return;
    }
    if (!items.length) {
      setHTML("oplbody", '<div class="empty">当前筛选下没有操作</div>');
      return;
    }
    var body = $("oplbody");
    var keepTop = body ? body.scrollTop : 0;
    var rows = items.map(function (o) {
      var kind = opKind(o.op);
      var sel = isSelected(o, false) ? ' class="sel"' : "";
      var t = o.t, dur = o.dur, mb = o.mb, l = o.l, g = o.g;
      return "<tr" + sel + ' data-t="' + t + '" data-mb="' + mb + '" data-l="' + l +
        '" data-op="' + esc(o.op) + '" data-g="' + g + '" data-tip="' +
        esc(opTip(o)) + '"><td class="n">' + t + '</td><td class="n">' + mb +
        '</td><td class="n">' + l + '</td><td class="cellop"><span class="sw ' +
        (kind === "comm" ? "comm" : "") + '"></span>' + esc(o.op) + '</td><td class="n">' +
        dur + '</td><td class="n">' + g + "</td></tr>";
    }).join("");
    var html = '<table class="opl"><thead><tr><th>t</th><th>mb</th><th>l</th><th>op</th>' +
      "<th>dur</th><th>g</th></tr></thead><tbody>" + rows + "</tbody></table>";
    if (S.ops.total > S.ops.returned) {
      html += '<div class="opnotice">服务端共 <b>' + S.ops.total + "</b> 条，本页仅取 <b>" +
        S.ops.returned + "</b> 条（按视口切片）。缩放时间轴或加筛选会重新请求；" +
        "不一次性拉全量。</div>";
    }
    setHTML("oplbody", html);
    if (body) body.scrollTop = keepTop;
  }

  function renderFilterTabs() {
    var layerBox = $("ftabs");
    if (!layerBox) return;
    var layers = [];
    if (S.ops) {
      S.ops.items.forEach(function (o) { if (layers.indexOf(o.l) < 0) layers.push(o.l); });
    }
    layers.sort(function (a, b) { return a - b; });
    var html = "";
    html += tabBtn("layer", "all", "全部层");
    layers.forEach(function (l) { html += tabBtn("layer", String(l), "L" + l); });
    html += '<span style="width:8px"></span>';
    html += tabBtn("kind", "all", "全部");
    html += tabBtn("kind", "comp", "计算");
    html += tabBtn("kind", "comm", "通信");
    html += tabBtn("kind", "fwd", "前向");
    html += tabBtn("kind", "bwd", "反向");
    layerBox.innerHTML = html;
  }

  function tabBtn(group, value, label) {
    var selected = S.filters[group] === value;
    return '<button class="ftab" data-fgroup="' + group + '" data-fvalue="' + esc(value) +
      '" aria-selected="' + (selected ? "true" : "false") + '">' + esc(label) + "</button>";
  }

  /* ── 渲染：底部两栏 ───────────────────────────────────────────── */
  function renderUsePane() {
    var detail = S.detail;
    if (!detail || !Array.isArray(detail.engines) || !detail.engines.length) {
      setHTML("usepane", '<div class="empty">无数据</div>');
      return;
    }
    var span = rangeSpan(S.range);
    var html = "";
    detail.engines.forEach(function (e) {
      html += '<div class="use"><span>v' + esc(e.v) + ' 算</span><span class="track">' +
        '<i class="w" style="width:' + clampPct(e.comp, span) + '%"></i></span><span class="pct">' +
        fmtInt(e.comp) + "</span></div>";
      html += '<div class="use"><span>v' + esc(e.v) + ' 通</span><span class="track">' +
        '<i class="m" style="width:' + clampPct(e.comm, span) + '%"></i></span><span class="pct">' +
        fmtInt(e.comm) + "</span></div>";
    });
    setHTML("usepane", html);
  }

  function renderTimePane() {
    var detail = S.detail;
    if (!detail) {
      setHTML("timepane", '<div class="empty">无数据</div>');
      return;
    }
    var time = num(detail.time), lb = num(detail.lb);
    var den = time !== null ? time : (lb !== null ? lb : 1);
    var html = '<div class="use"><span>Time</span><span class="track"><i class="m" style="width:' +
      (time === null ? 0 : clampPct(time, den)) + '%"></i></span><span class="pct">' +
      fmtInt(time) + "</span></div>";
    html += '<div class="use"><span>lb</span><span class="track"><i class="w" style="width:' +
      (lb === null ? 0 : clampPct(lb, den)) + '%"></i></span><span class="pct">' +
      fmtInt(lb) + "</span></div>";
    html += '<div class="wfkey"><span><b style="background:#3fc9dd"></b>Time <em>' +
      fmtInt(time) + "</em></span><span><b style=\"background:#b9c7d7\"></b>lb <em>" +
      fmtInt(lb) + "</em></span></div>";
    html += '<div class="note">Time / lb 都是服务端判定值；本页只做条形缩放。</div>';
    setHTML("timepane", html);
  }

  /* ── 渲染：右栏 ───────────────────────────────────────────────── */
  function renderRunHead() {
    var box = $("runhead");
    if (!box) return;
    var run = S.runId ? runOf(S.runId) : null;
    if (!run) {
      box.innerHTML = '<div class="empty">未选择 run</div>';
      return;
    }
    var version = versionOfRun(S.runId);
    var progress = num(run.done) !== null && num(run.total) !== null ?
      run.done + "/" + run.total : "—";
    var html = '<div class="tok">' + esc(run.run_id) + " " + statePill(run.state) + "</div>";
    html += '<div class="meta">';
    html += '<span class="kv-mini">版本 <b>' + esc(run.version || (version && version.version) || "—") + "</b></span>";
    html += '<span class="kv-mini">commit <b>' + esc(run.commit || (version && version.commit) || "—") + "</b></span>";
    html += '<span class="kv-mini">actor <b>' + esc(run.actor || (version && version.actor) || "—") + "</b></span>";
    html += '<span class="kv-mini">进度 <b>' + esc(progress) + "</b></span>";
    if (version) {
      var headScore = version.score;
      html += '<span class="kv-mini">相对分 <b>' + fmtScore(headScore) + "</b> · 排名 <b>" +
        (num(version.rank) === null ? "—" : "#" + version.rank) + "</b></span>";
    }
    html += "</div>";
    if (run.solver_cmd) html += '<div class="kv-mini" style="margin-top:6px">solver <b>' +
      esc(run.solver_cmd) + "</b></div>";
    if (run.notes) html += '<div class="kv-mini" style="margin-top:3px">notes <b>' +
      esc(run.notes) + "</b></div>";
    if (run.created_at) html += '<div class="kv-mini" style="margin-top:3px">created <b>' +
      esc(run.created_at) + "</b></div>";
    box.innerHTML = html;
  }

  function sortedVersions() {
    var list = S.versions.slice();
    list.sort(function (a, b) {
      var ra = num(a.rank), rb = num(b.rank);
      if (ra === null && rb === null) return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      if (ra === null) return 1;
      if (rb === null) return -1;
      return ra - rb;
    });
    return list;
  }

  function renderVersions() {
    var box = $("versions");
    var tag = $("versions-tag");
    if (!box) return;
    if (!S.versions.length) {
      box.innerHTML = '<div class="empty">账本里还没有版本</div>';
      if (tag) tag.textContent = "0";
      return;
    }
    if (tag) tag.textContent = S.versions.length + " 行";
    var html = '<table class="runs"><thead><tr><th>版本</th><th>相对分</th><th>排名</th>' +
      "<th>来源 run_id · commit · actor</th><th></th></tr></thead><tbody>";
    sortedVersions().forEach(function (v) {
      var cur = v.run_id === S.runId ? ' class="cur"' : "";
      var score = num(v.score);
      var illegal = v.ok === false || score === null;
      var cases = v.cases ? Object.keys(v.cases) : [];
      var chips = cases.map(function (c) {
        var item = v.cases[c];
        var good = item && item.ok;
        var itemTime = item ? item.time : "—";
        var itemBase = item ? item.base : "—";
        return '<span class="casechip ' + (good ? "good" : "bad") + '" title="' +
          esc(c + " · time " + itemTime + " · base " + itemBase) +
          '">' + esc(c) + " " + (item ? fmtInt(itemTime) : "—") + "</span>";
      }).join("");
      html += "<tr" + cur + ' data-run="' + esc(v.run_id) + '">' +
        '<td><span class="tagv">' + esc(v.version) + "</span>" +
        '<div class="src">' + esc(v.commit || "—") + "</div></td>" +
        '<td class="n">' + (illegal ? "<span class=\"badge3 bad\">null</span>" : score.toFixed(3)) + "</td>" +
        '<td class="n">' + (num(v.rank) === null ? "—" : "#" + v.rank) + "</td>" +
        '<td><div class="src">' + esc(v.run_id) + " · " + esc(v.commit || "—") + " · " +
        esc(v.actor || "—") + '</div><div class="casechips">' + chips + "</div></td>" +
        '<td><button class="mini" data-ab="' + esc(v.run_id) + '" title="设为 B">B</button></td></tr>';
    });
    html += "</tbody></table>";
    html += '<div class="srcnote">' + (S.versions.some(function (v) { return v.ok === false; }) ?
      "非法版本也出现在列表里（score:null，排名留空）。" : "") +
      "相对分 / 排名由服务端计算，本页只格式化。</div>";
    box.innerHTML = html;
  }

  function allRuns() {
    var merged = new Map();
    S.runList.forEach(function (r) {
      if (!r || !r.run_id) return;
      var live = S.runs.get(r.run_id) || {};
      var copy = {};
      Object.keys(r).forEach(function (k) { copy[k] = r[k]; });
      Object.keys(live).forEach(function (k) { copy[k] = live[k]; });
      merged.set(r.run_id, copy);
    });
    S.runs.forEach(function (r, id) {
      if (!merged.has(id)) merged.set(id, r);
    });
    return Array.from(merged.values());
  }

  function renderRuns() {
    var box = $("runs");
    var tag = $("runs-tag");
    if (!box) return;
    var list = allRuns();
    if (!list.length) {
      box.innerHTML = '<div class="empty">没有 run 记录</div>';
      if (tag) tag.textContent = "0";
      return;
    }
    list.sort(function (a, b) {
      return String(b.created_at || "").localeCompare(String(a.created_at || ""));
    });
    var active = list.filter(function (r) {
      var merged = S.runs.get(r.run_id) || r;
      var state = merged.state || r.state || "";
      return state === "queued" || state === "running";
    });
    var history = list.filter(function (r) {
      return active.indexOf(r) < 0;
    });
    if (tag) tag.textContent = "活动 " + active.length + " · 历史 " + history.length;
    var html = '<table class="runs"><thead><tr><th>run</th><th>状态</th><th>进度</th>' +
      "<th>版本 / 来源</th></tr></thead><tbody>";
    function row(r) {
      var merged = S.runs.get(r.run_id) || r;
      var cur = r.run_id === S.runId ? ' class="cur"' : "";
      var state = merged.state || r.state || "";
      var progress = num(merged.done) !== null && num(merged.total) !== null ?
        merged.done + "/" + merged.total : "—";
      var version = versionOfRun(r.run_id);
      var vScore = version ? version.score : null;
      var rel = version ? fmtScore(vScore) +
        (num(version.rank) === null ? "" : " · #" + version.rank) : "—";
      return "<tr" + cur + ' data-run="' + esc(r.run_id) + '">' +
        '<td><span class="tagv">' + esc(r.run_id) + '</span><div class="src">' +
        esc(merged.created_at || r.created_at || "") + "</div></td>" +
        "<td>" + statePill(state) + "</td>" +
        '<td class="n">' + esc(progress) + "</td>" +
        '<td><div class="src">' + esc(merged.version || r.version || "—") + " · " +
        esc(merged.commit || r.commit || "—") + "</div>" +
        '<div class="src">' + esc(merged.actor || r.actor || "—") + " · 相对分 " +
        esc(rel) + "</div></td></tr>";
    }
    active.forEach(function (r) { html += row(r); });
    if (history.length) {
      html += '<tr class="divider"><td colspan="4">历史 run · 来自 /api/versions 与 /api/runs/{id}' +
        "</td></tr>";
      history.forEach(function (r) { html += row(r); });
    }
    html += "</tbody></table>";
    html += '<div class="srcnote">活动 run 只算 <b>queued / running</b>（服务端 active_runs / SSE 快照同口径）；' +
      "done / failed / timeout 属于历史。总数请用账本条数（/api/health.ledger_lines），" +
      "不要把活动数当全部 run。</div>";
    box.innerHTML = html;
  }

  function renderTrend() {
    var box = $("trend");
    if (!box) return;
    var points = [];
    S.versions.forEach(function (v) {
      var score = num(v.score);
      if (score === null) return;
      points.push({ v: v, score: score });
    });
    points.sort(function (a, b) {
      return String(a.v.created_at || "").localeCompare(String(b.v.created_at || ""));
    });
    if (points.length < 2) {
      box.innerHTML = '<div class="empty">至少需要两个合法版本才有趋势（当前 ' +
        points.length + " 个；非法版本 score:null 不参与）</div>";
      return;
    }
    var lo = points[0].score, hi = points[0].score;
    points.forEach(function (p) {
      if (p.score < lo) lo = p.score;
      if (p.score > hi) hi = p.score;
    });
    if (lo === hi) { lo = lo - 0.02; hi = hi + 0.02; }
    var pad = (hi - lo) * 0.18;
    lo -= pad; hi += pad;
    var w = 286, h = 96, left = 30, right = 8, top = 10, bottom = 20;
    var plotW = w - left - right, plotH = h - top - bottom;
    var coords = points.map(function (p, i) {
      var x = left + (points.length === 1 ? plotW / 2 : (i * plotW) / (points.length - 1));
      var score = p.score;
      var y = top + ((hi - score) * plotH) / (hi - lo);
      return { x: x, y: y, p: p };
    });
    var line = coords.map(function (c, i) {
      return (i ? "L" : "M") + c.x.toFixed(1) + " " + c.y.toFixed(1);
    }).join(" ");
    var baseY = top + ((hi - 1) * plotH) / (hi - lo);
    var svg = '<svg viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="相对分趋势">';
    svg += '<line x1="' + left + '" y1="' + top + '" x2="' + left + '" y2="' + (h - bottom) +
      '" stroke="#e2e8f0"/>';
    svg += '<line x1="' + left + '" y1="' + (h - bottom) + '" x2="' + (w - right) + '" y2="' +
      (h - bottom) + '" stroke="#e2e8f0"/>';
    if (baseY > top && baseY < h - bottom) {
      svg += '<line x1="' + left + '" y1="' + baseY.toFixed(1) + '" x2="' + (w - right) +
        '" y2="' + baseY.toFixed(1) + '" stroke="#94a3b4" stroke-dasharray="3 3"/>';
      svg += '<text class="axis" x="' + (left + 2) + '" y="' + (baseY - 2).toFixed(1) +
        '">1.000</text>';
    }
    svg += '<path d="' + line + '" fill="none" stroke="#2563eb" stroke-width="1.6"/>';
    coords.forEach(function (c) {
      var illegal = c.p.v.ok === false;
      var score = c.p.score;
      svg += '<circle cx="' + c.x.toFixed(1) + '" cy="' + c.y.toFixed(1) + '" r="3" fill="' +
        (illegal ? "#d92d20" : "#2563eb") + '"><title>' + esc(c.p.v.version) + " · score " +
        score.toFixed(3) + " · rank " + (num(c.p.v.rank) === null ? "—" : c.p.v.rank) +
        "</title></circle>";
    });
    svg += '<text class="axis" x="' + left + '" y="' + (h - 6) + '">' +
      esc(points[0].v.version) + "</text>";
    svg += '<text class="axis" x="' + (w - right) + '" y="' + (h - 6) +
      '" text-anchor="end">' + esc(points[points.length - 1].v.version) + "</text>";
    svg += '<text class="axis" x="' + left + '" y="' + (top + 8) + '">' + hi.toFixed(2) + "</text>";
    svg += '<text class="axis" x="' + left + '" y="' + (h - bottom - 2) + '">' + lo.toFixed(2) + "</text>";
    svg += "</svg>";
    box.innerHTML = '<div class="trendwrap">' + svg +
      '<div class="srcnote">点 = /api/versions 的 score；纵轴只做缩放，本页不计算相对分。</div></div>';
  }

  function renderCompareOptions() {
    var select = $("cmpsel");
    if (!select) return;
    var current = S.ab.runId || select.value || "";
    var options = ['<option value="">— 关闭 —</option>'];
    var seen = {};
    S.versions.forEach(function (v) {
      if (!v.run_id || v.run_id === S.runId || seen[v.run_id]) return;
      seen[v.run_id] = 1;
      var score = v.score;
      options.push('<option value="' + esc(v.run_id) + '">' + esc(v.version) + " · " +
        esc(v.run_id) + " · " + fmtScore(score) + "</option>");
    });
    S.runList.forEach(function (r) {
      if (!r.run_id || r.run_id === S.runId || seen[r.run_id]) return;
      if (r.state !== "done") return;
      seen[r.run_id] = 1;
      options.push('<option value="' + esc(r.run_id) + '">' + esc(r.version || "?") + " · " +
        esc(r.run_id) + "</option>");
    });
    select.innerHTML = options.join("");
    if (seen[current]) select.value = current;
  }

  function renderAB() {
    var tag = $("abtag");
    if (!tag) return;
    if (!S.ab.detail) {
      tag.classList.remove("on");
      tag.textContent = "";
      var scaleWrap = $("cmpscale-wrap");
      if (scaleWrap) scaleWrap.hidden = true;
      return;
    }
    tag.classList.add("on");
    var aTime = S.detail ? fmtInt(S.detail.time) : "—";
    var bTime = fmtInt(S.ab.detail.time);
    tag.innerHTML = "<b>A " + esc(S.runId) + " " + esc(aTime) + "</b>" +
      ' <i class="vs">vs</i> <b>B ' + esc(S.ab.runId) + " " + esc(bTime) + "</b>";
    var wrap = $("cmpscale-wrap");
    if (wrap) wrap.hidden = false;
    var scale = $("cmpscale");
    if (scale) scale.value = S.ab.scale || "abs";
  }

  function renderDiff() {
    var box = $("diffpane");
    var tag = $("diff-tag");
    if (!box) return;
    if (!S.ab.detail) {
      if (S.ab.error) {
        box.innerHTML = '<div class="empty">' + esc(S.ab.error) + "<br>换一个用例或换一个 B run。</div>";
        if (tag) tag.textContent = "不可用";
        return;
      }
      box.innerHTML = '<div class="empty">选择「对比 B」后，从两次 run 的 ops 切片叠加显示。<br>' +
        "版本表最右列的 <b>B</b> 按钮也可直接设为 B。</div>";
      if (tag) tag.textContent = "未开启";
      return;
    }
    var a = S.detail, b = S.ab.detail;
    var va = versionOfRun(S.runId), vb = versionOfRun(S.ab.runId);
    var vaScore = va ? va.score : null;
    var vbScore = vb ? vb.score : null;
    var aTime = num(a.time), bTime = num(b.time);
    var delta = aTime !== null && bTime !== null ? bTime - aTime : null;
    if (tag) tag.textContent = "已开启";
    var html = '<div class="vdiffcard"><div class="abhead">' +
      '<span><b>A</b> ' + esc(S.runId) + "</span><span class=\"vs\">vs</span>" +
      '<span><b>B</b> ' + esc(S.ab.runId) + "</span></div>";
    html += '<div class="row"><span class="k">Time</span><span>' + fmtInt(aTime) + "</span>" +
      '<span class="old">→</span><span class="new ' +
      (delta === null ? "" : delta <= 0 ? "better" : "worse") + '">' + fmtInt(bTime) +
      (delta === null ? "" : " (" + (delta > 0 ? "+" : "") + delta + ")") + "</span></div>";
    html += '<div class="row"><span class="k">相对分</span><span>' +
      (va ? fmtScore(vaScore) : "—") + '</span><span class="old">→</span><span>' +
      (vb ? fmtScore(vbScore) : "—") + "</span></div>";
    html += '<div class="row"><span class="k">排名</span><span>' +
      (va && num(va.rank) !== null ? "#" + va.rank : "—") + '</span><span class="old">→</span><span>' +
      (vb && num(vb.rank) !== null ? "#" + vb.rank : "—") + "</span></div>";
    html += '<div class="row"><span class="k">网格</span><span>' + esc(gridText(a)) +
      '</span><span class="old">→</span><span>' + esc(gridText(b)) + "</span></div>";
    html += '<div class="row"><span class="k">ops</span><span>' + fmtInt(a.ops_total) +
      '</span><span class="old">→</span><span>' + fmtInt(b.ops_total) + "</span></div>";
    html += "</div>";
    if (a.grid && b.grid && (a.grid.V !== b.grid.V || a.grid.P !== b.grid.P)) {
      html += '<div class="srcnote">网格不同：A/B 泳道按卡组号对齐，比较时注意语义差异。</div>';
    }
    html += '<div class="srcnote">Δ 由前端格式化（B−A）；Time / 相对分 / 排名均来自服务端。' +
      "ops 叠加只取当前视口切片。</div>";
    box.innerHTML = html;
  }

  function renderVersionPopover() {
    var pop = $("vpop");
    if (!pop) return;
    var html = '<div class="vh"><b>版本账本</b><span>选一个版本切 run</span>' +
      '<span style="margin-left:auto">' + S.versions.length + " 行</span></div>";
    sortedVersions().forEach(function (v) {
      var cur = v.run_id === S.runId ? " cur" : "";
      var score = num(v.score);
      var illegal = v.ok === false || score === null;
      html += '<button class="vrow' + cur + '" data-run="' + esc(v.run_id) + '">' +
        '<span class="nm">' + esc(v.version) + "</span>" +
        '<span class="src">' + esc(v.run_id) + " · " + esc(v.commit || "—") + " · " +
        esc(v.actor || "—") + "</span>" +
        '<span class="tm">' + (illegal ? "null" : score.toFixed(3)) + "</span>" +
        '<span class="dl ' + (illegal ? "bad" : "good") + '">' +
        (num(v.rank) === null ? "无排名" : "#" + v.rank) + "</span></button>";
    });
    pop.innerHTML = html;
  }

  function renderAll() {
    renderStatus();
    renderCaseTabs();
    renderVerdict();
    renderChecks();
    renderMemory();
    renderEngines();
    renderGridinfo();
    renderErrors();
    renderGantt();
    renderOps();
    renderTrunc();
    renderUsePane();
    renderTimePane();
    renderRunHead();
    renderVersions();
    renderRuns();
    renderTrend();
    renderCompareOptions();
    renderAB();
    renderDiff();
    renderVersionPopover();
  }

  /* ── 视口切片 ─────────────────────────────────────────────────── */
  function currentWindow() {
    var metrics = trackMetrics();
    var wrap = $("ganttwrap");
    var left = wrap ? wrap.scrollLeft : 0;
    var visible = wrap && wrap.clientWidth ? wrap.clientWidth : metrics.total;
    var span = rangeSpan(S.range);
    var pad = visible * 0.4;
    var t0 = S.range.t0 + ((left - 56 - pad) * span) / metrics.lane;
    var t1 = S.range.t0 + ((left - 56 + visible + pad) * span) / metrics.lane;
    if (t0 < S.range.t0) t0 = S.range.t0;
    if (t1 > S.range.t1) t1 = S.range.t1;
    if (t1 <= t0) t1 = t0 + 1;
    return { since: t0 < 0 ? 0 : t0 | 0, until: (t1 | 0) + 1 };
  }

  function scheduleViewport() {
    if (S.viewTimer) clearTimeout(S.viewTimer);
    S.viewTimer = setTimeout(function () {
      S.viewTimer = null;
      reloadOpsForViewport();
    }, 180);
  }

  async function reloadOpsForViewport() {
    if (!S.detail || !S.ops) return;
    if (S.ops.total <= S.ops.returned) return;
    var win = currentWindow();
    if (S.window && win.since === S.window.since && win.until === S.window.until) return;
    try {
      await loadOps(win);
      renderGantt();
      renderOps();
      if (S.ab.runId) {
        var bWin = win;
        var ops = await api("/api/runs/" + encodeURIComponent(S.ab.runId) + "/cases/" +
          encodeURIComponent(S.caseName) + "/ops", {
          limit: 4000, since: bWin.since, until: bWin.until
        });
        S.ab.ops = Array.isArray(ops.ops) ? ops.ops : [];
        renderGantt();
        renderDiff();
      }
    } catch (err) {
      setFooter("ops 切片失败：" + describeError(err));
    }
  }

  function locateTime(t) {
    var wrap = $("ganttwrap");
    if (!wrap) return;
    var metrics = trackMetrics();
    var x = xFor(t, S.range, metrics.lane);
    var left = x - wrap.clientWidth / 2;
    wrap.scrollLeft = left < 0 ? 0 : left;
    scheduleViewport();
    setFooter("定位到 t=" + t);
  }

  /* ── 选中 op ──────────────────────────────────────────────────── */
  function selectOp(attrs) {
    S.sel = {
      t: Number(attrs.t), mb: Number(attrs.mb), l: Number(attrs.l),
      op: attrs.op, g: Number(attrs.g)
    };
    renderGantt();
    renderOps();
    var pickedT = attrs.t;
    setFooter("选中 " + attrs.mb + ":" + attrs.l + ":" + attrs.op + " · t=" + pickedT +
      " · 数据来自服务端 ops");
  }

  /* ── 编辑器（预览走服务端） ───────────────────────────────────── */
  function openSheet() {
    if (!S.detail) { setFooter("没有可编辑的用例数据"); return; }
    fillEditorFromDetail();
    loadCommittedOutput();
    showSheetTab("grid");
    $("mask").classList.add("on");
    $("sheet").classList.add("on");
    setText("sheet-sub", S.runId + " · " + S.caseName + " · 预览由 POST /api/evaluate 判定");
    setText("pv-time", "—");
    setText("pv-committed", fmtInt(S.detail.time));
    setText("pv-status", "未预览");
    var status = $("pv-status");
    if (status) status.className = "pvstatus";
    setText("pv-hint", "预览值来自 POST /api/evaluate；正式值来自账本，永不覆盖。");
  }

  function closeSheet() {
    $("mask").classList.remove("on");
    $("sheet").classList.remove("on");
  }

  function showSheetTab(tab) {
    var buttons = $("sheet-tabs") ? $("sheet-tabs").querySelectorAll("button") : [];
    Array.prototype.forEach.call(buttons, function (btn) {
      btn.setAttribute("aria-selected", btn.getAttribute("data-tab") === tab ? "true" : "false");
    });
    var grid = $("ws-grid"), text = $("ws-text");
    if (grid) grid.hidden = tab !== "grid";
    if (text) text.hidden = tab !== "text";
  }

  function fillEditorFromDetail() {
    var detail = S.detail;
    if (!detail) return;
    var grid = detail.grid || {};
    $("f-V").value = grid.V === undefined ? "" : grid.V;
    $("f-P").value = grid.P === undefined ? "" : grid.P;
    $("f-K").value = detail.K === undefined || detail.K === null ? "" : detail.K;
    $("f-psi").value = Array.isArray(detail.psi) ? detail.psi.join(" ") : "";
  }

  async function loadCommittedOutput() {
    var text = $("ed-text");
    if (!text) return;
    setText("ed-hint", "正在从服务端取已提交输出 …");
    try {
      var data = await api("/api/runs/" + encodeURIComponent(S.runId) + "/cases/" +
        encodeURIComponent(S.caseName) + "/output");
      text.value = data && typeof data.text === "string" ? data.text : "";
      setText("ed-hint", "已载入服务端原文（" + (text.value ? text.value.split("\n").length : 0) +
        " 行）。改动只影响预览，不会写账本。");
    } catch (err) {
      text.value = "";
      setText("ed-hint", "服务未保留输出原文（" + describeError(err) +
        "）。可以粘贴 cases/" + S.caseName + ".out 的全文后再预览。");
    }
  }

  function applyGridToText() {
    var box = $("ed-text");
    if (!box) return;
    var lines = box.value.split("\n");
    if (lines.length < 3) {
      setText("ed-hint", "原文至少要三行：V P / PSI / 切点。");
      return;
    }
    var v = $("f-V").value.trim();
    var p = $("f-P").value.trim();
    lines[0] = [v, p].join(" ");  // 2026-10 版：只有 V P
    lines[1] = "PSI";
    var k = $("f-K").value.trim();
    var psi = $("f-psi").value.trim();
    lines[2] = (k + (psi ? " " + psi : "")).trim();
    box.value = lines.join("\n");
    setText("ed-hint", "网格与切点已写回原文（第 1–3 行：V P / PSI / K ψ…）。");
  }

  function previewDraft() {
    var box = $("ed-text");
    if (!box || !box.value.trim()) {
      setText("pv-status", "原文为空");
      $("pv-status").className = "pvstatus bad";
      return;
    }
    setText("pv-status", "预览中…");
    $("pv-status").className = "pvstatus";
    setText("pv-time", "—");
    apiPost("/api/evaluate", { case: S.caseName, output: box.value }).then(function (res) {
      S.preview = res;
      var ok = !!res.ok;
      setText("pv-time", num(res.time) === null ? "—" : fmtInt(res.time));
      setText("pv-committed", fmtInt(S.detail ? S.detail.time : null));
      var status = $("pv-status");
      status.className = "pvstatus " + (ok ? "ok" : "bad");
      status.textContent = ok ? "合法（未提交）" : "非法 · " + ((res.errors || []).length) + " 条";
      var committed = num(S.detail ? S.detail.time : null);
      var preview = num(res.time);
      var hint = "预览 · 本地试算 · 未提交：由服务端 POST /api/evaluate 判定；" +
        "已提交值来自账本。二者不同时都已显示，绝不把预览当正式值。";
      if (preview !== null && committed !== null && preview !== committed) {
        hint = "预览 " + preview + " / 已提交 " + committed + " —— 预览不会写入账本。" + hint;
        var chip = $("draftchip");
        if (chip) {
          chip.classList.add("on");
          chip.textContent = "预览·未提交 " + preview + " ≠ 已提交 " + committed;
        }
      }
      if (!ok && res.errors && res.errors.length) {
        hint = "预览非法：" + res.errors[0].category + " · " + res.errors[0].message;
      }
      setText("pv-hint", hint);
      setText("ed-hint", ok ? "预览合法；如需固化请用 CLI 提交新 run（视图只读）。" :
        "预览非法；错误来自服务端，可在下方错误面板定位。");
    }).catch(function (err) {
      setText("pv-status", "预览失败");
      $("pv-status").className = "pvstatus bad";
      setText("pv-time", "—");
      setText("pv-hint", "预览失败：" + describeError(err) + "（不会回退本地计算）");
    });
  }

  /* ── 事件绑定 ─────────────────────────────────────────────────── */
  function bindStatic() {
    var retry = $("es-retry");
    if (retry) retry.addEventListener("click", function () {
      var input = $("es-base");
      var value = input && input.value ? input.value : S.base;
      S.base = normalizeBase(value);
      saveBase(S.base);
      boot();
    });

    var demo = $("es-demo");
    if (demo) demo.addEventListener("click", function () {
      var url = location.pathname + "?demo=1";
      location.href = url;
    });

    var baseBtn = $("btn-base");
    if (baseBtn) baseBtn.addEventListener("click", function () {
      var box = $("emptystate");
      if (box) box.hidden = false;
      setText("es-title", "服务地址");
      var input = $("es-base");
      if (input) input.value = S.base;
      setText("es-detail", "当前连接：" + S.base + (S.connected ? "（已连接）" : "（未连接）"));
    });

    var refresh = $("btn-refresh");
    if (refresh) refresh.addEventListener("click", function () { softRefresh(); });

    var versionsBtn = $("btn-versions");
    if (versionsBtn) versionsBtn.addEventListener("click", function (ev) {
      var pop = $("vpop");
      if (!pop) return;
      var on = pop.classList.toggle("on");
      if (on) {
        var rect = versionsBtn.getBoundingClientRect();
        pop.style.left = (rect.left - 120) + "px";
        pop.style.top = (rect.bottom + 6) + "px";
      }
      ev.stopPropagation();
    });

    var edit = $("btn-edit");
    if (edit) edit.addEventListener("click", openSheet);
    var close = $("sheet-close");
    if (close) close.addEventListener("click", closeSheet);
    var cancel = $("mask");
    if (cancel) cancel.addEventListener("click", closeSheet);

    var tabs = $("sheet-tabs");
    if (tabs) tabs.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button[data-tab]");
      if (btn) showSheetTab(btn.getAttribute("data-tab"));
    });

    var applyGrid = $("ed-applygrid");
    if (applyGrid) applyGrid.addEventListener("click", applyGridToText);
    var fromDetail = $("ed-fromdetail");
    if (fromDetail) fromDetail.addEventListener("click", fillEditorFromDetail);
    var load = $("ed-load");
    if (load) load.addEventListener("click", loadCommittedOutput);
    var reset = $("ed-reset");
    if (reset) reset.addEventListener("click", function () {
      fillEditorFromDetail();
      loadCommittedOutput();
      setText("pv-time", "—");
      setText("pv-committed", fmtInt(S.detail ? S.detail.time : null));
      setText("pv-status", "未预览");
      var chip = $("draftchip");
      if (chip) { chip.classList.remove("on"); chip.textContent = ""; }
    });
    var preview = $("ed-preview");
    if (preview) preview.addEventListener("click", previewDraft);

    var casebar = $("casebar");
    if (casebar) casebar.addEventListener("click", function (ev) {
      var tab = ev.target.closest("[data-case]");
      if (tab) selectCase(tab.getAttribute("data-case"));
    });

    var versionsBox = $("versions");
    if (versionsBox) versionsBox.addEventListener("click", function (ev) {
      var ab = ev.target.closest("[data-ab]");
      if (ab) {
        ev.stopPropagation();
        setCompare(ab.getAttribute("data-ab"));
        return;
      }
      var row = ev.target.closest("tr[data-run]");
      if (row) selectRun(row.getAttribute("data-run"), S.caseName);
    });

    var runsBox = $("runs");
    if (runsBox) runsBox.addEventListener("click", function (ev) {
      var row = ev.target.closest("tr[data-run]");
      if (row) selectRun(row.getAttribute("data-run"), "");
    });

    var pop = $("vpop");
    if (pop) pop.addEventListener("click", function (ev) {
      var row = ev.target.closest("[data-run]");
      if (row) {
        pop.classList.remove("on");
        selectRun(row.getAttribute("data-run"), "");
      }
    });

    var select = $("cmpsel");
    if (select) select.addEventListener("change", function () {
      setCompare(select.value);
    });
    var scale = $("cmpscale");
    if (scale) scale.addEventListener("change", function () {
      S.ab.scale = scale.value;
      renderGantt();
    });

    var zoom = $("zoom");
    if (zoom) zoom.addEventListener("input", function () {
      S.zoom = Number(zoom.value) / 100;
      setText("zoomv", S.zoom.toFixed(1) + "×");
      renderGantt();
      scheduleViewport();
    });

    var ganttWrap = $("ganttwrap");
    if (ganttWrap) ganttWrap.addEventListener("scroll", scheduleViewport);
    window.addEventListener("resize", function () { renderGantt(); });

    var truncBox = $("gtrunc");
    if (truncBox) truncBox.addEventListener("click", function (ev) {
      if (ev.target.closest("#gtrunc-more")) loadMoreOps();
    });

    var gantt = $("gantt");
    if (gantt) gantt.addEventListener("click", function (ev) {
      var el = ev.target.closest(".op, .zm, .span");
      if (!el) return;
      if (el.classList.contains("span")) {
        var start = Number(el.getAttribute("data-start") || 0);
        locateTime(start);
        return;
      }
      selectOp(el.dataset);
    });

    var opl = $("oplbody");
    if (opl) opl.addEventListener("click", function (ev) {
      var row = ev.target.closest("tr[data-t]");
      if (row) selectOp(row.dataset);
    });

    var ftabs = $("ftabs");
    if (ftabs) ftabs.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-fgroup]");
      if (!btn) return;
      S.filters[btn.getAttribute("data-fgroup")] = btn.getAttribute("data-fvalue");
      renderGantt();
      renderOps();
    });

    var errors = $("errors");
    if (errors) errors.addEventListener("click", function (ev) {
      var item = ev.target.closest(".err[data-t]");
      if (!item) return;
      var t = item.getAttribute("data-t");
      if (t !== "") locateTime(Number(t));
    });

    var draft = $("draftchip");
    if (draft) draft.addEventListener("click", openSheet);

    document.addEventListener("click", function (ev) {
      var popEl = $("vpop");
      if (popEl && popEl.classList.contains("on") && !ev.target.closest("#vpop") &&
        !ev.target.closest("#btn-versions")) {
        popEl.classList.remove("on");
      }
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        closeSheet();
        var popEl = $("vpop");
        if (popEl) popEl.classList.remove("on");
      }
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
        if ($("sheet").classList.contains("on")) previewDraft();
        else openSheet();
      }
    });

    bindTips();
  }

  function setCompare(runId) {
    S.ab.runId = runId || "";
    var select = $("cmpsel");
    if (select) select.value = S.ab.runId;
    if (!S.ab.runId) {
      S.ab = { runId: "", detail: null, ops: null, scale: S.ab.scale || "abs" };
      renderAB();
      renderGantt();
      renderDiff();
      return Promise.resolve();
    }
    return loadCompare(S.ab.runId).then(function () {
      renderAB();
      renderGantt();
      renderDiff();
      if (S.ab.detail) setFooter("A/B：A " + S.runId + " vs B " + S.ab.runId);
    });
  }

  /* ── 悬浮提示 ─────────────────────────────────────────────────── */
  function showTip(text, x, y) {
    var tip = $("tip");
    if (!tip) return;
    tip.textContent = text;
    tip.style.opacity = "1";
    var left = x + 14;
    var top = y + 14;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function hideTip() {
    var tip = $("tip");
    if (tip) tip.style.opacity = "0";
  }
  function bindTips() {
    document.addEventListener("mouseover", function (ev) {
      var el = ev.target.closest ? ev.target.closest("[data-tip],[title]") : null;
      if (!el) { hideTip(); return; }
      var text = el.getAttribute("data-tip");
      if (!text) {
        var title = el.getAttribute("title");
        if (!title) { hideTip(); return; }
        text = title;
      }
      showTip(text, ev.clientX, ev.clientY);
    });
    document.addEventListener("mousemove", function (ev) {
      var tip = $("tip");
      if (!tip || tip.style.opacity !== "1") return;
      tip.style.left = (ev.clientX + 14) + "px";
      tip.style.top = (ev.clientY + 14) + "px";
    });
    document.addEventListener("mouseout", function (ev) {
      if (!ev.relatedTarget) hideTip();
    });
  }

  /* ── 启动 ─────────────────────────────────────────────────────── */
  async function boot() {
    S.mode = DEMO ? "demo" : "live";
    renderMode();
    setSSE("connecting");
    setFooter("连接 " + S.base + " …");
    try {
      if (S.mode === "demo") {
        await loadScript("fixtures.js");
        fixtures();
      }
      await refreshData();
      connected();
      if (new URLSearchParams(location.search).get("sse") === "0") setSSE("off");
      else connectEvents();
      await ensureSelection();
      await applyDeepLinks();
    } catch (err) {
      disconnected(err);
    }
  }

  async function applyDeepLinks() {
    var params = new URLSearchParams(location.search);
    var wantedRun = params.get("run");
    if (wantedRun && wantedRun !== S.runId) {
      S.caseName = "";
      await selectRun(wantedRun, "");
    }
    var wantedCase = params.get("case");
    if (wantedCase && wantedCase !== S.caseName) await selectCase(wantedCase);
    var wantedB = params.get("ab");
    if (wantedB && wantedB !== S.runId) await setCompare(wantedB);
    if (params.get("sheet") === "1" && S.detail) {
      openSheet();
      await loadCommittedOutput();
      if (params.get("tab")) showSheetTab(params.get("tab"));
      if (params.get("preview") === "1") previewDraft();
    }
  }

  function init() {
    S.base = loadBase();
    var wantedBase = new URLSearchParams(location.search).get("base");
    if (wantedBase) {
      S.base = normalizeBase(wantedBase);
      saveBase(S.base);
    }
    renderMode();
    renderStatus();
    bindStatic();
    var input = $("es-base");
    if (input) input.value = S.base;
    var zoom = $("zoom");
    if (zoom) setText("zoomv", (Number(zoom.value) / 100).toFixed(1) + "×");
    boot();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
