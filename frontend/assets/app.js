const PAGE_TITLES = {
  overview: "系统总览",
  data: "数据",
  sync: "数据同步",
  strategy: "策略",
  orders: "交易",
  review: "复盘",
  settings: "设置",
};

async function requestJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch (_err) {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return response.json();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function formatDateTime(value, withSeconds = true) {
  if (value == null || value === "") {
    return "-";
  }
  let text = String(value).trim();
  if (!text) {
    return "-";
  }
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(text)) {
    text = `${text.replace(" ", "T")}Z`;
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  }).formatToParts(date);
  const pick = (type) => parts.find((part) => part.type === type)?.value || "";
  const clock = withSeconds
    ? `${pick("hour")}:${pick("minute")}:${pick("second")}`
    : `${pick("hour")}:${pick("minute")}`;
  return `${pick("year")}-${pick("month")}-${pick("day")} ${clock}`;
}

function currentPage() {
  const hash = (location.hash || "#overview").replace("#", "");
  return PAGE_TITLES[hash] ? hash : "overview";
}

function setTone(id, count) {
  const el = document.getElementById(id);
  if (!el) {
    return;
  }
  const n = Number(count) || 0;
  el.dataset.tone = n > 0 ? "block" : "ok";
}

const SYNC_STATUS_LABEL = {
  queued: "排队",
  running: "进行中",
  success: "成功",
  skipped: "已是最新",
  quality_failed: "质检未通过",
  failed: "失败",
  blocked: "质检未通过",
};
const STRATEGY_STATUS_LABEL = {
  draft: "草稿",
  backtest: "回测中",
  candidate: "候选",
  failed: "失败",
  paper: "模拟",
  paused: "暂停",
  retired: "退役",
  archived: "归档",
};
const ORDER_STATUS_LABEL = {
  risk_pending: "待风控",
  submit_pending: "待提交",
  submitted: "已提交",
  partial_filled: "部分成交",
  filled: "全部成交",
  cancelled: "已撤单",
  rejected: "已拒绝",
  error: "异常",
};

function makeTag(label, tone) {
  const span = document.createElement("span");
  span.className = "tag";
  if (tone) {
    span.dataset.tone = tone;
  }
  span.textContent = label;
  return span;
}

function appendCell(tr, value, options = {}) {
  const td = document.createElement("td");
  if (options.className) {
    td.className = options.className;
  }
  if (options.title) {
    td.title = options.title;
  }
  if (options.tone) {
    const tag = makeTag(value, options.tone);
    if (options.title) {
      tag.title = options.title;
    }
    td.appendChild(tag);
  } else {
    td.textContent = value;
  }
  tr.appendChild(td);
  return td;
}

function toneForSync(status) {
  if (status === "success") {
    return "ok";
  }
  if (status === "skipped") {
    return "accent";
  }
  if (status === "quality_failed" || status === "failed" || status === "blocked") {
    return "block";
  }
  if (status === "running" || status === "queued") {
    return "info";
  }
  return "muted";
}

function toneForStrategy(status) {
  if (status === "paper") {
    return "ok";
  }
  if (status === "candidate") {
    return "accent";
  }
  if (status === "failed") {
    return "block";
  }
  if (status === "backtest") {
    return "info";
  }
  if (status === "paused") {
    return "warn";
  }
  return "muted";
}

function toneForOrder(status) {
  if (status === "filled") {
    return "ok";
  }
  if (status === "rejected" || status === "error") {
    return "block";
  }
  if (status === "cancelled") {
    return "muted";
  }
  if (status === "partial_filled") {
    return "accent";
  }
  return "warn";
}

function renderMarket(payload) {
  const body = document.getElementById("market-body");
  body.innerHTML = "";
  const records = payload.items || [];
  document.querySelectorAll('.sort-btn[data-sort-scope="market"]').forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.sort === marketState.sort);
  });
  if (!records.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 13;
    td.className = "table-empty";
    const wrap = document.createElement("div");
    wrap.className = "empty-action";
    const note = document.createElement("span");
    note.textContent = "当前筛选没有行情。";
    const action = document.createElement("button");
    action.type = "button";
    action.className = "secondary";
    action.id = "bootstrap-empty";
    action.textContent = "初始化演示数据";
    wrap.append(note, action);
    td.appendChild(wrap);
    tr.appendChild(td);
    body.appendChild(tr);
    action.addEventListener("click", runBootstrap);
    return;
  }
  records.forEach((row, index) => {
    const tr = document.createElement("tr");
    const cells = [
      ["num", String(index + 1)],
      ["", row.trade_date],
      ["", row.code],
      ["", row.exchange],
      ["", row.name || "-"],
      ["num", row.open],
      ["num", row.high],
      ["num", row.low],
      ["num", row.close],
      ["num", formatVolume(row.volume)],
      [chgClass(row.volume_dod_dir), formatChg(row.volume_dod, row.volume_dod_dir)],
      [chgClass(row.volume_yoy_dir), formatChg(row.volume_yoy, row.volume_yoy_dir)],
      ["", row.source],
    ];
    for (const [cls, value] of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      if (cls) {
        td.className = cls;
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  });
}

function formatVolume(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "-";
  }
  if (Math.abs(n) >= 1e8) {
    return `${(n / 1e8).toFixed(2)}亿`;
  }
  if (Math.abs(n) >= 1e4) {
    return `${(n / 1e4).toFixed(0)}万`;
  }
  return String(n);
}

function chgClass(dir) {
  if (dir === "up") {
    return "num chg-up";
  }
  if (dir === "down") {
    return "num chg-down";
  }
  return "num chg-na";
}

function formatChg(ratio, dir) {
  if (dir === "na" || ratio == null || !Number.isFinite(Number(ratio))) {
    return "—";
  }
  const n = Number(ratio) * 100;
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "–";
  const sign = n > 0 ? "+" : "";
  return `${arrow}${sign}${n.toFixed(1)}%`;
}

const marketState = { sort: "volume", order: "desc" };

function marketQuery() {
  const params = new URLSearchParams({
    limit: "50",
    sort: marketState.sort,
    order: marketState.order,
  });
  const date = document.getElementById("market-date").value;
  const exchange = document.getElementById("market-exchange").value;
  const type = document.getElementById("market-type").value;
  const code = document.getElementById("market-code").value.trim();
  if (date) {
    params.set("trade_date", date);
  }
  if (exchange) {
    params.set("exchange", exchange);
  }
  if (type) {
    params.set("instrument_type", type);
  }
  if (code) {
    params.set("code", code);
  }
  return params;
}

function syncMarketFilters(payload) {
  const dateInput = document.getElementById("market-date");
  if (payload.min_trade_date) {
    dateInput.min = payload.min_trade_date;
  }
  if (payload.max_trade_date) {
    dateInput.max = payload.max_trade_date;
  }
  const current = dateInput.value;
  const outOfRange =
    (payload.min_trade_date && current && current < payload.min_trade_date) ||
    (payload.max_trade_date && current && current > payload.max_trade_date);
  if (!current || outOfRange) {
    if (payload.trade_date) {
      dateInput.value = payload.trade_date;
    } else if (payload.max_trade_date) {
      dateInput.value = payload.max_trade_date;
    }
  }
}

async function loadMarketSnapshot() {
  let payload = await requestJson(`/api/market/snapshot?${marketQuery().toString()}`);
  const requested = document.getElementById("market-date").value;
  if (
    (payload.returned || 0) === 0 &&
    payload.max_trade_date &&
    requested &&
    requested !== payload.max_trade_date
  ) {
    document.getElementById("market-date").value = payload.max_trade_date;
    payload = await requestJson(`/api/market/snapshot?${marketQuery().toString()}`);
  }
  syncMarketFilters(payload);
  const shown = payload.returned || 0;
  const matched = payload.matched || 0;
  const sortLabel = { volume: "成交量", dod: "环比", yoy: "同比" }[payload.sort || marketState.sort] || "成交量";
  const orderLabel = (payload.order || marketState.order) === "asc" ? "低→高" : "高→低";
  setText(
    "market-file",
    payload.trade_date
      ? `${payload.trade_date} · Top${payload.limit || 50} · ${sortLabel}${orderLabel} · ${shown}/${matched}`
      : "无行情文件",
  );
  renderMarket(payload);
}

function renderTasks(tasks) {
  const list = document.getElementById("task-list");
  list.innerHTML = "";
  if (!tasks.length) {
    const li = document.createElement("li");
    li.textContent = "暂无任务记录";
    list.appendChild(li);
    return;
  }
  for (const task of tasks) {
    const li = document.createElement("li");
    const left = document.createElement("span");
    const status = task.status || "";
    left.textContent = `${task.task_name} ${formatDateTime(task.started_at)}`;
    const tag = makeTag(SYNC_STATUS_LABEL[status] || status || "-", toneForSync(status));
    if (task.message) {
      tag.title = task.message;
    }
    li.append(left, tag);
    list.appendChild(li);
  }
}

function renderKv(containerId, entries) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = "";
  for (const [label, value] of entries) {
    const item = document.createElement("div");
    item.className = "kv-item";
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = value;
    item.append(k, v);
    grid.appendChild(item);
  }
}

const SOURCE_AUTH_LABEL = { ok: "正常", ready: "就绪", local: "本地" };
const SOURCE_HEALTH_LABEL = { healthy: "正常", ok: "正常", down: "异常", unknown: "未知" };

function renderSources(sources) {
  const body = document.getElementById("source-body");
  body.innerHTML = "";
  if (!sources.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.textContent = "暂无数据源。请先初始化演示数据。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of sources) {
    const tr = document.createElement("tr");
    const auth = row.auth_status || "-";
    const health = row.health_status || "-";
    appendCell(tr, row.source_id ?? "-");
    appendCell(tr, row.name ?? "-");
    appendCell(tr, SOURCE_AUTH_LABEL[auth] || auth, { tone: auth === "ok" || auth === "ready" ? "ok" : "muted" });
    appendCell(tr, row.quota ?? "-");
    appendCell(tr, row.cost ?? "-");
    appendCell(tr, row.owner ?? "-");
    appendCell(tr, SOURCE_HEALTH_LABEL[health] || health, {
      tone: health === "ok" || health === "healthy" ? "ok" : health === "down" ? "block" : "muted",
    });
    body.appendChild(tr);
  }
}

function renderPorts(ports) {
  const list = document.getElementById("port-list");
  list.innerHTML = "";
  for (const port of ports) {
    const li = document.createElement("li");
    const left = document.createElement("span");
    const right = document.createElement("span");
    left.textContent = port.name;
    const tag = makeTag(port.status === "wired" ? "已接入" : "未接入", port.status === "wired" ? "ok" : "muted");
    li.append(left, tag);
    list.appendChild(li);
  }
}

const QUALITY_PAGE_SIZE = 20;
const qualityState = {
  page: 1,
  status: "open",
  severity: "",
  sort: "created_at",
  order: "desc",
  pages: 1,
  seq: 0,
  expandedId: "",
};

const QUALITY_SEVERITY_LABEL = { block: "阻断", warn: "警告", info: "提示" };
const QUALITY_STATUS_LABEL = { open: "未关闭", closed: "已关闭" };
const QUALITY_CHECK_LABEL = {
  missing: "缺失",
  range: "越界",
  adj_conflict: "复权冲突",
  point_in_time: "时点错误",
  cross_source: "跨源不一致",
};
const QUALITY_SORT_LABEL = {
  created_at: "时间",
  symbol: "代码",
  exchange: "市场",
  trade_date: "日期",
  check_type: "检查",
  severity: "级别",
  status: "状态",
};

function truncate(value, max) {
  const text = value == null || value === "" ? "-" : String(value);
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function qualityQuery() {
  const params = new URLSearchParams({
    page: String(qualityState.page),
    page_size: String(QUALITY_PAGE_SIZE),
    status: qualityState.status,
    sort: qualityState.sort,
    order: qualityState.order,
  });
  const date = document.getElementById("quality-date").value;
  const severity = document.getElementById("quality-severity").value;
  const code = document.getElementById("quality-code").value.trim();
  qualityState.severity = severity;
  if (date) {
    params.set("trade_date", date);
  }
  if (severity) {
    params.set("severity", severity);
  }
  if (code) {
    params.set("code", code);
  }
  return params;
}

function renderQualityIssues(payload) {
  const body = document.getElementById("quality-body");
  body.innerHTML = "";
  document.querySelectorAll('.sort-btn[data-sort-scope="quality"]').forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.sort === qualityState.sort);
  });
  const items = payload.items || [];
  if (!items.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.className = "table-empty";
    td.textContent = "当前筛选下没有质量问题。";
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    const startNo = ((Number(payload.page) || 1) - 1) * (Number(payload.page_size) || QUALITY_PAGE_SIZE);
    items.forEach((row, index) => {
      const tr = document.createElement("tr");
      const issueId = row.issue_id || `${row.symbol}-${row.trade_date}-${index}`;
      const open = qualityState.expandedId === issueId;
      tr.className = open ? "quality-row is-open" : "quality-row";
      tr.dataset.issueId = issueId;
      appendCell(tr, String(startNo + index + 1), { className: "num" });
      appendCell(tr, row.created_at || "-");
      appendCell(tr, row.code || row.symbol || "-");
      appendCell(tr, row.exchange || "-");
      appendCell(tr, row.trade_date || "-");
      appendCell(tr, QUALITY_CHECK_LABEL[row.check_type] || row.check_type || "-");
      appendCell(tr, QUALITY_SEVERITY_LABEL[row.severity] || row.severity || "-", {
        tone: row.severity === "block" ? "block" : row.severity === "warn" ? "warn" : "info",
      });
      appendCell(tr, QUALITY_STATUS_LABEL[row.status] || row.status || "-", {
        tone: row.status === "open" ? "warn" : "muted",
      });
      const diffText = row.diff_label || row.diff || "-";
      appendCell(tr, diffText, { className: "cell-clip", title: diffText });
      const actionTd = document.createElement("td");
      if (row.status === "open" && row.issue_id) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "secondary";
        btn.dataset.closeIssue = row.issue_id;
        btn.textContent = "关闭";
        actionTd.appendChild(btn);
      } else {
        actionTd.textContent = "-";
      }
      tr.appendChild(actionTd);
      body.appendChild(tr);
      const detail = document.createElement("tr");
      detail.className = "quality-detail";
      detail.hidden = !open;
      const detailTd = document.createElement("td");
      detailTd.colSpan = 10;
      detailTd.textContent = diffText;
      detail.appendChild(detailTd);
      body.appendChild(detail);
    });
  }
  const total = Number(payload.total) || 0;
  const page = Number(payload.page) || 1;
  const pages = Number(payload.pages) || 1;
  const size = Number(payload.page_size) || QUALITY_PAGE_SIZE;
  qualityState.page = page;
  qualityState.pages = pages;
  const sortLabel = QUALITY_SORT_LABEL[payload.sort || qualityState.sort] || "时间";
  const orderLabel = (payload.order || qualityState.order) === "asc" ? "低→高" : "高→低";
  setText(
    "quality-page-meta",
    total ? `共 ${total} 条（当前筛选）· 第 ${page}/${pages} 页 · ${sortLabel}${orderLabel}` : "共 0 条",
  );
  setText("quality-page-label", `共 ${total} 条 · ${page} / ${pages} · 每页 ${size}`);
  const prev = document.getElementById("quality-prev");
  const next = document.getElementById("quality-next");
  prev.disabled = page <= 1;
  next.disabled = page >= pages || total === 0;
}

async function loadQualityIssues() {
  const seq = ++qualityState.seq;
  const prev = document.getElementById("quality-prev");
  const next = document.getElementById("quality-next");
  prev.disabled = true;
  next.disabled = true;
  const payload = await requestJson(`/api/quality/issues?${qualityQuery().toString()}`);
  if (seq !== qualityState.seq) {
    return;
  }
  renderQualityIssues(payload);
}

function showPage(page) {
  document.querySelectorAll(".page").forEach((section) => {
    section.classList.toggle("hidden", section.id !== `page-${page}`);
  });
  document.querySelectorAll("#nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === page);
  });
  setText("page-title", PAGE_TITLES[page]);
  if (page === "data") {
    loadQualityIssues().catch((error) => {
      setText("quality-page-meta", `加载失败：${error.message}`);
    });
  }
  if (page === "sync") {
    loadSyncRuns().catch((error) => {
      setText("sync-page-meta", `加载失败：${error.message}`);
    });
  }
  if (page === "orders") {
    loadOrders().catch((error) => {
      setText("order-result", `加载失败：${error.message}`);
    });
  }
  if (page === "strategy") {
    loadStrategyPage().catch((error) => {
      setText("strategy-run-result", `加载失败：${error.message}`);
      const hint = document.getElementById("strategy-run-result");
      if (hint) {
        hint.hidden = false;
      }
    });
  }
  if (page === "review") {
    loadReviewPage().catch((error) => {
      setText("review-hint", `加载失败：${error.message}`);
    });
  }
}

async function refresh() {
  const [health, status, sources, ports] = await Promise.all([
    requestJson("/api/health"),
    requestJson("/api/status"),
    requestJson("/api/data-sources"),
    requestJson("/api/ports"),
  ]);
  await loadMarketSnapshot();

  setText("runtime", health.status === "ok" ? "运行正常 · 模拟交易未开" : "运行异常");
  setText("source-count", status.data_sources);
  setText("instrument-count", status.instruments);
  setText("quality-count", status.open_quality_blocks ?? status.open_quality_issues);
  setText("alert-count", status.open_alerts);
  setTone("metric-quality", status.open_quality_blocks ?? status.open_quality_issues);
  setTone("metric-alerts", status.open_alerts);
  const blocks = Number(status.open_quality_blocks);
  const warns = Number(status.open_quality_warns);
  let qualityHint = "当前无开放质量问题";
  if (blocks > 0) {
    qualityHint = `开放阻断 ${blocks} 条，研究/交易应停在质量门`;
    if (warns > 0) {
      qualityHint += `；另有警告 ${warns} 条`;
    }
  } else if (warns > 0) {
    qualityHint = `无阻断；${warns} 条警告（跨源因子），不拦研究/交易`;
  }
  setText("quality-hint", qualityHint);
  setText(
    "alert-hint",
    Number(status.open_alerts) > 0 ? "有开放告警，先看阻断项再拉数" : "当前无开放告警",
  );
  document.querySelector(".metrics")?.classList.remove("is-loading");
  renderTasks(status.recent_tasks || []);
  renderSources(sources);
  renderPorts(ports);
  renderKv("data-summary", [
    ["交易日历行数", status.trade_calendar_rows],
    ["涨跌停/停牌行数", status.limit_suspension_rows],
    ["因子信号行数", status.factor_signal_rows],
    ["开放阻断", status.open_quality_blocks ?? status.open_quality_issues],
    ["开放警告", status.open_quality_warns ?? 0],
  ]);
  renderKv(
    "layout-grid",
    Object.entries(status.layout || health.layout || {}).map(([k, v]) => [k, v]),
  );
}

function showActionError(message) {
  const el = document.getElementById("action-error");
  if (!el) {
    return;
  }
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = message;
}

async function runBootstrap() {
  showActionError("");
  try {
    const result = await requestJson("/api/admin/bootstrap", { method: "POST" });
    document.getElementById("market-date").value = "";
    await refresh();
    if (currentPage() === "data") {
      await loadQualityIssues();
    }
    if (result.skipped_market_daily) {
      setText("runtime", `运行正常 · 已保留现有 ${result.market_daily_rows} 行情，未覆盖演示数据`);
    }
  } catch (error) {
    showActionError(`初始化失败：${error.message}`);
  }
}

function applyTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  localStorage.setItem("asqt-theme", mode);
  document.getElementById("theme-dark").classList.toggle("active", mode === "dark");
  document.getElementById("theme-light").classList.toggle("active", mode === "light");
}

document.getElementById("bootstrap").addEventListener("click", () => {
  runBootstrap();
});

document.getElementById("sync-now").addEventListener("click", () => {
  triggerSync();
});

document.getElementById("theme-light").addEventListener("click", () => applyTheme("light"));
document.getElementById("theme-dark").addEventListener("click", () => applyTheme("dark"));

document.getElementById("quality-prev").addEventListener("click", () => {
  if (qualityState.page <= 1) {
    return;
  }
  qualityState.page -= 1;
  loadQualityIssues().catch((error) => {
    setText("quality-page-meta", `加载失败：${error.message}`);
  });
});

document.getElementById("quality-next").addEventListener("click", () => {
  if (qualityState.page >= qualityState.pages) {
    return;
  }
  qualityState.page += 1;
  loadQualityIssues().catch((error) => {
    setText("quality-page-meta", `加载失败：${error.message}`);
  });
});

function loadQualityOrError() {
  loadQualityIssues().catch((error) => {
    setText("quality-page-meta", `加载失败：${error.message}`);
  });
}

document.getElementById("quality-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  qualityState.status = document.getElementById("quality-status").value;
  qualityState.page = 1;
  loadQualityOrError();
});

document.getElementById("quality-status").addEventListener("change", (event) => {
  qualityState.status = event.target.value;
  qualityState.page = 1;
  loadQualityOrError();
});

document.getElementById("quality-severity").addEventListener("change", () => {
  qualityState.page = 1;
  loadQualityOrError();
});

document.getElementById("quality-body").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-close-issue]");
  if (button) {
    const issueId = button.dataset.closeIssue;
    button.disabled = true;
    try {
      await requestJson(`/api/quality/issues/${encodeURIComponent(issueId)}/close`, { method: "POST" });
      showToast("已关闭该条质量问题", "ok");
      if (qualityState.expandedId === issueId) {
        qualityState.expandedId = "";
      }
      await loadQualityIssues();
      await refresh();
    } catch (error) {
      button.disabled = false;
      showToast(error.message || "关闭失败", "warn");
    }
    return;
  }
  const row = event.target.closest("tr.quality-row");
  if (!row) {
    return;
  }
  const issueId = row.dataset.issueId || "";
  qualityState.expandedId = qualityState.expandedId === issueId ? "" : issueId;
  document.querySelectorAll("#quality-body tr.quality-row").forEach((item) => {
    const open = item.dataset.issueId === qualityState.expandedId;
    item.classList.toggle("is-open", open);
    const detail = item.nextElementSibling;
    if (detail && detail.classList.contains("quality-detail")) {
      detail.hidden = !open;
    }
  });
});

const SYNC_TRIGGER_LABEL = { manual: "人工", auto: "自动" };
function syncStatusLabel(row) {
  const base = SYNC_STATUS_LABEL[row.status] || row.status || "-";
  if (row.status === "queued" || row.status === "running") {
    const pct = row.progress_pct;
    if (pct == null || pct === "") {
      return base;
    }
    return `${base} ${Number(pct)}%`;
  }
  return base;
}

function syncStatusTitle(row) {
  if (row.status !== "queued" && row.status !== "running") {
    return "";
  }
  const done = row.progress_done;
  const total = row.progress_total;
  const symbol = row.progress_symbol || "";
  if (total) {
    return `已处理 ${done || 0}/${total}${symbol ? ` ${symbol}` : ""}`;
  }
  return "";
}
const syncState = { page: 1, pages: 1, status: "all", trigger: "all", seq: 0 };
let syncTimer = 0;
let watchedRunId = "";

function showToast(message, tone) {
  const host = document.getElementById("toast-host");
  if (!host || !message) {
    return;
  }
  const el = document.createElement("div");
  el.className = "toast";
  el.dataset.tone = tone || "ok";
  el.textContent = message;
  host.prepend(el);
  window.setTimeout(() => el.remove(), 5200);
}

const SYNC_NOW_IDLE = "追加行情";

function syncBusyLabel(row) {
  if (!row) {
    return "追加中…";
  }
  if (row.status === "queued") {
    return "排队中…";
  }
  const pct = row.progress_pct;
  if (pct == null || pct === "") {
    return "追加中…";
  }
  return `追加中 ${Number(pct)}%`;
}

function setSyncBusy(busy, label) {
  const btn = document.getElementById("sync-now");
  if (!btn) {
    return;
  }
  const on = Boolean(busy);
  btn.disabled = on;
  btn.setAttribute("aria-disabled", on ? "true" : "false");
  btn.setAttribute("aria-busy", on ? "true" : "false");
  btn.setAttribute("aria-readonly", on ? "true" : "false");
  btn.title = on ? label || "正在追加，请稍候" : SYNC_NOW_IDLE;
  btn.textContent = on ? label || "追加中…" : SYNC_NOW_IDLE;
}

function syncToastForRun(row) {
  const asof = row.max_trade_date_after || row.max_trade_date_before || "";
  if (row.status === "success") {
    showToast(`质检通过，行情已追加到 ${asof || "最新交易日"}`, "pass");
    return;
  }
  if (row.status === "skipped") {
    showToast(`行情已是最新（截止 ${asof || "-"}），质检通过`, "pass");
    return;
  }
  if (row.status === "quality_failed") {
    showToast(row.fail_reason || "质检未通过", "block");
    return;
  }
  if (row.status === "failed") {
    showToast(row.fail_reason || "同步失败", "block");
  }
}

function watchSyncRun(runId) {
  watchedRunId = runId;
  window.clearInterval(syncTimer);
  setSyncBusy(true, "追加中…");
  const tick = () => {
    requestJson(`/api/sync/runs/${runId}`)
      .then((row) => {
        if (["queued", "running"].includes(row.status)) {
          setSyncBusy(true, syncBusyLabel(row));
          if (currentPage() === "sync") {
            loadSyncRuns().catch(() => {});
          }
          return;
        }
        window.clearInterval(syncTimer);
        watchedRunId = "";
        setSyncBusy(false);
        syncToastForRun(row);
        loadSyncRuns().catch(() => {});
        refresh().catch(() => {});
        if (currentPage() === "data") {
          loadQualityIssues().catch(() => {});
        }
      })
      .catch(() => {});
  };
  tick();
  syncTimer = window.setInterval(tick, 1500);
}

async function triggerSync() {
  const btn = document.getElementById("sync-now");
  if (btn?.disabled) {
    return;
  }
  setSyncBusy(true, "追加中…");
  try {
    const result = await requestJson("/api/sync/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "baostock" }),
    });
    showToast("已开始追加行情与质检（异步）", "ok");
    watchSyncRun(result.run_id);
    if (currentPage() === "sync") {
      loadSyncRuns().catch(() => {});
    }
  } catch (error) {
    setSyncBusy(false);
    showToast(error.message || "无法开始同步", "warn");
  }
}

function syncSchedulerHint(scheduler) {
  if (!scheduler.enabled) {
    return "自动同步已关闭。可用右上角「追加行情」人工触发。";
  }
  const next = scheduler.next_at ? formatDateTime(scheduler.next_at, false) : "-";
  const window = scheduler.window || "16:30";
  const deadline = scheduler.deadline || "17:30";
  const tz = scheduler.timezone || "Asia/Shanghai";
  return `人工点「追加行情」立即异步执行；每个交易日 ${window} 起等主源确认当日 K 再质检，${deadline} 起按原逻辑重试直到成功（${tz}）；下次 ${next}。`;
}

async function resumeActiveSync() {
  try {
    const payload = await requestJson("/api/sync/active");
    if (payload.active && payload.active.run_id) {
      watchSyncRun(payload.active.run_id);
    }
    if (payload.scheduler) {
      setText("sync-scheduler-hint", syncSchedulerHint(payload.scheduler));
    }
  } catch (_err) {
    /* ignore */
  }
}

function renderSyncRuns(payload) {
  const body = document.getElementById("sync-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const items = payload.items || [];
  if (!items.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.className = "table-empty";
    td.textContent = "还没有同步记录。";
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    const startNo = ((Number(payload.page) || 1) - 1) * (Number(payload.page_size) || 20);
    items.forEach((row, index) => {
      const tr = document.createElement("tr");
      const windowLabel = row.start_date && row.end_date ? `${row.start_date} → ${row.end_date}` : "-";
      const qualityLabel =
        row.quality_ok == null ? "-" : Number(row.quality_ok) ? "通过" : "未通过";
      appendCell(tr, String(startNo + index + 1), { className: "num" });
      appendCell(tr, formatDateTime(row.started_at || row.created_at));
      appendCell(tr, formatDateTime(row.finished_at));
      appendCell(tr, SYNC_TRIGGER_LABEL[row.trigger] || row.trigger || "-");
      appendCell(tr, syncStatusLabel(row), {
        tone: toneForSync(row.status),
        title: syncStatusTitle(row) || row.fail_reason || "",
      });
      appendCell(tr, windowLabel);
      appendCell(tr, row.max_trade_date_after || row.max_trade_date_before || "-");
      appendCell(tr, row.normalized_rows == null ? "-" : String(row.normalized_rows), { className: "num" });
      appendCell(tr, qualityLabel, {
        tone: row.quality_ok == null ? "muted" : Number(row.quality_ok) ? "ok" : "block",
      });
      appendCell(tr, row.fail_reason || "-", { className: "cell-clip", title: row.fail_reason || row.detail || "" });
      body.appendChild(tr);
    });
  }
  const total = Number(payload.total) || 0;
  const page = Number(payload.page) || 1;
  const pages = Number(payload.pages) || 1;
  const size = Number(payload.page_size) || 20;
  syncState.page = page;
  syncState.pages = pages;
  setText("sync-page-meta", total ? `第 ${page}/${pages} 页 · 共 ${total} 条` : "0 条");
  setText("sync-page-label", `${page} / ${pages} · 每页 ${size}`);
  document.getElementById("sync-prev").disabled = page <= 1;
  document.getElementById("sync-next").disabled = page >= pages || total === 0;
  if (payload.scheduler) {
    setText("sync-scheduler-hint", syncSchedulerHint(payload.scheduler));
  }
}

async function loadSyncRuns() {
  const seq = ++syncState.seq;
  const params = new URLSearchParams({
    page: String(syncState.page),
    page_size: "20",
    status: syncState.status,
    trigger: syncState.trigger,
  });
  const payload = await requestJson(`/api/sync/runs?${params.toString()}`);
  if (seq !== syncState.seq) {
    return;
  }
  renderSyncRuns(payload);
  if (payload.active && payload.active.run_id && payload.active.run_id !== watchedRunId) {
    watchSyncRun(payload.active.run_id);
  }
}

document.getElementById("sync-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  syncState.status = document.getElementById("sync-status").value;
  syncState.trigger = document.getElementById("sync-trigger").value;
  syncState.page = 1;
  loadSyncRuns().catch((error) => setText("sync-page-meta", `加载失败：${error.message}`));
});

document.getElementById("sync-status").addEventListener("change", (event) => {
  syncState.status = event.target.value;
  syncState.page = 1;
  loadSyncRuns().catch((error) => setText("sync-page-meta", `加载失败：${error.message}`));
});

document.getElementById("sync-trigger").addEventListener("change", (event) => {
  syncState.trigger = event.target.value;
  syncState.page = 1;
  loadSyncRuns().catch((error) => setText("sync-page-meta", `加载失败：${error.message}`));
});

document.getElementById("sync-prev").addEventListener("click", () => {
  if (syncState.page <= 1) {
    return;
  }
  syncState.page -= 1;
  loadSyncRuns().catch((error) => setText("sync-page-meta", `加载失败：${error.message}`));
});

document.getElementById("sync-next").addEventListener("click", () => {
  if (syncState.page >= syncState.pages) {
    return;
  }
  syncState.page += 1;
  loadSyncRuns().catch((error) => setText("sync-page-meta", `加载失败：${error.message}`));
});

document.getElementById("market-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  loadMarketSnapshot().catch((error) => {
    setText("market-file", `加载失败：${error.message}`);
  });
});

let codeTimer = 0;
document.getElementById("market-code").addEventListener("input", () => {
  window.clearTimeout(codeTimer);
  codeTimer = window.setTimeout(() => {
    loadMarketSnapshot().catch((error) => {
      setText("market-file", `加载失败：${error.message}`);
    });
  }, 280);
});

let qualityCodeTimer = 0;
document.getElementById("quality-code").addEventListener("input", () => {
  window.clearTimeout(qualityCodeTimer);
  qualityCodeTimer = window.setTimeout(() => {
    qualityState.page = 1;
    loadQualityOrError();
  }, 280);
});

document.querySelectorAll(".sort-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.sort;
    const scope = btn.dataset.sortScope;
    if (scope === "quality") {
      if (qualityState.sort === key) {
        qualityState.order = qualityState.order === "desc" ? "asc" : "desc";
      } else {
        qualityState.sort = key;
        qualityState.order = "desc";
      }
      qualityState.page = 1;
      loadQualityOrError();
      return;
    }
    if (marketState.sort === key) {
      marketState.order = marketState.order === "desc" ? "asc" : "desc";
    } else {
      marketState.sort = key;
      marketState.order = "desc";
    }
    loadMarketSnapshot().catch((error) => {
      setText("market-file", `加载失败：${error.message}`);
    });
  });
});

function enhanceSelect(select) {
  if (select.dataset.enhanced === "1") {
    return;
  }
  select.dataset.enhanced = "1";
  const wrap = document.createElement("div");
  wrap.className = select.dataset.asqtSelect === "wide" ? "asqt-select asqt-select-wide" : "asqt-select";
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "asqt-select-trigger";
  const menu = document.createElement("ul");
  menu.className = "asqt-select-menu";
  menu.hidden = true;
  wrap.append(trigger, menu);

  function currentLabel() {
    const selected = select.options[select.selectedIndex];
    return selected ? selected.textContent : "请选择";
  }

  function renderMenu() {
    menu.innerHTML = "";
    [...select.options].forEach((option) => {
      const li = document.createElement("li");
      li.textContent = option.textContent;
      li.dataset.value = option.value;
      if (option.selected) {
        li.className = "is-active";
      }
      li.addEventListener("click", () => {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        closeAllSelects();
      });
      menu.appendChild(li);
    });
    trigger.textContent = currentLabel() || "请选择";
    trigger.classList.toggle("is-placeholder", !select.value && currentLabel() === "全部");
  }

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    const open = menu.hidden;
    closeAllSelects();
    if (open) {
      menu.hidden = false;
      wrap.classList.add("is-open");
    }
  });
  select.addEventListener("change", renderMenu);
  renderMenu();
}

function closeAllSelects() {
  document.querySelectorAll(".asqt-select").forEach((wrap) => {
    wrap.classList.remove("is-open");
    const menu = wrap.querySelector(".asqt-select-menu");
    if (menu) {
      menu.hidden = true;
    }
  });
}

function enhanceSelects() {
  document.querySelectorAll("select[data-asqt-select]").forEach(enhanceSelect);
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".asqt-select")) {
    closeAllSelects();
  }
});

function applySidebar(collapsed) {
  document.querySelector(".shell")?.classList.toggle("sidebar-collapsed", collapsed);
  localStorage.setItem("asqt-sidebar", collapsed ? "1" : "0");
  const btn = document.getElementById("sidebar-toggle");
  if (btn) {
    btn.textContent = collapsed ? "⟩" : "⟨";
  }
}

function applyTasks(collapsed) {
  document.querySelector(".overview-workbench")?.classList.toggle("tasks-collapsed", collapsed);
  localStorage.setItem("asqt-tasks", collapsed ? "1" : "0");
  const btn = document.getElementById("tasks-toggle");
  if (btn) {
    btn.textContent = collapsed ? "⟨" : "⟩";
  }
}

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  applySidebar(!document.querySelector(".shell")?.classList.contains("sidebar-collapsed"));
});

document.getElementById("tasks-toggle").addEventListener("click", () => {
  applyTasks(!document.querySelector(".overview-workbench")?.classList.contains("tasks-collapsed"));
});

function renderOrders(rows) {
  const body = document.getElementById("order-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "还没有 mock 订单。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    appendCell(tr, row.created_at || "-");
    appendCell(tr, row.symbol || "-");
    appendCell(tr, row.side === "SELL" ? "卖出" : row.side === "BUY" ? "买入" : row.side || "-");
    appendCell(tr, row.quantity == null ? "-" : String(row.quantity));
    appendCell(tr, ORDER_STATUS_LABEL[row.status] || row.status || "-", { tone: toneForOrder(row.status) });
    appendCell(tr, row.risk_tags || "-");
    body.appendChild(tr);
  }
}

const STRATEGY_LABEL = {
  etf_ma_rotate: "ETF 均线轮动",
  stock_momentum_topk: "股票动量 TopK",
};
function formatPct(value) {
  if (value == null || value === "") {
    return "-";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "-";
  }
  return `${(number * 100).toFixed(2)}%`;
}

function renderStrategyVersions(rows) {
  const body = document.getElementById("strategy-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "还没有策略版本。先点「重跑回测」或命令行 asqt research-backtest --strategy all。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id);
    appendCell(tr, row.version || "v1");
    appendCell(tr, STRATEGY_STATUS_LABEL[row.status] || row.status || "-", { tone: toneForStrategy(row.status) });
    appendCell(tr, row.parameter_set_id || "-");
    appendCell(tr, row.code_version || "-");
    appendCell(tr, row.effective_date || "-");
    body.appendChild(tr);
  }
}

function renderExperiments(rows) {
  const body = document.getElementById("experiment-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "还没有实验记录。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    const isRet = row.metrics?.is?.total_return;
    const oosRet = row.metrics?.oos?.total_return;
    const oosDd = row.metrics?.oos?.max_drawdown;
    appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id);
    appendCell(tr, STRATEGY_STATUS_LABEL[row.status] || row.status || "-", { tone: toneForStrategy(row.status) });
    appendCell(tr, formatPct(isRet));
    appendCell(tr, formatPct(oosRet));
    appendCell(tr, formatPct(oosDd));
    appendCell(tr, row.data_version || "-");
    body.appendChild(tr);
  }
}

async function loadStrategyPage() {
  const [versions, experiments] = await Promise.all([
    requestJson("/api/strategies"),
    requestJson("/api/research/experiments"),
  ]);
  renderStrategyVersions(versions);
  renderExperiments(experiments);
}

function renderAttribution(payload) {
  const body = document.getElementById("review-body");
  const summary = document.getElementById("review-summary");
  if (!body || !summary) {
    return;
  }
  summary.innerHTML = "";
  const paper = payload.paper_vs_backtest || {};
  const entries = payload.ok
    ? [
        ["净值", Number(payload.nav || 0).toFixed(4)],
        ["复利收益", formatPct(payload.total_return)],
        ["累加贡献", formatPct(payload.additive_return)],
        ["样本内贡献", formatPct(payload.is_contribution)],
        ["样本外贡献", formatPct(payload.oos_contribution)],
        ["样本内截止", payload.in_sample_end || "-"],
        ["模拟偏差", paper.available ? "可算" : "尚无模拟成交"],
      ]
    : [
        ["状态", "无法归因"],
        ["原因", payload.reason || "-"],
        ["模拟偏差", paper.detail || "尚无模拟成交"],
      ];
  for (const [label, value] of entries) {
    const item = document.createElement("div");
    item.className = "kv-item";
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = value;
    item.append(k, v);
    summary.appendChild(item);
  }
  setText(
    "review-hint",
    paper.available
      ? "按标的累加每日贡献。"
      : "按标的累加每日贡献。模拟 vs 回测偏差要等 PaperBroker 成交后才能算。",
  );
  body.innerHTML = "";
  const rows = payload.by_symbol || [];
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = payload.reason === "quality_block" ? "质量闸门阻断，未做归因。" : "还没有归因行。先在策略页跑回测。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    const cells = [
      formatPct(row.contribution),
      formatPct(row.is_contribution),
      formatPct(row.oos_contribution),
    ];
    appendCell(tr, row.symbol);
    for (const value of cells) {
      const down = typeof value === "string" && value.endsWith("%") && value.startsWith("-") && value !== "-0.00%";
      appendCell(tr, value, { className: down ? "num chg-down" : "num" });
    }
    appendCell(tr, row.days == null ? "-" : String(row.days), { className: "num" });
    appendCell(tr, formatPct(row.avg_weight), { className: "num" });
    body.appendChild(tr);
  }
}

async function loadReviewPage() {
  const select = document.getElementById("review-strategy");
  const strategyId = select?.value || "etf_ma_rotate";
  const payload = await requestJson(`/api/research/attribution?strategy_id=${encodeURIComponent(strategyId)}`);
  renderAttribution(payload);
}

let backtestTimer = 0;
let watchedBacktestId = "";

function setBacktestBusy(busy) {
  const button = document.getElementById("strategy-run");
  if (button) {
    button.disabled = Boolean(busy);
  }
}

function backtestProgressText(row) {
  const pct = row.progress_pct == null || row.progress_pct === "" ? "" : `${Number(row.progress_pct)}%`;
  const label = row.progress_label || "";
  if (row.status === "queued") {
    return pct ? `回测排队 ${pct}` : "回测已入队";
  }
  if (row.status === "running") {
    return `回测计算中 ${pct || ""}${label ? ` · ${label}` : ""}`.replace(/\s+/g, " ").trim();
  }
  if (row.status === "success") {
    return label || "回测完成";
  }
  return row.fail_reason || label || "回测失败";
}

function finishBacktestWatch(row) {
  const result = document.getElementById("strategy-run-result");
  const reports = row.detail?.reports || [];
  const summary = reports
    .map((item) => `${STRATEGY_LABEL[item.strategy_id] || item.strategy_id} ${STRATEGY_STATUS_LABEL[item.status] || item.status}`)
    .join(" · ");
  if (result) {
    result.hidden = false;
    result.textContent = summary || backtestProgressText(row);
  }
  if (row.status === "success") {
    showToast("回测完成", "ok");
  } else {
    showToast(row.fail_reason || "回测未全部通过", "block");
  }
  loadStrategyPage().catch(() => {});
}

function watchBacktest(runId) {
  watchedBacktestId = runId;
  window.clearInterval(backtestTimer);
  setBacktestBusy(true);
  const result = document.getElementById("strategy-run-result");
  if (result) {
    result.hidden = false;
    result.textContent = "回测已入队";
  }
  const tick = () => {
    requestJson(`/api/research/backtest/${runId}`)
      .then((row) => {
        if (result) {
          result.textContent = backtestProgressText(row);
        }
        if (row.status === "queued" || row.status === "running") {
          return;
        }
        window.clearInterval(backtestTimer);
        watchedBacktestId = "";
        setBacktestBusy(false);
        finishBacktestWatch(row);
      })
      .catch(() => {});
  };
  tick();
  backtestTimer = window.setInterval(tick, 1000);
}

async function resumeActiveBacktest() {
  try {
    const payload = await requestJson("/api/research/backtest/active");
    if (payload.active && payload.active.run_id) {
      watchBacktest(payload.active.run_id);
    }
  } catch (_err) {
    /* ignore */
  }
}

const strategyRunForm = document.getElementById("strategy-run-form");
if (strategyRunForm) {
  strategyRunForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const result = document.getElementById("strategy-run-result");
    if (result) {
      result.hidden = false;
      result.textContent = "回测入队中…";
    }
    setBacktestBusy(true);
    try {
      const payload = await requestJson("/api/research/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: document.getElementById("strategy-run-id").value }),
      });
      showToast("回测已在后台开始", "ok");
      watchBacktest(payload.run_id);
    } catch (error) {
      setBacktestBusy(false);
      if (result) {
        result.textContent = `回测失败：${error.message}`;
      }
      showToast(error.message || "回测失败", "block");
    }
  });
}

const reviewFilterForm = document.getElementById("review-filter-form");
if (reviewFilterForm) {
  reviewFilterForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await loadReviewPage();
    } catch (error) {
      setText("review-hint", `加载失败：${error.message}`);
    }
  });
}

async function loadOrders() {
  const rows = await requestJson("/api/orders?limit=20");
  renderOrders(rows);
}

document.getElementById("mock-order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = document.getElementById("order-result");
  result.hidden = false;
  try {
    const payload = await requestJson("/api/orders/mock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: document.getElementById("order-symbol").value.trim(),
        side: document.getElementById("order-side").value,
        quantity: Number(document.getElementById("order-qty").value) || 100,
      }),
    });
    result.textContent = payload.accepted
      ? `已受理 ${payload.order.status}（mock）`
      : `已拒绝：${payload.reason || "quality_block"}，开放 block ${payload.quality?.block_count ?? "-"}`;
    await loadOrders();
  } catch (error) {
    result.textContent = `下单失败：${error.message}`;
  }
});

window.addEventListener("hashchange", () => showPage(currentPage()));

document.querySelectorAll("#nav a").forEach((link) => {
  link.addEventListener("click", (event) => {
    const page = link.dataset.page;
    if (!page) {
      return;
    }
    event.preventDefault();
    const next = `#${page}`;
    if (location.hash === next) {
      showPage(page);
      return;
    }
    location.hash = next;
  });
});

function bindTips() {
  let pop = document.getElementById("asqt-tooltip");
  if (!pop) {
    pop = document.createElement("div");
    pop.id = "asqt-tooltip";
    pop.className = "tip-pop-fixed";
    pop.hidden = true;
    document.body.appendChild(pop);
  }
  const place = (anchor) => {
    const box = anchor.getBoundingClientRect();
    pop.hidden = false;
    pop.style.left = "0px";
    pop.style.top = "0px";
    const width = pop.offsetWidth;
    const height = pop.offsetHeight;
    let left = box.right - width;
    let top = box.top - height - 8;
    if (left < 8) {
      left = 8;
    }
    if (top < 8) {
      top = box.bottom + 8;
    }
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
  };
  document.querySelectorAll(".tip[data-tip]").forEach((el) => {
    const show = () => {
      pop.textContent = el.getAttribute("data-tip") || "";
      place(el);
    };
    const hide = () => {
      pop.hidden = true;
    };
    el.addEventListener("mouseenter", show);
    el.addEventListener("focus", show);
    el.addEventListener("mouseleave", hide);
    el.addEventListener("blur", hide);
  });
}

applyTheme(localStorage.getItem("asqt-theme") || "dark");
enhanceSelects();
bindTips();
applySidebar(localStorage.getItem("asqt-sidebar") === "1");
applyTasks(localStorage.getItem("asqt-tasks") === "1");
showPage(currentPage());
refresh().catch((error) => {
  setText("runtime", `加载失败：${error.message}`);
  showActionError(`加载失败：${error.message}`);
});
resumeActiveSync();
resumeActiveBacktest();
