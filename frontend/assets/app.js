const PAGE_TITLES = {
  overview: "系统总览",
  data: "数据",
  sync: "数据同步",
  strategy: "策略",
  orders: "交易",
  review: "复盘",
  settings: "设置",
};

const GATE_DENY_LABEL = {
  kill_switch: "急停已打开，不能准入或恢复模拟。请先到交易页关闭急停后再试。",
  quality_block: "存在未关闭的质量阻断，不能准入或恢复模拟。",
  missing_experiment: "缺少最近一次回测报告，不能准入或恢复模拟。请先重跑回测。",
  experiment_not_ok: "最近一次回测未通过，不能准入或恢复模拟。",
  missing_version_pins: "回测报告缺少参数组或数据版本钉扎，不能准入或恢复模拟。",
  no_version: "该策略还没有版本，不能改生命周期。请先重跑回测。",
  not_orderable: "当前状态不能生成可下单目标仓。仅「模拟」状态可以。",
  bad_action: "动作只能是准入模拟、暂停、恢复或退役。",
  paper_busy: "模拟盘运行中，请勿重复提交",
  "kill switch change requires a reason": "请填写急停原因（不能全是空格）",
  "lifecycle change requires a reason": "改生命周期必须填写原因。",
};

function formatApiDetail(detail) {
  if (detail == null || detail === "") {
    return "";
  }
  if (typeof detail === "string") {
    return GATE_DENY_LABEL[detail] || RISK_TAG_LABEL[detail] || detail;
  }
  if (typeof detail === "object") {
    if (detail.message) {
      return String(detail.message);
    }
    if (detail.code) {
      return GATE_DENY_LABEL[detail.code] || RISK_TAG_LABEL[detail.code] || String(detail.code);
    }
  }
  return JSON.stringify(detail);
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail != null) {
        detail = formatApiDetail(body.detail) || detail;
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
  const raw = (location.hash || "#overview").replace("#", "");
  const page = raw.split(/[/?]/)[0];
  return PAGE_TITLES[page] ? page : "overview";
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
  partial: "未完整",
  review: "待复核",
  blocked: "质检未通过",
};

const TASK_NAME_LABEL = {
  "paper-run-job": "跑模拟",
  "paper-run": "跑模拟",
  "paper-daily": "日终模拟",
  "research-backtest": "回测",
  "research_backtest": "回测",
  "sync-daily": "同步行情",
  sync_daily: "同步行情",
  "check-quality": "质检",
  check_quality: "质检",
  pull_daily: "拉取日K",
  "pull-daily": "拉取日K",
  reconcile_daily: "跨源对账",
  "reconcile-daily": "跨源对账",
  cash_reconcile: "财务对账",
  "cash-reconcile": "财务对账",
  seed_demo: "初始化演示",
  "seed-demo": "初始化演示",
  universe_load: "加载股票池",
  "universe-load": "加载股票池",
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
const RISK_TAG_LABEL = {
  positions: "未准入模拟",
  not_paper: "未准入模拟",
  quality_block: "质量阻断",
  kill_switch: "急停",
  channel_unavailable: "通道不可用",
  calendar_closed: "非交易日",
  suspended: "停牌",
  limit_up: "涨停",
  limit_down: "跌停",
  lot_size: "手数不符",
  name_cap: "超单票上限",
  gross_limit: "超总仓上限",
  cash: "现金不足",
  mock: "演示单",
  paper: "模拟",
};

function formatRiskTags(value) {
  if (value == null || value === "") {
    return "-";
  }
  return String(value)
    .split(",")
    .map((part) => {
      const key = part.trim();
      return RISK_TAG_LABEL[key] || key;
    })
    .filter(Boolean)
    .join("、") || "-";
}

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
  if (status === "skipped" || status === "partial" || status === "review") {
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

function formatTaskName(name) {
  if (!name) {
    return "-";
  }
  if (TASK_NAME_LABEL[name]) {
    return TASK_NAME_LABEL[name];
  }
  const alt = name.includes("_") ? name.replaceAll("_", "-") : name.replaceAll("-", "_");
  return TASK_NAME_LABEL[alt] || name;
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
    const statusLabel =
      (
        task.task_name === "reconcile-daily" ||
        task.task_name === "reconcile_daily" ||
        task.task_name === "cash-reconcile" ||
        task.task_name === "cash_reconcile"
      ) && status === "partial"
        ? "待复核"
        : SYNC_STATUS_LABEL[status] || status || "-";
    left.textContent = `${formatTaskName(task.task_name)} ${formatDateTime(task.started_at)}`;
    const tag = makeTag(statusLabel, toneForSync(status));
    if (task.message) {
      tag.title = typeof task.message === "string" ? task.message : JSON.stringify(task.message);
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

const ALERT_LEVEL_LABEL = {
  info: "提示",
  high: "重要",
  critical: "严重",
};

const ALERT_CATEGORY_LABEL = {
  drawdown: "回撤",
  kill_switch: "急停",
  paper_trading: "模拟开关",
  quality: "质量",
  ops: "运维",
  reconcile: "跨源对账",
  cash_reconcile: "财务对账",
  paper_daily: "日终模拟",
};

const ALERT_TITLE_LABEL = {
  "max drawdown stop": "回撤触发急停",
  "max drawdown warning": "回撤预警",
  "kill switch on": "急停已打开",
  "paper trading on": "模拟交易已开启",
  "跨源对账完成": "跨源对账完成",
  "跨源对账待复核": "跨源对账待复核",
  "跨源对账失败": "跨源对账失败",
  "财务对账通过": "财务对账通过",
  "财务对账跳过": "财务对账跳过",
  "财务对账不一致": "财务对账不一致",
  "财务对账失败": "财务对账失败",
};

const ALERT_KIND_LABEL = {
  actionable: "需关注",
  dup: "重复主题",
  stale: "已过期",
  state: "状态提示",
  info: "一般提示",
  noise: "噪音",
};

let alertIntelState = { noise_ids: [], groups: [], open_ids: [] };
let alertListState = { expandedId: "" };

function formatAlertTitle(row) {
  return ALERT_TITLE_LABEL[row.title] || row.title || "-";
}

function moneyText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-";
  }
  return number.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function pctText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-";
  }
  return `${(Math.abs(number) * 100).toFixed(2)}%`;
}

function parseAlertDetail(row) {
  const raw = String(row?.detail || "").trim();
  if (!raw) {
    return {};
  }
  if (raw.startsWith("{")) {
    try {
      const data = JSON.parse(raw);
      if (data && typeof data === "object") {
        return data;
      }
    } catch (_error) {
      /* legacy plain text */
    }
  }
  const out = { raw };
  const ddMatch = raw.match(/dd\s*=\s*(-?[0-9.]+)/i);
  if (ddMatch) {
    const dd = Number(ddMatch[1]);
    if (Number.isFinite(dd)) {
      out.dd = dd;
      out.dd_pct = Math.abs(dd) * 100;
      out.summary = `回撤 ${pctText(dd)}`;
    }
  }
  const parts = raw
    .split(/[;；]/)
    .map((part) => part.trim())
    .filter(Boolean);
  const readable = parts.filter((part) => !/^dd\s*=/i.test(part));
  if (readable.length) {
    out.legacy_text = readable.join("；");
    if (!out.summary) {
      out.summary = readable[0];
    }
  }
  return out;
}

function formatAlertSummary(row) {
  const payload = parseAlertDetail(row);
  if (payload.summary) {
    return payload.summary;
  }
  if (payload.legacy_text) {
    return payload.legacy_text;
  }
  const title = formatAlertTitle(row);
  if (payload.dd != null) {
    const stop =
      row?.level === "critical" ||
      String(payload.kind || "").endsWith("stop") ||
      String(row?.title || "").includes("stop");
    const warn =
      String(payload.kind || "").endsWith("warn") || String(row?.title || "").includes("warning");
    if (stop) {
      return `回撤 ${pctText(payload.dd)} 触发急停`;
    }
    if (warn) {
      return `回撤 ${pctText(payload.dd)} 触及预警`;
    }
    return `回撤 ${pctText(payload.dd)}`;
  }
  const raw = String(row?.detail || "").trim();
  if (/^dd\s*=/i.test(raw)) {
    return title;
  }
  return raw || title;
}

function appendAlertSummaryCell(tr, row) {
  const td = document.createElement("td");
  td.className = "alert-detail-cell cell-clip";
  const payload = parseAlertDetail(row);
  const summary = formatAlertSummary(row);
  td.title = summary;
  if (payload.dd != null) {
    const match = summary.match(/^(.*?)(回撤\s*)([0-9.]+%)(.*)$/);
    if (match) {
      if (match[1]) {
        td.append(match[1]);
      }
      td.append(match[2]);
      const span = document.createElement("span");
      span.className = "alert-dd";
      span.textContent = match[3];
      td.appendChild(span);
      if (match[4]) {
        td.append(match[4]);
      }
    } else {
      td.textContent = summary;
    }
  } else {
    td.textContent = summary;
  }
  tr.appendChild(td);
}

function appendAlertFullDetail(container, row) {
  container.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "alert-detail-full";
  const payload = parseAlertDetail(row);
  const category = row?.category || "";
  const lines = [];
  const push = (label, value, { tone } = {}) => {
    if (value == null || value === "") {
      return;
    }
    lines.push({ label, value: String(value), tone });
  };
  push("级别", ALERT_LEVEL_LABEL[row?.level] || row?.level || "-");
  push("类别", ALERT_CATEGORY_LABEL[category] || category || "-");
  push("事件", formatAlertTitle(row));

  const strategyLabel = {
    etf_ma_rotate: "ETF 均线轮动",
    stock_momentum_topk: "股票动量 TopK",
    etf_momentum_topk: "ETF 动量 TopK",
    stock_lowvol_momentum: "股票低波动量",
    etf_ma_momentum_filter: "ETF 均线动量过滤",
  };
  const isDrawdown =
    String(payload.kind || "").startsWith("drawdown") ||
    category === "drawdown" ||
    String(row?.title || "").includes("drawdown");

  if (isDrawdown) {
    if (payload.strategy_id) {
      push("策略", strategyLabel[payload.strategy_id] || payload.strategy_id);
    }
    if (payload.account_id) {
      push("账户", payload.account_id);
    }
    if (payload.trade_date) {
      push("成交日", payload.trade_date);
    }
    if (payload.dd != null) {
      const stop = row?.level === "critical" || String(payload.kind || "").endsWith("stop");
      const threshold =
        payload.threshold != null
          ? pctText(payload.threshold)
          : stop
            ? "12.00%"
            : "8.00%";
      push(
        "回撤",
        `${pctText(payload.dd)}（相对账户峰值；${stop ? "急停线" : "预警线"} ${threshold}）`,
        { tone: "dd" },
      );
    }
    if (payload.peak_asset != null) {
      push("账户峰值", moneyText(payload.peak_asset));
    }
    if (payload.total_asset != null) {
      push("当前总资产", moneyText(payload.total_asset));
    }
    if (payload.cash != null) {
      push("现金", moneyText(payload.cash));
    }
    if (payload.market_value != null) {
      push("持仓市值", moneyText(payload.market_value));
    }
    if (payload.initial_cash != null) {
      push("本金", moneyText(payload.initial_cash));
    }
    if (payload.pnl_vs_peak != null) {
      push("较峰值盈亏", moneyText(payload.pnl_vs_peak));
    }
    if (payload.pnl_vs_initial != null) {
      push("较本金盈亏", moneyText(payload.pnl_vs_initial));
    }
    if (payload.action) {
      push("处置", payload.action);
    } else if (payload.legacy_text) {
      push("说明", payload.legacy_text);
    } else if (payload.dd != null) {
      const stop = row?.level === "critical" || String(payload.kind || "").endsWith("stop");
      push(
        "处置",
        stop ? "已触发急停，停止新开仓与继续模拟成交。" : "未达急停线，请关注回撤与仓位。",
      );
    }
  } else if (category === "reconcile" || payload.kind === "cross_source_reconcile") {
    if (payload.summary) {
      push("摘要", payload.summary);
    }
    if (payload.window) {
      push("窗口", payload.window);
    }
    if (payload.trigger) {
      push("触发", payload.trigger);
    }
    if (payload.symbols != null) {
      push("标的数", payload.symbols);
    }
    if (payload.match_rate != null) {
      push("匹配率", `${(Number(payload.match_rate) * 100).toFixed(2)}%`);
    } else if (payload.match_rate_pct != null) {
      push("匹配率", `${payload.match_rate_pct}%`);
    }
    if (payload.matched_rows != null) {
      push("匹配行", `${payload.matched_rows}/${payload.stored_rows}（对照 ${payload.peer_rows}）`);
    }
    if (payload.mismatch_count != null) {
      push("价差差异", payload.mismatch_count);
    }
    if (payload.adj_baseline_count) {
      push("因子基准已对齐", `${payload.adj_baseline_count} 标的`);
    }
    if (payload.silent_inconsistent != null) {
      push("静默跳变异常", payload.silent_inconsistent);
    }
    if (payload.peer_error_count != null) {
      push("对照源错误", payload.peer_error_count);
    }
    if (payload.report || payload.report_path) {
      const raw = String(payload.report || payload.report_path || "");
      const name = raw.split(/[/\\]/).filter(Boolean).pop() || raw;
      push("报告", name);
    }
    if (payload.action) {
      push("处置", payload.action);
    }
  } else if (category === "cash_reconcile" || payload.kind === "cash_reconcile") {
    if (payload.summary) {
      push("摘要", payload.summary);
    }
    if (payload.trigger) {
      push("触发", payload.trigger);
    }
    if (payload.checked != null) {
      push(
        "已核对",
        `${payload.checked} · 不一致 ${payload.mismatch_count ?? 0} · 跳过 ${payload.skipped_count ?? 0}`,
      );
    }
    for (const item of payload.books || []) {
      const label = item.strategy_label || item.strategy_id || "策略";
      if (item.skipped) {
        push(label, "尚无账本");
        continue;
      }
      const status = item.ok ? "通过" : "不一致";
      push(
        label,
        `${status} · ${item.asof || "-"} · 本金 ${moneyText(item.initial_cash)} · 峰值 ${moneyText(item.peak_asset)}` +
          ` · 现金 ${moneyText(item.actual_cash)}（差额 ${moneyText(item.cash_diff)}）` +
          ` · 市值 ${moneyText(item.market_value)} · 总资产 ${moneyText(item.end_asset)}`,
      );
      if (item.failed_checks?.length) {
        push("失败项", item.failed_checks.join("、"));
      }
      if (item.qty_mismatches) {
        push("持仓数量不一致", item.qty_mismatches);
      }
    }
    if (payload.action) {
      push("处置", payload.action);
    }
  } else {
    const text = formatAlertFull(row)
      .split("\n")
      .slice(3)
      .filter(Boolean);
    text.forEach((line) => {
      const idx = line.indexOf("：");
      if (idx > 0) {
        push(line.slice(0, idx), line.slice(idx + 1));
      } else {
        push("说明", line);
      }
    });
  }

  for (const item of lines) {
    const line = document.createElement("div");
    line.className = "alert-detail-line";
    const label = document.createElement("span");
    label.className = "alert-detail-label";
    label.textContent = `${item.label}：`;
    line.appendChild(label);
    if (item.tone === "dd") {
      const match = String(item.value).match(/^([0-9.]+%)(.*)$/);
      if (match) {
        const dd = document.createElement("span");
        dd.className = "alert-dd";
        dd.textContent = match[1];
        line.appendChild(dd);
        if (match[2]) {
          line.append(match[2]);
        }
      } else {
        const dd = document.createElement("span");
        dd.className = "alert-dd";
        dd.textContent = item.value;
        line.appendChild(dd);
      }
    } else {
      line.append(item.value);
    }
    wrap.appendChild(line);
  }
  container.appendChild(wrap);
}

function formatAlertFull(row) {
  const payload = parseAlertDetail(row);
  const category = row?.category || "";
  const title = formatAlertTitle(row);
  const level = ALERT_LEVEL_LABEL[row?.level] || row?.level || "-";
  const lines = [
    `级别：${level}`,
    `类别：${ALERT_CATEGORY_LABEL[category] || category || "-"}`,
    `事件：${title}`,
  ];
  const strategyLabel = {
    etf_ma_rotate: "ETF 均线轮动",
    stock_momentum_topk: "股票动量 TopK",
    etf_momentum_topk: "ETF 动量 TopK",
    stock_lowvol_momentum: "股票低波动量",
    etf_ma_momentum_filter: "ETF 均线动量过滤",
  };

  if (
    String(payload.kind || "").startsWith("drawdown") ||
    category === "drawdown" ||
    String(row?.title || "").includes("drawdown")
  ) {
    if (payload.strategy_id) {
      lines.push(`策略：${strategyLabel[payload.strategy_id] || payload.strategy_id}`);
    }
    if (payload.account_id) {
      lines.push(`账户：${payload.account_id}`);
    }
    if (payload.trade_date) {
      lines.push(`成交日：${payload.trade_date}`);
    }
    if (payload.dd != null) {
      const stop = row?.level === "critical" || String(payload.kind || "").endsWith("stop");
      const threshold =
        payload.threshold != null
          ? pctText(payload.threshold)
          : stop
            ? "12.00%"
            : "8.00%";
      lines.push(
        `回撤：${pctText(payload.dd)}（相对账户峰值；${stop ? "急停线" : "预警线"} ${threshold}）`,
      );
    }
    if (payload.peak_asset != null) {
      lines.push(`账户峰值：${moneyText(payload.peak_asset)}`);
    }
    if (payload.total_asset != null) {
      lines.push(`当前总资产：${moneyText(payload.total_asset)}`);
    }
    if (payload.cash != null) {
      lines.push(`现金：${moneyText(payload.cash)}`);
    }
    if (payload.market_value != null) {
      lines.push(`持仓市值：${moneyText(payload.market_value)}`);
    }
    if (payload.initial_cash != null) {
      lines.push(`本金：${moneyText(payload.initial_cash)}`);
    }
    if (payload.pnl_vs_peak != null) {
      lines.push(`较峰值盈亏：${moneyText(payload.pnl_vs_peak)}`);
    }
    if (payload.pnl_vs_initial != null) {
      lines.push(`较本金盈亏：${moneyText(payload.pnl_vs_initial)}`);
    }
    if (payload.action) {
      lines.push(`处置：${payload.action}`);
    } else if (payload.legacy_text) {
      lines.push(`说明：${payload.legacy_text}`);
    } else if (payload.dd != null) {
      const stop = row?.level === "critical" || String(payload.kind || "").endsWith("stop");
      lines.push(
        stop
          ? "处置：已触发急停，停止新开仓与继续模拟成交。"
          : "处置：未达急停线，请关注回撤与仓位。",
      );
    }
    return lines.join("\n");
  }

  if (category === "kill_switch" || String(row?.title || "").includes("kill switch")) {
    let reason = payload.legacy_text || row?.detail || "操作员或风控触发";
    if (/^dd\s*=/i.test(String(reason))) {
      reason = "操作员或风控触发";
    }
    lines.push(`原因：${reason}`);
    lines.push("影响：解除前不能准入/恢复模拟，也不能继续有效成交。");
    return lines.join("\n");
  }

  if (category === "paper_trading" || String(row?.title || "").includes("paper trading")) {
    let reason = payload.legacy_text || row?.detail || "settings";
    if (reason === "settings") {
      reason = "设置页开启模拟交易";
    }
    lines.push(`原因：${reason}`);
    lines.push("说明：这是状态提示，不是故障。");
    return lines.join("\n");
  }

  const detail = payload.legacy_text || row?.detail;
  if (detail && !/^dd\s*=/i.test(String(detail))) {
    lines.push(`说明：${detail}`);
  } else {
    lines.push("说明：无附加字段。");
  }
  return lines.join("\n");
}

function formatAlertDetail(row) {
  return formatAlertSummary(row);
}

function alertNeedsConfirm(level) {
  return level === "critical" || level === "high";
}

async function confirmCloseAlerts({ count, level, label }) {
  const high = alertNeedsConfirm(level) || level === "mixed-high";
  if (!high) {
    return true;
  }
  const title = document.getElementById("confirm-title");
  if (title) {
    title.textContent = "关闭高等级告警";
  }
  const text =
    count > 1
      ? `即将关闭 ${count} 条告警（含重要/严重级${label ? `：${label}` : ""}）。确认继续？`
      : `即将关闭 1 条高等级告警${label ? `（${label}）` : ""}。确认继续？`;
  const ok = await confirmDialog(text);
  if (title) {
    title.textContent = "提示";
  }
  return ok;
}

async function closeAlertIds(ids, reason, { level = "info", label = "" } = {}) {
  const alertIds = [...new Set((ids || []).filter(Boolean))];
  if (!alertIds.length) {
    showToast("没有可关闭的告警", "warn");
    return false;
  }
  const confirmed = await confirmCloseAlerts({
    count: alertIds.length,
    level: alertIds.length > 1 && alertNeedsConfirm(level) ? "mixed-high" : level,
    label,
  });
  if (!confirmed) {
    return false;
  }
  if (alertIds.length === 1) {
    await requestJson(`/api/alerts/${encodeURIComponent(alertIds[0])}/close`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
  } else {
    await requestJson("/api/alerts/close-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alert_ids: alertIds, reason }),
    });
  }
  showToast(alertIds.length > 1 ? `已关闭 ${alertIds.length} 条告警` : "已关闭告警", "ok");
  if (alertIds.includes(alertListState.expandedId)) {
    alertListState.expandedId = "";
  }
  await refresh();
  return true;
}

function renderOverviewAlerts(rows) {
  const body = document.getElementById("overview-alert-body");
  const meta = document.getElementById("overview-alert-meta");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (meta) {
    meta.textContent = rows.length ? `开放 ${rows.length} 条 · 与上方计数同源` : "当前无开放告警";
  }
  if (!rows.length) {
    alertListState.expandedId = "";
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "没有开放告警。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  const ids = new Set(rows.map((row) => String(row.alert_id || "")).filter(Boolean));
  if (alertListState.expandedId && !ids.has(alertListState.expandedId)) {
    alertListState.expandedId = "";
  }
  for (const row of rows) {
    const alertId = String(row.alert_id || "");
    const open = alertListState.expandedId === alertId;
    const tr = document.createElement("tr");
    tr.className = open ? "alert-row is-open" : "alert-row";
    tr.dataset.alertId = alertId;
    tr.dataset.alertLevel = row.level || "";
    tr.dataset.alertTitle = formatAlertTitle(row);
    tr.setAttribute("aria-expanded", open ? "true" : "false");
    appendCell(tr, ALERT_LEVEL_LABEL[row.level] || row.level || "-", {
      tone: row.level === "critical" ? "block" : row.level === "high" ? "warn" : "muted",
    });
    appendCell(tr, ALERT_CATEGORY_LABEL[row.category] || row.category || "-");
    appendCell(tr, formatAlertTitle(row));
    appendAlertSummaryCell(tr, row);
    appendCell(tr, formatDateTime(row.created_at) || "-");
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary";
    btn.dataset.closeAlert = alertId;
    btn.textContent = "关闭";
    td.appendChild(btn);
    tr.appendChild(td);

    const expandTr = document.createElement("tr");
    expandTr.className = "alert-detail";
    expandTr.hidden = !open;
    const expandTd = document.createElement("td");
    expandTd.colSpan = 6;
    appendAlertFullDetail(expandTd, row);
    expandTr.appendChild(expandTd);

    body.appendChild(tr);
    body.appendChild(expandTr);
  }
}

function syncAlertRowExpansion() {
  document.querySelectorAll("#overview-alert-body tr.alert-row").forEach((item) => {
    const open = item.dataset.alertId === alertListState.expandedId;
    item.classList.toggle("is-open", open);
    item.setAttribute("aria-expanded", open ? "true" : "false");
    const detail = item.nextElementSibling;
    if (detail && detail.classList.contains("alert-detail")) {
      detail.hidden = !open;
    }
  });
}

function renderAlertIntel(payload) {
  const verdict = document.getElementById("alert-intel-verdict");
  const meta = document.getElementById("alert-intel-meta");
  const summary = document.getElementById("alert-intel-summary");
  const body = document.getElementById("alert-intel-body");
  const noiseBtn = document.getElementById("alert-close-noise");
  const allBtn = document.getElementById("alert-close-all");
  if (!body || !summary) {
    return;
  }
  const groups = payload.groups || [];
  const noiseIds = payload.noise_ids || [];
  const openIds = groups.flatMap((group) => group.all_ids || []);
  alertIntelState = { noise_ids: noiseIds, groups, open_ids: openIds };

  if (verdict) {
    verdict.textContent = payload.verdict || "暂无分析结果";
  }
  if (meta) {
    meta.textContent = payload.analyzed_at
      ? `实时汇总 · ${formatDateTime(payload.analyzed_at)}`
      : "按实时开放告警汇总";
  }

  summary.innerHTML = "";
  const cards = [
    ["开放总数", String(payload.open_count ?? 0)],
    ["有效关注", String(payload.signal_count ?? 0)],
    ["重复/过期噪音", String(payload.noise_count ?? 0)],
    ["状态提示", String(payload.state_count ?? 0)],
    ["急停开关", payload.kill_engaged ? "开" : "关"],
  ];
  for (const [label, value] of cards) {
    const item = document.createElement("div");
    item.className = "kv-item";
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = value;
    item.append(k, v);
    summary.appendChild(item);
  }

  if (noiseBtn) {
    noiseBtn.disabled = !noiseIds.length;
    noiseBtn.textContent = noiseIds.length ? `一键关闭噪音（${noiseIds.length}）` : "一键关闭噪音";
  }
  if (allBtn) {
    allBtn.disabled = !openIds.length;
    allBtn.textContent = openIds.length ? `关闭全部开放（${openIds.length}）` : "关闭全部开放";
  }

  body.innerHTML = "";
  if (!groups.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "没有可汇总的开放告警。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

  for (const group of groups) {
    const tr = document.createElement("tr");
    const kindTone =
      group.kind === "actionable" || group.kind === "dup"
        ? group.level === "critical"
          ? "block"
          : "warn"
        : group.kind === "stale"
          ? "accent"
          : "muted";
    appendCell(tr, ALERT_KIND_LABEL[group.kind] || group.kind || "-", { tone: kindTone });
    appendCell(tr, ALERT_LEVEL_LABEL[group.level] || group.level || "-", {
      tone: group.level === "critical" ? "block" : group.level === "high" ? "warn" : "muted",
    });
    appendCell(
      tr,
      `${ALERT_CATEGORY_LABEL[group.category] || group.category || "-"} · ${ALERT_TITLE_LABEL[group.title] || group.title || "-"}`,
    );
    appendCell(tr, String(group.count ?? 0), { className: "num" });
    appendCell(tr, group.advice || "-");
    const td = document.createElement("td");
    const wrap = document.createElement("div");
    wrap.className = "alert-intel-actions";
    if ((group.noise_ids || []).length) {
      const noise = document.createElement("button");
      noise.type = "button";
      noise.className = "secondary";
      noise.textContent = `关重复 ${group.noise_ids.length}`;
      noise.addEventListener("click", async () => {
        noise.disabled = true;
        try {
          const ok = await closeAlertIds(group.noise_ids, "close duplicate noise", {
            level: group.level,
            label: ALERT_TITLE_LABEL[group.title] || group.title,
          });
          if (!ok) {
            noise.disabled = false;
          }
        } catch (error) {
          showToast(error.message || "关闭失败", "warn");
          noise.disabled = false;
        }
      });
      wrap.appendChild(noise);
    }
    const closeGroup = document.createElement("button");
    closeGroup.type = "button";
    closeGroup.className = "secondary";
    closeGroup.textContent = "关闭本组";
    closeGroup.addEventListener("click", async () => {
      closeGroup.disabled = true;
      try {
        const ok = await closeAlertIds(group.all_ids, "close alert group", {
          level: group.level,
          label: ALERT_TITLE_LABEL[group.title] || group.title,
        });
        if (!ok) {
          closeGroup.disabled = false;
        }
      } catch (error) {
        showToast(error.message || "关闭失败", "warn");
        closeGroup.disabled = false;
      }
    });
    wrap.appendChild(closeGroup);
    td.appendChild(wrap);
    tr.appendChild(td);
    body.appendChild(tr);
  }
}

async function loadOverviewAlerts() {
  const [rows, analysis] = await Promise.all([
    requestJson("/api/alerts?status=open&limit=100"),
    requestJson("/api/alerts/analysis?limit=200"),
  ]);
  renderOverviewAlerts(rows);
  renderAlertIntel(analysis);
  return rows;
}

function focusOverviewAlerts() {
  const panel = document.getElementById("overview-alerts");
  if (!panel) {
    return;
  }
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  panel.classList.add("panel-flash");
  window.setTimeout(() => panel.classList.remove("panel-flash"), 1200);
}

document.getElementById("alert-close-noise")?.addEventListener("click", async () => {
  const ids = alertIntelState.noise_ids || [];
  const hasHigh = (alertIntelState.groups || []).some(
    (group) => (group.noise_ids || []).length && alertNeedsConfirm(group.level),
  );
  try {
    await closeAlertIds(ids, "one-click close noise", {
      level: hasHigh ? "critical" : "info",
      label: "重复/过期噪音",
    });
  } catch (error) {
    showToast(error.message || "关闭失败", "warn");
  }
});

document.getElementById("overview-alert-body")?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-close-alert]");
  if (button) {
    const alertId = button.dataset.closeAlert || "";
    const row = button.closest("tr.alert-row");
    button.disabled = true;
    try {
      const ok = await closeAlertIds([alertId], "closed from overview", {
        level: row?.dataset.alertLevel || "info",
        label: row?.dataset.alertTitle || "",
      });
      if (!ok) {
        button.disabled = false;
      }
    } catch (error) {
      showToast(error.message || "关闭失败", "warn");
      button.disabled = false;
    }
    return;
  }
  const row = event.target.closest("tr.alert-row");
  if (!row) {
    return;
  }
  const alertId = row.dataset.alertId || "";
  alertListState.expandedId = alertListState.expandedId === alertId ? "" : alertId;
  syncAlertRowExpansion();
});

document.getElementById("alert-close-all")?.addEventListener("click", async () => {
  const ids = alertIntelState.open_ids || [];
  const hasHigh = (alertIntelState.groups || []).some((group) => alertNeedsConfirm(group.level));
  try {
    await closeAlertIds(ids, "one-click close all open", {
      level: hasHigh ? "critical" : "info",
      label: "全部开放告警",
    });
  } catch (error) {
    showToast(error.message || "关闭失败", "warn");
  }
});

function showPage(page) {
  document.querySelectorAll(".page").forEach((section) => {
    section.classList.toggle("hidden", section.id !== `page-${page}`);
  });
  document.querySelectorAll("#nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === page);
  });
  setText("page-title", PAGE_TITLES[page]);
  if (page === "overview") {
    loadOverviewAlerts().catch(() => {});
    if ((location.hash || "").includes("overview-alerts")) {
      window.setTimeout(focusOverviewAlerts, 80);
    }
  }
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
      setText("paper-account-hint", `加载失败：${error.message}`);
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
  if (page === "settings") {
    loadPaperTradingSwitch().catch(() => {});
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

  setText("runtime", health.status === "ok" ? "运行正常 · 本地模拟盘已接" : "运行异常");
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
    Number(status.open_alerts) > 0 ? "点击查看下方告警列表" : "当前无开放告警",
  );
  document.querySelector(".metrics")?.classList.remove("is-loading");
  renderTasks(status.recent_tasks || []);
  renderSources(sources);
  renderPorts(ports);
  await loadOverviewAlerts().catch(() => {});
  if ((location.hash || "").includes("overview-alerts")) {
    window.setTimeout(focusOverviewAlerts, 80);
  }
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

const TOAST_HOLD_MS = 5000;
let confirmResolver = null;

function closeConfirmDialog(ok) {
  const mask = document.getElementById("confirm-dialog");
  if (mask) {
    mask.hidden = true;
  }
  const resolve = confirmResolver;
  confirmResolver = null;
  if (resolve) {
    resolve(Boolean(ok));
  }
}

function confirmDialog(message) {
  const mask = document.getElementById("confirm-dialog");
  const text = document.getElementById("confirm-message");
  const okBtn = document.getElementById("confirm-ok");
  if (!mask || !text) {
    return Promise.resolve(window.confirm(message));
  }
  if (confirmResolver) {
    closeConfirmDialog(false);
  }
  text.textContent = message;
  mask.hidden = false;
  okBtn?.focus();
  return new Promise((resolve) => {
    confirmResolver = resolve;
  });
}

document.getElementById("confirm-ok")?.addEventListener("click", () => closeConfirmDialog(true));
document.getElementById("confirm-cancel")?.addEventListener("click", () => closeConfirmDialog(false));
document.getElementById("confirm-close")?.addEventListener("click", () => closeConfirmDialog(false));
document.getElementById("confirm-dialog")?.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    closeConfirmDialog(false);
  }
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && confirmResolver) {
    closeConfirmDialog(false);
  }
});

function showToast(message, tone) {
  const host = document.getElementById("toast-host");
  if (!host || !message) {
    return;
  }
  const el = document.createElement("div");
  el.className = "toast";
  el.dataset.tone = tone || "ok";
  el.textContent = message;
  let timer = 0;
  const dismiss = () => {
    window.clearTimeout(timer);
    timer = 0;
    el.remove();
  };
  const arm = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(dismiss, TOAST_HOLD_MS);
  };
  el.addEventListener("mouseenter", () => {
    window.clearTimeout(timer);
    timer = 0;
  });
  el.addEventListener("mouseleave", arm);
  host.prepend(el);
  arm();
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
  syncInFlight = Boolean(busy);
  const btn = document.getElementById("sync-now");
  if (!btn) {
    return;
  }
  if (busy) {
    btn.disabled = true;
    btn.setAttribute("aria-disabled", "true");
    btn.setAttribute("aria-busy", "true");
    btn.setAttribute("aria-readonly", "true");
    btn.title = label || "正在追加，请稍候";
    btn.textContent = label || "追加中…";
    return;
  }
  btn.setAttribute("aria-busy", "false");
  refreshHeaderActionLocks();
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
  const deadline = scheduler.deadline || "18:00";
  const cron = scheduler.cron || "20:05";
  const tz = scheduler.timezone || "Asia/Shanghai";
  const reconcile = scheduler.reconcile || {};
  const reconcileWindow = reconcile.window || "19:15";
  const reconcileNext = reconcile.next_at ? formatDateTime(reconcile.next_at, false) : "-";
  const reconcileTimeout = reconcile.timeout_s ? `${reconcile.timeout_s}s` : "900s";
  const cash = scheduler.cash_reconcile || {};
  const cashWindow = cash.window || "19:45";
  const cashNext = cash.next_at ? formatDateTime(cash.next_at, false) : "-";
  return (
    `人工点「追加行情」立即异步执行（盘前手工通常只盖到昨日 K）。` +
    `每个交易日 ${window} 起等主源确认当日 K 再质检，${deadline} 起强制重试直到成功（${tz}）；` +
    `上午手工成功不会取消傍晚自动。跨源对账 ${reconcileWindow}（优先 Tushare，超时 ${reconcileTimeout}，下次 ${reconcileNext}）；` +
    `财务对账 ${cashWindow}（下次 ${cashNext}）。` +
    `进程外 cron 兜底 ${cron}。下次进程内同步 ${next}。`
  );
}

function syncOpsHint(scheduler) {
  const parts = [];
  if (scheduler.morning_manual_note) {
    parts.push(scheduler.morning_manual_note);
  }
  const cron = scheduler.cron_installed || {};
  if (cron.checked) {
    parts.push(cron.installed ? "当前用户 crontab 已装（含兜底脚本）。" : cron.detail || "当前用户未装 crontab。");
  }
  if (scheduler.hot_reload_note) {
    parts.push(scheduler.hot_reload_note);
  }
  if (scheduler.lock_note) {
    parts.push(scheduler.lock_note);
  }
  return parts.join(" ");
}

function applySchedulerHints(scheduler) {
  if (!scheduler) {
    return;
  }
  setText("sync-scheduler-hint", syncSchedulerHint(scheduler));
  const ops = document.getElementById("sync-ops-hint");
  if (ops) {
    const text = syncOpsHint(scheduler);
    ops.hidden = !text;
    ops.textContent = text;
  }
}

async function resumeActiveSync() {
  try {
    const payload = await requestJson("/api/sync/active");
    if (payload.active && payload.active.run_id) {
      watchSyncRun(payload.active.run_id);
    }
    if (payload.scheduler) {
      applySchedulerHints(payload.scheduler);
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
    applySchedulerHints(payload.scheduler);
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
  document.querySelector(".overview-alerts-row")?.classList.toggle("tasks-collapsed", collapsed);
  document.querySelector(".overview-workbench")?.classList.toggle("tasks-collapsed", collapsed);
  localStorage.setItem("asqt-tasks", collapsed ? "1" : "0");
  const btn = document.getElementById("tasks-toggle");
  if (btn) {
    btn.textContent = collapsed ? "⟨" : "⟩";
    btn.setAttribute("aria-label", collapsed ? "展开任务" : "收起任务");
  }
}

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  applySidebar(!document.querySelector(".shell")?.classList.contains("sidebar-collapsed"));
});

document.getElementById("tasks-toggle").addEventListener("click", () => {
  const row = document.querySelector(".overview-alerts-row") || document.querySelector(".overview-workbench");
  applyTasks(!row?.classList.contains("tasks-collapsed"));
});

const TRADE_PAGE_SIZE = 10;
const tradePages = { daily: 1, positions: 1, fills: 1, orders: 1, mock: 1 };
const tradeLists = { positions: [], fills: [], orders: [], mock: [] };

function tradePageSlice(rows, page) {
  const list = rows || [];
  const total = list.length;
  const pages = Math.max(1, Math.ceil(total / TRADE_PAGE_SIZE) || 1);
  const safe = Math.min(Math.max(1, Number(page) || 1), pages);
  const start = (safe - 1) * TRADE_PAGE_SIZE;
  return { page: safe, pages, total, start, items: list.slice(start, start + TRADE_PAGE_SIZE) };
}

function paintTradePager(prefix, info) {
  setText(
    `${prefix}-page-label`,
    info.total ? `${info.page} / ${info.pages} · 共 ${info.total} 条 · 每页 ${TRADE_PAGE_SIZE}` : "共 0 条",
  );
  const prev = document.getElementById(`${prefix}-prev`);
  const next = document.getElementById(`${prefix}-next`);
  if (prev) {
    prev.disabled = info.page <= 1 || info.total === 0;
  }
  if (next) {
    next.disabled = info.page >= info.pages || info.total === 0;
  }
}

function bindTradePager(prefix, key, redraw) {
  document.getElementById(`${prefix}-prev`)?.addEventListener("click", () => {
    tradePages[key] -= 1;
    redraw();
  });
  document.getElementById(`${prefix}-next`)?.addEventListener("click", () => {
    tradePages[key] += 1;
    redraw();
  });
}

function renderOrders(rows, bodyId = "order-body") {
  const body = document.getElementById(bodyId);
  if (!body) {
    return;
  }
  const pagerId = bodyId === "mock-order-body" ? "mock-order" : "paper-order";
  if (bodyId === "mock-order-body") {
    tradeLists.mock = rows.slice();
  } else {
    tradeLists.orders = rows.slice();
  }
  const pageKey = bodyId === "mock-order-body" ? "mock" : "orders";
  const info = tradePageSlice(tradeLists[pageKey], tradePages[pageKey]);
  tradePages[pageKey] = info.page;
  body.innerHTML = "";
  if (!info.total) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = bodyId === "order-body" ? 8 : 7;
    td.className = "table-empty";
    td.textContent = "还没有订单。";
    tr.appendChild(td);
    body.appendChild(tr);
    paintTradePager(pagerId, info);
    return;
  }
  info.items.forEach((row, index) => {
    const tr = document.createElement("tr");
    appendCell(tr, String(info.start + index + 1), { className: "num" });
    appendCell(tr, formatDateTime(row.created_at) || "-");
    if (bodyId === "order-body") {
      appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id || "-");
    }
    appendCell(tr, row.symbol || "-");
    appendCell(tr, row.side === "SELL" ? "卖出" : row.side === "BUY" ? "买入" : row.side || "-");
    appendCell(tr, row.quantity == null ? "-" : String(row.quantity));
    appendCell(tr, ORDER_STATUS_LABEL[row.status] || row.status || "-", { tone: toneForOrder(row.status) });
    appendCell(tr, formatRiskTags(row.risk_tags));
    body.appendChild(tr);
  });
  paintTradePager(pagerId, info);
}

const STRATEGY_LABEL = {
  etf_ma_rotate: "ETF 均线轮动",
  stock_momentum_topk: "股票动量 TopK",
  etf_momentum_topk: "ETF 动量 TopK",
  stock_lowvol_momentum: "股票低波动量",
  etf_ma_momentum_filter: "ETF 均线动量过滤",
};

const PARAM_LABEL = {
  lookback: "回看天数",
  top_k: "选取数量",
  max_weight: "单票上限",
  gross_limit: "总仓上限",
  window: "均线窗口",
  vol_window: "波动窗口",
  ma_window: "均线窗口",
  mom_lookback: "动量回看",
};

const PARAM_PCT_KEYS = new Set(["max_weight", "gross_limit"]);

/** 与后端 STRATEGY_SPECS.params 对齐；策略页无 params 字段时用此展示。 */
const STRATEGY_PARAMS = {
  etf_ma_rotate: { window: 20, max_weight: 0.2, gross_limit: 0.95 },
  stock_momentum_topk: { lookback: 20, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  etf_momentum_topk: { lookback: 40, top_k: 3, max_weight: 0.2, gross_limit: 0.95 },
  stock_lowvol_momentum: { lookback: 20, vol_window: 20, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  etf_ma_momentum_filter: { ma_window: 20, mom_lookback: 40, top_k: 3, max_weight: 0.2, gross_limit: 0.95 },
};

function formatParamValue(key, value) {
  if (PARAM_PCT_KEYS.has(key) && value != null && value !== "") {
    const number = Number(value);
    if (!Number.isNaN(number)) {
      const pct = number * 100;
      const text = Number.isInteger(pct) ? String(pct) : pct.toFixed(2).replace(/\.?0+$/, "");
      return `${text}%`;
    }
  }
  return String(value);
}

function formatParamsChinese(params, fallbackId) {
  if (params && typeof params === "object" && Object.keys(params).length) {
    return Object.entries(params)
      .map(([key, value]) => `${PARAM_LABEL[key] || key}=${formatParamValue(key, value)}`)
      .join(" · ");
  }
  return fallbackId || "-";
}

function formatParameterSetDisplay(row) {
  const params = row?.params || STRATEGY_PARAMS[row?.strategy_id];
  return formatParamsChinese(params, row?.parameter_set_id);
}
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

function formatMoney(value) {
  if (value == null || value === "") {
    return "-";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "-";
  }
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pnlClass(value) {
  const number = Number(value);
  if (Number.isNaN(number) || number === 0) {
    return "num";
  }
  return number < 0 ? "num chg-down" : "num chg-up";
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
    appendCell(tr, formatParameterSetDisplay(row));
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
    td.colSpan = 7;
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
    const isDays = row.metrics?.is?.n_days;
    const oosDays = row.metrics?.oos?.n_days;
    appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id);
    appendCell(tr, STRATEGY_STATUS_LABEL[row.status] || row.status || "-", { tone: toneForStrategy(row.status) });
    appendCell(tr, formatPct(isRet));
    appendCell(tr, formatPct(oosRet));
    appendCell(tr, formatPct(oosDd));
    appendCell(
      tr,
      isDays != null || oosDays != null ? `${isDays ?? "-"} / ${oosDays ?? "-"}` : "-",
      { className: "num" },
    );
    appendCell(tr, row.data_version || "-");
    body.appendChild(tr);
  }
}

async function loadStrategyPage() {
  const [versions, experiments, kill] = await Promise.all([
    requestJson("/api/strategies"),
    requestJson("/api/research/experiments"),
    requestJson("/api/ops/kill-switch").catch(() => ({ engaged: false })),
  ]);
  renderStrategyVersions(versions);
  renderExperiments(experiments);
  const gate = document.getElementById("strategy-gate-hint");
  if (gate) {
    if (kill?.engaged) {
      const reason = kill.reason ? ` 当前原因：${kill.reason}` : "";
      gate.hidden = false;
      gate.textContent = `急停已打开，不能准入或恢复模拟。请先到交易页关闭急停后再试。${reason}`;
    } else {
      gate.hidden = true;
      gate.textContent = "";
    }
  }
}

function renderAttribution(payload) {
  const body = document.getElementById("review-body");
  const summary = document.getElementById("review-summary");
  const isoos = document.getElementById("review-isoos");
  const paperBody = document.getElementById("review-paper-body");
  if (!body || !summary) {
    return;
  }
  summary.innerHTML = "";
  if (isoos) {
    isoos.innerHTML = "";
  }
  if (paperBody) {
    paperBody.innerHTML = "";
  }
  const paper = payload.paper_vs_backtest || {};
  const sample = payload.sample || {};
  const params = payload.params || STRATEGY_PARAMS[payload.strategy_id] || {};
  const paramText = formatParamsChinese(params, payload.parameter_set_id);
  const entries = payload.ok
    ? [
        ["净值", Number(payload.nav || 0).toFixed(4)],
        ["复利收益", formatPct(payload.total_return)],
        ["累加贡献", formatPct(payload.additive_return)],
        ["参数组", paramText],
        ["样本区间", sample.start && sample.end ? `${sample.start} ~ ${sample.end}（${sample.n_sessions || "-"} 日）` : "-"],
        ["模拟偏差", paper.available ? formatPct(paper.items?.[0]?.max_abs_nav_gap) : "尚无模拟成交"],
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
  if (isoos && payload.ok) {
    const isoosEntries = [
      ["样本内截止", payload.in_sample_end || "-"],
      ["样本内天数", payload.is_days == null ? "-" : String(payload.is_days)],
      ["样本外天数", payload.oos_days == null ? "-" : String(payload.oos_days)],
      ["样本内贡献", formatPct(payload.is_contribution)],
      ["样本外贡献", formatPct(payload.oos_contribution)],
      ["样本内占比", payload.is_share == null ? "-" : formatPct(payload.is_share)],
      ["样本外占比", payload.oos_share == null ? "-" : formatPct(payload.oos_share)],
      [
        "样本外 Top",
        (payload.top_oos || [])
          .slice(0, 3)
          .map((row) => `${row.symbol} ${formatPct(row.oos_contribution)}`)
          .join(" · ") || "-",
      ],
      [
        "样本外拖累",
        (payload.bottom_oos || [])
          .slice(0, 3)
          .map((row) => `${row.symbol} ${formatPct(row.oos_contribution)}`)
          .join(" · ") || "-",
      ],
    ];
    for (const [label, value] of isoosEntries) {
      const item = document.createElement("div");
      item.className = "kv-item";
      const k = document.createElement("span");
      const v = document.createElement("strong");
      k.textContent = label;
      v.textContent = value;
      item.append(k, v);
      isoos.appendChild(item);
    }
  }
  if (paperBody) {
    const items = paper.available ? paper.items || [] : [];
    if (!items.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "table-empty";
      td.textContent = paper.detail || "尚无模拟成交，无法对比。";
      tr.appendChild(td);
      paperBody.appendChild(tr);
    } else {
      for (const row of items) {
        const tr = document.createElement("tr");
        appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id);
        appendCell(tr, String(row.n_days ?? "-"), { className: "num" });
        appendCell(tr, formatPct(row.paper_return), { className: pnlClass(row.paper_return) });
        appendCell(tr, formatPct(row.backtest_return), { className: pnlClass(row.backtest_return) });
        appendCell(tr, formatPct(row.max_abs_nav_gap), { className: "num" });
        paperBody.appendChild(tr);
      }
    }
  }
  setText(
    "review-hint",
    paper.available
      ? `按标的累加每日贡献。样本内/外已切开；模拟 vs 回测最大净值偏离 ${formatPct(paper.items?.[0]?.max_abs_nav_gap)}。`
      : "按标的累加每日贡献。样本内/外按时间切开；模拟 vs 回测偏差要等 PaperBroker 成交后才能算。",
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
  setText("review-hint", "正在按日重算归因，请稍候…");
  const payload = await requestJson(`/api/research/attribution?strategy_id=${encodeURIComponent(strategyId)}`);
  renderAttribution(payload);
}

let backtestTimer = 0;
let watchedBacktestId = "";
let backtestBusy = false;
let paperBusy = false;
let syncInFlight = false;

function setControlReadonly(el, on, title) {
  if (!el) {
    return;
  }
  el.disabled = Boolean(on);
  el.setAttribute("aria-disabled", on ? "true" : "false");
  el.setAttribute("aria-readonly", on ? "true" : "false");
  if (on) {
    el.title = title || "回测进行中，请稍候";
  } else if (el.title === "回测进行中，请稍候") {
    el.title = "";
  }
}

function lockSelectTriggers(root, on) {
  if (!root) {
    return;
  }
  root.querySelectorAll(".asqt-select-trigger").forEach((btn) => {
    setControlReadonly(btn, on);
  });
}

function refreshHeaderActionLocks() {
  const btn = document.getElementById("sync-now");
  if (!btn) {
    return;
  }
  if (syncInFlight) {
    return;
  }
  const lock = backtestBusy || paperBusy;
  btn.disabled = lock;
  btn.setAttribute("aria-disabled", lock ? "true" : "false");
  btn.setAttribute("aria-readonly", lock ? "true" : "false");
  btn.textContent = SYNC_NOW_IDLE;
  btn.title = paperBusy ? "模拟盘运行中，请稍候" : lock ? "回测进行中，请稍候" : SYNC_NOW_IDLE;
}

function applyTradeLocks() {
  const locked = backtestBusy || paperBusy;
  const lockTitle = paperBusy ? "模拟盘运行中，请勿重复提交" : backtestBusy ? "回测进行中，请稍候" : "";
  const runBtn = document.getElementById("paper-run-submit");
  setControlReadonly(document.getElementById("strategy-run"), locked, lockTitle);
  setControlReadonly(document.getElementById("bootstrap"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-life-submit"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-life-reason"), locked, lockTitle);
  setControlReadonly(runBtn, locked, lockTitle);
  if (runBtn && !backtestBusy) {
    runBtn.textContent = paperBusy ? "运行中…" : "跑模拟";
  }
  setControlReadonly(document.getElementById("paper-reset"), locked, lockTitle);
  setControlReadonly(document.getElementById("paper-run-days"), paperBusy, lockTitle);
  lockSelectTriggers(document.getElementById("paper-run-form"), locked);
  lockSelectTriggers(document.getElementById("strategy-run-form"), locked);
  lockSelectTriggers(document.getElementById("strategy-life-form"), locked);
  refreshHeaderActionLocks();
}

function setBacktestBusy(busy) {
  backtestBusy = Boolean(busy);
  applyTradeLocks();
}

function setPaperBusy(busy) {
  paperBusy = Boolean(busy);
  applyTradeLocks();
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

const strategyLifeForm = document.getElementById("strategy-life-form");
if (strategyLifeForm) {
  strategyLifeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const result = document.getElementById("strategy-life-result");
    const strategyId = document.getElementById("strategy-life-id").value;
    const action = document.getElementById("strategy-life-action").value;
    const reason = document.getElementById("strategy-life-reason").value.trim();
    if (result) {
      result.hidden = false;
      result.textContent = "提交中…";
    }
    try {
      const payload = await requestJson(`/api/strategies/${encodeURIComponent(strategyId)}/lifecycle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reason }),
      });
      if (result) {
        result.textContent = `${STRATEGY_LABEL[payload.strategy_id] || payload.strategy_id} → ${STRATEGY_STATUS_LABEL[payload.status] || payload.status}`;
      }
      showToast("生命周期已更新", "ok");
      await loadStrategyPage();
    } catch (error) {
      if (result) {
        result.textContent = `失败：${error.message}`;
      }
      showToast(error.message || "生命周期失败", "block");
    }
  });
}

const paperRunId = document.getElementById("paper-run-id");
if (paperRunId) {
  paperRunId.addEventListener("change", () => {
    loadOrders().catch((error) => showToast(error.message || "加载模拟账户失败", "block"));
  });
}

let paperRunTimer = 0;
let watchedPaperRunId = "";

function paperProgressText(row) {
  const pct = row.progress_pct == null || row.progress_pct === "" ? "" : `${Number(row.progress_pct)}%`;
  const label = row.progress_label || "";
  if (row.status === "queued") {
    return pct ? `模拟排队 ${pct}` : "模拟已入队";
  }
  if (row.status === "running") {
    return `模拟盘运行中 ${pct || ""}${label ? ` · ${label}` : ""}`.replace(/\s+/g, " ").trim();
  }
  if (row.status === "success") {
    return (row.detail && row.detail.detail) || label || "模拟已跑完";
  }
  return row.fail_reason || (row.detail && row.detail.detail) || label || "模拟未完整";
}

function finishPaperWatch(row) {
  const detail = row.detail || {};
  const ok = row.status === "success" && detail.ok !== false;
  const partial = row.status === "partial";
  const message = paperProgressText(row);
  setText("paper-account-hint", message);
  showToast(ok ? "模拟已跑完" : message || "模拟未完整", ok ? "ok" : partial ? "warn" : "block");
  loadOrders().catch(() => {});
}

function watchPaperRun(runId) {
  watchedPaperRunId = runId;
  window.clearInterval(paperRunTimer);
  setPaperBusy(true);
  setText("paper-account-hint", "模拟已入队…请勿重复提交。");
  const tick = () => {
    requestJson(`/api/paper/run/${runId}`)
      .then((row) => {
        if (runId !== watchedPaperRunId) {
          return;
        }
        setText("paper-account-hint", paperProgressText(row));
        const runBtn = document.getElementById("paper-run-submit");
        if (runBtn && paperBusy) {
          const pct = row.progress_pct == null ? "" : ` ${row.progress_pct}%`;
          runBtn.textContent = row.status === "queued" ? "排队中…" : `运行中…${pct}`;
        }
        if (row.status === "success" || row.status === "failed" || row.status === "partial") {
          window.clearInterval(paperRunTimer);
          paperRunTimer = 0;
          watchedPaperRunId = "";
          setPaperBusy(false);
          finishPaperWatch(row);
        }
      })
      .catch((error) => {
        window.clearInterval(paperRunTimer);
        paperRunTimer = 0;
        watchedPaperRunId = "";
        setPaperBusy(false);
        setText("paper-account-hint", `模拟失败：${error.message}`);
        showToast(error.message || "模拟失败", "block");
      });
  };
  tick();
  paperRunTimer = window.setInterval(tick, 1000);
}

async function resumeActivePaperRun() {
  try {
    const payload = await requestJson("/api/paper/run/active");
    if (payload.active && payload.active.run_id) {
      watchPaperRun(payload.active.run_id);
    }
  } catch (_err) {
    /* ignore */
  }
}

const paperRunForm = document.getElementById("paper-run-form");
if (paperRunForm) {
  paperRunForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (paperBusy || backtestBusy) {
      showToast("模拟盘运行中，请勿重复提交", "warn");
      return;
    }
    setPaperBusy(true);
    setText("paper-account-hint", "模拟盘入队中…请勿重复提交。");
    try {
      const payload = await requestJson("/api/paper/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: document.getElementById("paper-run-id").value,
          days: Math.min(240, Math.max(2, Number(document.getElementById("paper-run-days").value) || 20)),
        }),
      });
      showToast("模拟已在后台开始", "ok");
      watchPaperRun(payload.run_id);
    } catch (error) {
      setPaperBusy(false);
      setText("paper-account-hint", `模拟失败：${error.message}`);
      showToast(error.message || "模拟失败", "block");
    }
  });
}

const paperResetBtn = document.getElementById("paper-reset");
if (paperResetBtn) {
  paperResetBtn.addEventListener("click", async () => {
    if (paperBusy || backtestBusy) {
      showToast(paperBusy ? "模拟盘运行中，请勿重复提交" : "回测进行中，请稍候", "warn");
      return;
    }
    const strategyId = document.getElementById("paper-run-id")?.value || "all";
    let cash = Number(lastPaperConfig?.initial_cash) || 1000000;
    try {
      lastPaperConfig = await requestJson("/api/ops/paper-config");
      cash = Number(lastPaperConfig.initial_cash) || cash;
    } catch {
      /* keep last known */
    }
    const ok = await confirmDialog(
      `重置模拟账户数据后，所选策略的持仓、成交、快照和模拟订单将清空并回到本金 ${formatMoney(cash)}，此操作不可撤销。是否确定重置？`,
    );
    if (!ok) {
      return;
    }
    setControlReadonly(paperResetBtn, true);
    try {
      const payload = await requestJson("/api/paper/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: strategyId }),
      });
      const deleted = (payload.reports || []).reduce(
        (sum, item) => sum + Number(item.deleted_snapshots || 0) + Number(item.deleted_orders || 0),
        0,
      );
      showToast(deleted ? "模拟账户已重置" : "没有可清空的模拟数据", "ok");
      await loadOrders();
    } catch (error) {
      showToast(error.message || "重置失败", "block");
    } finally {
      if (!backtestBusy && !paperBusy) {
        setControlReadonly(paperResetBtn, false);
      }
    }
  });
}

const killSwitchForm = document.getElementById("kill-switch-form");
if (killSwitchForm) {
  const killReason = document.getElementById("kill-reason");
  const killReasonError = document.getElementById("kill-reason-error");
  const KILL_REASON_HINT = "请填写原因（不能全是空格）";

  function showKillReasonError(message) {
    if (killReasonError) {
      killReasonError.hidden = !message;
      killReasonError.textContent = message || "";
    }
    if (killReason) {
      killReason.setCustomValidity(message || "");
      killReason.classList.toggle("is-invalid", Boolean(message));
    }
  }

  function validateKillReason() {
    const value = (killReason?.value || "").trim();
    if (!value) {
      showKillReasonError(KILL_REASON_HINT);
      return false;
    }
    showKillReasonError("");
    return true;
  }

  killReason?.addEventListener("input", () => {
    if (killReasonError && !killReasonError.hidden) {
      validateKillReason();
    } else if (killReason) {
      killReason.setCustomValidity("");
      killReason.classList.remove("is-invalid");
    }
  });

  killSwitchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateKillReason()) {
      killReason?.focus();
      killReason?.reportValidity();
      return;
    }
    try {
      const payload = await requestJson("/api/ops/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          engaged: document.getElementById("kill-engaged").value === "on",
          reason: killReason.value.trim(),
        }),
      });
      showKillReasonError("");
      killReason.value = "";
      showToast(payload.engaged ? "急停已开" : "急停已关", payload.engaged ? "block" : "ok");
      await loadOrders();
    } catch (error) {
      const message = error.message || "急停失败";
      if (/reason|原因/i.test(message)) {
        showKillReasonError(KILL_REASON_HINT);
        killReason?.focus();
        killReason?.reportValidity();
        return;
      }
      showToast(message, "block");
    }
  });
}

let lastPaperConfig = { initial_cash: 1000000, commission_per_myriad: 2.5 };

async function loadPaperTradingSwitch() {
  const [gate, config] = await Promise.all([
    requestJson("/api/ops/paper-trading"),
    requestJson("/api/ops/paper-config"),
  ]);
  lastPaperConfig = config;
  const select = document.getElementById("paper-trading-enabled");
  if (select) {
    select.value = gate.enabled ? "on" : "off";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }
  const cash = document.getElementById("paper-initial-cash");
  if (cash && config.initial_cash != null) {
    cash.value = String(config.initial_cash);
  }
  const wan = document.getElementById("paper-commission-wan");
  if (wan && config.commission_per_myriad != null) {
    wan.value = String(config.commission_per_myriad);
  }
  setText(
    "paper-trading-hint",
    gate.enabled
      ? `模拟交易已开。初始资金 ${formatMoney(config.initial_cash)}，佣金万分之 ${config.commission_per_myriad}。策略准入后可跑模拟；急停打开时仍会拒单。已有账本请先重置再跑。`
      : "开关为关时不能跑模拟。急停打开时也会拒绝新订单。初始资金与佣金对之后新开的模拟生效。",
  );
}

const paperTradingForm = document.getElementById("paper-trading-form");
if (paperTradingForm) {
  paperTradingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const enabled = document.getElementById("paper-trading-enabled").value === "on";
      await requestJson("/api/ops/paper-trading", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          reason: "settings",
        }),
      });
      await requestJson("/api/ops/paper-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initial_cash: Number(document.getElementById("paper-initial-cash").value) || 1000000,
          commission_per_myriad: Number(document.getElementById("paper-commission-wan").value),
        }),
      });
      showToast("模拟交易设置已保存", "ok");
      await loadPaperTradingSwitch();
    } catch (error) {
      showToast(error.message || "保存失败", "block");
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
  const strategyId = document.getElementById("paper-run-id")?.value || "stock_momentum_topk";
  const ids = strategyId === "all" ? Object.keys(STRATEGY_LABEL) : [strategyId];
  const [mockRows, kill, paperGate, ...accounts] = await Promise.all([
    requestJson("/api/orders?limit=200"),
    requestJson("/api/ops/kill-switch"),
    requestJson("/api/ops/paper-trading"),
    ...ids.map((id) => requestJson(`/api/paper/account?strategy_id=${encodeURIComponent(id)}`)),
  ]);
  paperKillState = kill;
  paperGateState = paperGate;
  paperBooks = {};
  for (const account of accounts) {
    if (account?.strategy_id) {
      paperBooks[account.strategy_id] = account;
    }
  }
  if (!paperFocusId || !paperBooks[paperFocusId]) {
    paperFocusId = ids[0];
  }
  renderOrders(mockRows, "mock-order-body");
  await showPaperFocus();
}

let paperBooks = {};
let paperFocusId = null;
let paperKillState = null;
let paperGateState = null;

function renderPaperGates(kill, paperGate, account, multi) {
  const summary = document.getElementById("paper-summary");
  if (!summary) {
    return;
  }
  summary.innerHTML = "";
  const gates = [
    ["模拟交易", paperGate?.enabled ? "开" : "关"],
    ["急停", kill?.engaged ? "开" : "关"],
  ];
  if (!multi && account) {
    gates.push(["账户", "独立模拟账户"]);
    gates.push(["策略", STRATEGY_LABEL[account.strategy_id] || account.strategy_id || "-"]);
  }
  for (const [label, value] of gates) {
    const item = document.createElement("div");
    item.className = "kv-item";
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = value;
    item.append(k, v);
    summary.appendChild(item);
  }
}

function renderPaperBookSwitcher(ids) {
  const host = document.getElementById("paper-books");
  if (!host) {
    return;
  }
  host.hidden = ids.length < 2;
  host.innerHTML = "";
  if (ids.length < 2) {
    return;
  }
  for (const id of ids) {
    const account = paperBooks[id];
    const board = account?.summary || {};
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `paper-book${id === paperFocusId ? " is-active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = STRATEGY_LABEL[id] || id;
    const acc = document.createElement("span");
    acc.className = "paper-book-id";
    acc.textContent = "独立模拟账户";
    const meta = document.createElement("span");
    meta.className = "paper-book-meta";
    if (board.sessions) {
      const ret = document.createElement("em");
      ret.className = pnlClass(board.total_return);
      ret.textContent = formatPct(board.total_return);
      meta.append(
        document.createTextNode(`${board.sessions} 日 · ${formatMoney(board.end_asset)} · `),
        ret,
      );
    } else {
      meta.textContent = "还没有快照";
    }
    btn.append(title, acc, meta);
    btn.addEventListener("click", () => {
      if (paperFocusId === id) {
        return;
      }
      paperFocusId = id;
      showPaperFocus().catch((error) => showToast(error.message || "切换账户失败", "block"));
    });
    host.appendChild(btn);
  }
}

async function showPaperFocus() {
  const ids = Object.keys(STRATEGY_LABEL).filter((id) => paperBooks[id]);
  const account = paperBooks[paperFocusId];
  const multi = ids.length > 1;
  renderPaperGates(paperKillState, paperGateState, account, multi);
  renderPaperBookSwitcher(ids);
  renderPaperCompare(ids);
  if (!account) {
    return;
  }
  renderPaperAccount(account, paperKillState, paperGateState, multi);
  const paperRows = await requestJson(
    `/api/paper/orders?limit=2000&strategy_id=${encodeURIComponent(paperFocusId)}`,
  );
  renderOrders(paperRows, "order-body");
}

function renderPaperCompare(ids) {
  const title = document.getElementById("paper-compare-title");
  const wrap = document.getElementById("paper-compare-wrap");
  const body = document.getElementById("paper-compare-body");
  if (!title || !wrap || !body) {
    return;
  }
  const show = ids.length > 1;
  title.hidden = !show;
  wrap.hidden = !show;
  body.innerHTML = "";
  if (!show) {
    return;
  }
  for (const id of ids) {
    const account = paperBooks[id];
    const board = account?.summary || {};
    const reconcile = account?.reconcile || {};
    const tr = document.createElement("tr");
    appendCell(tr, STRATEGY_LABEL[id] || id);
    appendCell(tr, board.sessions ? String(board.sessions) : "0", { className: "num" });
    appendCell(tr, board.end_asset == null ? "-" : formatMoney(board.end_asset), { className: "num" });
    appendCell(tr, formatPct(board.total_return), { className: pnlClass(board.total_return) });
    appendCell(tr, formatPct(board.max_drawdown), { className: pnlClass(board.max_drawdown) });
    appendCell(tr, !board.sessions ? "尚无" : reconcile.ok ? "通过" : "不一致", {
      tone: !board.sessions ? "muted" : reconcile.ok ? "ok" : "block",
    });
    body.appendChild(tr);
  }
}

function renderPaperAccount(account, kill, paperGate, multi = false) {
  const body = document.getElementById("paper-curve-body");
  if (!body) {
    return;
  }
  const board = account.summary || {};
  const timeline = account.timeline || [];
  renderPaperBoard(board);
  renderPaperReconcile(account.reconcile || {});
  renderPaperChart(timeline, board);
  paperDailyState.rows = timeline;
  paperDailyState.fillsByDate = groupFillsByDate(account.fills || []);
  paperDailyState.expanded = null;
  tradePages.daily = 1;
  tradePages.positions = 1;
  tradePages.fills = 1;
  tradePages.orders = 1;
  renderPaperDaily();
  if (timeline.length) {
    selectPaperDay(timeline[timeline.length - 1].trade_date, "table");
  }
  renderPaperPositions(account.positions || []);
  renderPaperFills(account.fills || []);
  const windowText = board.window_start && board.window_end
    ? `${board.window_start} ~ ${board.window_end}，共 ${board.sessions || 0} 个交易日`
    : "还没有模拟快照";
  const bookName = STRATEGY_LABEL[account.strategy_id] || account.strategy_id || "当前账户";
  const cashText = formatMoney(board.initial_cash);
  if (!paperGate?.enabled) {
    setText("paper-account-hint", "设置页「模拟交易」为关，跑模拟不会成功。请先到设置打开开关。");
  } else if (kill?.engaged) {
    setText(
      "paper-account-hint",
      multi
        ? `急停已开，禁止新的模拟订单。点选账户查看各自曲线。当前 ${bookName}：${windowText}。`
        : `急停已开，禁止新的模拟订单。当前窗口 ${windowText}。`,
    );
  } else if (multi) {
    setText(
      "paper-account-hint",
      `两本账独立资金、互不占仓。当前查看 ${bookName}：${windowText}。收益相对该账本金 ${cashText}。`,
    );
  } else {
    setText("paper-account-hint", `${windowText}。收益相对本金 ${cashText}；折线与下表可对每日盈亏和成交。`);
  }
}

function renderPaperReconcile(reconcile) {
  const status = document.getElementById("paper-reconcile-status");
  const hint = document.getElementById("paper-reconcile-hint");
  const summary = document.getElementById("paper-reconcile-summary");
  const body = document.getElementById("paper-reconcile-body");
  if (!body) {
    return;
  }
  const checks = reconcile.checks || [];
  const mismatches = reconcile.qty_mismatches || [];
  const hasData = Boolean(checks.length);
  if (status) {
    const asof = reconcile.asof ? ` · 截至 ${reconcile.asof}` : "";
    status.textContent = !hasData
      ? "尚无对账"
      : reconcile.ok
        ? `对账通过${asof}`
        : `对账不一致${asof}`;
    status.className = !hasData ? "" : reconcile.ok ? "ok" : "warn";
  }
  if (hint) {
    hint.textContent = reconcile.formula
      || "期末现金 = 本金 − 买入额 + 卖出额 − 费用；持仓数量 = 各标的买入数量 − 卖出数量。现金不含持仓市值浮盈。";
  }
  if (summary) {
    summary.innerHTML = "";
    const cards = [
      ["对账日", reconcile.asof || "-"],
      ["本金", formatMoney(reconcile.initial_cash)],
      ["账户峰值", formatMoney(reconcile.peak_asset)],
      ["买入额 / 量", `${formatMoney(reconcile.buy_notional)} / ${reconcile.buy_qty ?? 0}`],
      ["卖出额 / 量", `${formatMoney(reconcile.sell_notional)} / ${reconcile.sell_qty ?? 0}`],
      ["费用", formatMoney(reconcile.fees)],
      ["成交推算现金", formatMoney(reconcile.expected_cash)],
      ["账本现金", formatMoney(reconcile.actual_cash)],
      ["现金差额", formatMoney(reconcile.cash_diff), pnlClass(reconcile.cash_diff)],
      ["持仓市值", formatMoney(reconcile.market_value)],
      ["当前总资产", formatMoney(reconcile.end_asset)],
    ];
    for (const [label, value, className] of cards) {
      const item = document.createElement("div");
      item.className = "kv-item";
      const k = document.createElement("span");
      const v = document.createElement("strong");
      k.textContent = label;
      v.textContent = hasData ? value : "-";
      if (className) {
        v.className = className;
      }
      item.append(k, v);
      summary.appendChild(item);
    }
  }
  body.innerHTML = "";
  if (!hasData) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "table-empty";
    td.textContent = "还没有账本可对。跑完模拟后会按成交回推现金和持仓数量。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  const qtyName = (name) => String(name || "").includes("数量");
  const formatValue = (name, value) => (qtyName(name) ? String(Math.round(Number(value) || 0)) : formatMoney(value));
  for (const row of checks) {
    const tr = document.createElement("tr");
    appendCell(tr, row.name || "-");
    appendCell(tr, formatValue(row.name, row.expected), { className: "num" });
    appendCell(tr, formatValue(row.name, row.actual), { className: "num" });
    appendCell(tr, formatValue(row.name, row.diff), { className: pnlClass(row.diff) });
    appendCell(tr, row.ok ? "通过" : "不一致", { tone: row.ok ? "ok" : "warn" });
    body.appendChild(tr);
  }
  for (const row of mismatches) {
    const tr = document.createElement("tr");
    appendCell(tr, `持仓数量 · ${row.symbol}`);
    appendCell(tr, String(row.expected ?? 0), { className: "num" });
    appendCell(tr, String(row.actual ?? 0), { className: "num" });
    appendCell(tr, String(row.diff ?? 0), { className: "num warn" });
    appendCell(tr, "不一致", { tone: "warn" });
    body.appendChild(tr);
  }
}

function renderPaperBoard(board) {
  const host = document.getElementById("paper-board");
  if (!host) {
    return;
  }
  host.innerHTML = "";
  if (!board.sessions) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "还没有模拟快照，跑完连续交易日后这里会给出区间收益、回撤和成交汇总。";
    host.appendChild(empty);
    return;
  }
  const cards = [
    ["区间", `${board.window_start} ~ ${board.window_end}`],
    ["本金", formatMoney(board.initial_cash)],
    ["期末总资产", formatMoney(board.end_asset)],
    ["区间收益", formatPct(board.total_return), pnlClass(board.total_return)],
    ["最大回撤", formatPct(board.max_drawdown), pnlClass(board.max_drawdown)],
    ["现金 / 市值", `${formatMoney(board.cash)} / ${formatMoney(board.market_value)}`],
    ["成交 / 拒单", `${board.orders_filled || 0} / ${board.orders_rejected || 0}`],
    ["买额 / 卖额", `${formatMoney(board.buy_notional)} / ${formatMoney(board.sell_notional)}`],
    ["费用", formatMoney(board.fees)],
    ["持仓只数", String(board.position_count || 0)],
  ];
  for (const [label, value, className] of cards) {
    const item = document.createElement("div");
    item.className = "kv-item";
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = value;
    if (className) {
      v.className = className;
    }
    item.append(k, v);
    host.appendChild(item);
  }
}

let paperChartView = null;

function smoothLinePath(points) {
  if (!points.length) {
    return "";
  }
  if (points.length === 1) {
    return `M ${points[0].x} ${points[0].y}`;
  }
  if (points.length === 2) {
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`;
  }
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x} ${c1y} ${c2x} ${c2y} ${p2.x} ${p2.y}`;
  }
  return d;
}

function formatAxisMoney(value) {
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "-";
  }
  if (Math.abs(number) >= 10000) {
    return `${(number / 10000).toFixed(2)}万`;
  }
  return number.toFixed(0);
}

function shortMd(date) {
  const parts = String(date || "").split("-");
  return parts.length === 3 ? `${parts[1]}-${parts[2]}` : date || "";
}

function xTickIndexes(count) {
  if (count <= 6) {
    return [...Array(count).keys()];
  }
  const step = Math.ceil((count - 1) / 6);
  const indexes = [];
  for (let i = 0; i < count; i += step) {
    indexes.push(i);
  }
  const last = count - 1;
  if (indexes[indexes.length - 1] !== last) {
    if (last - indexes[indexes.length - 1] <= 1) {
      indexes[indexes.length - 1] = last;
    } else {
      indexes.push(last);
    }
  }
  return indexes;
}

function selectPaperDay(date, origin = "hover") {
  if (!paperChartView || !date) {
    return;
  }
  const point = paperChartView.points.find((item) => item.date === date);
  if (!point) {
    return;
  }
  paperChartView.selected = date;
  const { cursor, hCursor, marker, axisDot, yAxisDot, yValueLabel, yValueBg, tooltip, host, width, pad, height } = paperChartView;
  cursor.setAttribute("x1", String(point.x));
  cursor.setAttribute("x2", String(point.x));
  cursor.setAttribute("y1", String(pad.top));
  cursor.setAttribute("y2", String(height - pad.bottom + 8));
  cursor.setAttribute("visibility", "visible");
  if (hCursor) {
    hCursor.setAttribute("x1", String(pad.left - 8));
    hCursor.setAttribute("x2", String(width - pad.right));
    hCursor.setAttribute("y1", String(point.y));
    hCursor.setAttribute("y2", String(point.y));
    hCursor.setAttribute("visibility", "visible");
  }
  marker.setAttribute("cx", String(point.x));
  marker.setAttribute("cy", String(point.y));
  marker.setAttribute("visibility", "visible");
  axisDot.setAttribute("cx", String(point.x));
  axisDot.setAttribute("cy", String(height - pad.bottom + 8));
  axisDot.setAttribute("visibility", "visible");
  if (yAxisDot) {
    yAxisDot.setAttribute("cx", String(pad.left));
    yAxisDot.setAttribute("cy", String(point.y));
    yAxisDot.setAttribute("visibility", "visible");
  }
  if (yValueLabel) {
    yValueLabel.textContent = formatAxisMoney(point.row.total_asset);
    yValueLabel.setAttribute("x", String(pad.left - 10));
    yValueLabel.setAttribute("y", String(point.y + 3));
    yValueLabel.setAttribute("visibility", "visible");
    if (yValueBg) {
      yValueBg.setAttribute("visibility", "visible");
      try {
        const box = yValueLabel.getBBox();
        yValueBg.setAttribute("x", String(box.x - 3));
        yValueBg.setAttribute("y", String(box.y - 1));
        yValueBg.setAttribute("width", String(box.width + 6));
        yValueBg.setAttribute("height", String(box.height + 2));
      } catch (_err) {
        yValueBg.setAttribute("visibility", "hidden");
      }
    }
  }
  const buys = Number(point.row.buys || 0);
  const sells = Number(point.row.sells || 0);
  tooltip.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = point.date;
  tooltip.appendChild(title);
  const lines = [
    ["总资产", formatMoney(point.row.total_asset), ""],
    ["日盈亏", formatMoney(point.row.daily_pnl), pnlClass(point.row.daily_pnl)],
    ["买入", `${buys} 条`, "side-buy"],
    ["卖出", `${sells} 条`, "side-sell"],
    ["累计", formatPct(point.row.total_return), pnlClass(point.row.total_return)],
  ];
  for (const [label, value, className] of lines) {
    const p = document.createElement("p");
    p.className = className || "";
    p.textContent = `${label} ${value}`;
    tooltip.appendChild(p);
  }
  tooltip.hidden = false;
  const hostW = host.clientWidth || width;
  const scale = hostW / width;
  const tipW = tooltip.offsetWidth || 148;
  const left = Math.min(Math.max(point.x * scale - tipW / 2, 8), hostW - tipW - 8);
  const top = Math.max(point.y * ((host.clientHeight || height) / height) - tooltip.offsetHeight - 14, 8);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  document.querySelectorAll("#paper-curve-body tr[data-date]").forEach((tr) => {
    tr.classList.toggle("is-selected", tr.dataset.date === date);
  });
  if (origin === "chart") {
    const newestFirst = (paperDailyState.rows || []).slice().reverse();
    const idx = newestFirst.findIndex((row) => row.trade_date === date);
    if (idx >= 0) {
      const nextPage = Math.floor(idx / TRADE_PAGE_SIZE) + 1;
      if (nextPage !== tradePages.daily) {
        tradePages.daily = nextPage;
        renderPaperDaily();
        document.querySelectorAll("#paper-curve-body tr[data-date]").forEach((tr) => {
          tr.classList.toggle("is-selected", tr.dataset.date === date);
        });
      }
    }
  }
}

let paperDailyState = { rows: [], fillsByDate: {}, expanded: null };

function groupFillsByDate(fills) {
  const map = {};
  for (const fill of fills) {
    const day = String(fill.trade_date || "");
    if (!day) {
      continue;
    }
    if (!map[day]) {
      map[day] = [];
    }
    map[day].push(fill);
  }
  return map;
}

function togglePaperDayExpand(date) {
  paperDailyState.expanded = paperDailyState.expanded === date ? null : date;
  renderPaperDaily();
  selectPaperDay(date, "table");
}

function buildPaperDayDetailRow(date) {
  const tr = document.createElement("tr");
  tr.className = "paper-day-detail";
  tr.addEventListener("click", (event) => event.stopPropagation());
  const td = document.createElement("td");
  td.colSpan = 9;
  const fills = paperDailyState.fillsByDate[date] || [];
  if (!fills.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "当日无成交";
    td.appendChild(empty);
    tr.appendChild(td);
    return tr;
  }
  const grid = document.createElement("div");
  grid.className = "paper-day-fills";
  grid.setAttribute("role", "table");
  for (const label of ["代码", "方向", "数量", "成交价", "成交额", "费用"]) {
    const head = document.createElement("div");
    head.className = "paper-day-fills-h";
    head.setAttribute("role", "columnheader");
    head.textContent = label;
    grid.appendChild(head);
  }
  for (const fill of fills) {
    const cells = [
      [fill.symbol || "-", ""],
      [fill.side === "SELL" ? "卖出" : "买入", fill.side === "SELL" ? "side-sell" : "side-buy"],
      [String(fill.filled_qty ?? "-"), ""],
      [formatMoney(fill.filled_price), ""],
      [formatMoney(fill.notional), ""],
      [formatMoney(fill.fee), ""],
    ];
    for (const [text, className] of cells) {
      const cell = document.createElement("div");
      cell.className = className ? `paper-day-fills-c ${className}` : "paper-day-fills-c";
      cell.setAttribute("role", "cell");
      cell.textContent = text;
      grid.appendChild(cell);
    }
  }
  td.appendChild(grid);
  tr.appendChild(td);
  return tr;
}

function renderPaperDaily() {
  const body = document.getElementById("paper-curve-body");
  if (!body) {
    return;
  }
  const rows = paperDailyState.rows || [];
  body.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 9;
    td.className = "table-empty";
    td.textContent = "还没有模拟快照。";
    tr.appendChild(td);
    body.appendChild(tr);
    paintTradePager("paper-daily", tradePageSlice([], 1));
    return;
  }
  const newestFirst = rows.slice().reverse();
  const info = tradePageSlice(newestFirst, tradePages.daily);
  tradePages.daily = info.page;
  if (!info.total) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 9;
    td.className = "table-empty";
    td.textContent = "还没有模拟快照。";
    tr.appendChild(td);
    body.appendChild(tr);
    paintTradePager("paper-daily", info);
    return;
  }
  info.items.forEach((row, index) => {
    const tr = document.createElement("tr");
    const expanded = paperDailyState.expanded === row.trade_date;
    tr.dataset.date = row.trade_date;
    tr.setAttribute("aria-expanded", expanded ? "true" : "false");
    tr.addEventListener("click", () => togglePaperDayExpand(row.trade_date));
    const seq = document.createElement("td");
    seq.className = "num paper-day-seq";
    const caret = document.createElement("span");
    caret.className = "paper-day-caret";
    caret.textContent = expanded ? "▾" : "▸";
    seq.append(caret, document.createTextNode(String(info.start + index + 1)));
    tr.appendChild(seq);
    appendCell(tr, row.trade_date || "-");
    appendCell(tr, formatMoney(row.total_asset), { className: "num" });
    appendCell(tr, formatMoney(row.daily_pnl), { className: pnlClass(row.daily_pnl) });
    appendCell(tr, formatPct(row.daily_return), { className: pnlClass(row.daily_return) });
    appendCell(tr, formatPct(row.total_return), { className: pnlClass(row.total_return) });
    appendCell(tr, formatMoney(row.buy_notional), { className: "num" });
    appendCell(tr, formatMoney(row.sell_notional), { className: "num" });
    appendCell(tr, String((row.buys || 0) + (row.sells || 0)), { className: "num" });
    body.appendChild(tr);
    if (expanded) {
      body.appendChild(buildPaperDayDetailRow(row.trade_date));
    }
  });
  paintTradePager("paper-daily", info);
  const selected = paperChartView?.selected;
  if (selected) {
    document.querySelectorAll("#paper-curve-body tr[data-date]").forEach((tr) => {
      tr.classList.toggle("is-selected", tr.dataset.date === selected);
    });
  }
}

function renderPaperPositions(rows) {
  const body = document.getElementById("paper-position-body");
  if (!body) {
    return;
  }
  if (Array.isArray(rows)) {
    tradeLists.positions = rows.slice();
  }
  const info = tradePageSlice(tradeLists.positions, tradePages.positions);
  tradePages.positions = info.page;
  body.innerHTML = "";
  if (!info.total) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "当前空仓。";
    tr.appendChild(td);
    body.appendChild(tr);
    paintTradePager("paper-position", info);
    return;
  }
  info.items.forEach((row, index) => {
    const tr = document.createElement("tr");
    appendCell(tr, String(info.start + index + 1), { className: "num" });
    appendCell(tr, row.symbol || "-");
    appendCell(tr, String(row.qty ?? "-"), { className: "num" });
    appendCell(tr, formatMoney(row.cost), { className: "num" });
    appendCell(tr, formatMoney(row.market_price), { className: "num" });
    appendCell(tr, formatMoney(row.market_value), { className: "num" });
    body.appendChild(tr);
  });
  paintTradePager("paper-position", info);
}

function renderPaperFills(rows) {
  const body = document.getElementById("paper-fill-body");
  if (!body) {
    return;
  }
  if (Array.isArray(rows)) {
    tradeLists.fills = rows.slice().reverse();
  }
  const info = tradePageSlice(tradeLists.fills, tradePages.fills);
  tradePages.fills = info.page;
  body.innerHTML = "";
  if (!info.total) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.className = "table-empty";
    td.textContent = "还没有成交。";
    tr.appendChild(td);
    body.appendChild(tr);
    paintTradePager("paper-fill", info);
    return;
  }
  info.items.forEach((row, index) => {
    const tr = document.createElement("tr");
    appendCell(tr, String(info.start + index + 1), { className: "num" });
    appendCell(tr, row.trade_date || "-");
    appendCell(tr, row.symbol || "-");
    appendCell(tr, row.side === "SELL" ? "卖出" : "买入", {
      className: row.side === "SELL" ? "side-sell" : "side-buy",
    });
    appendCell(tr, String(row.filled_qty ?? "-"), { className: "num" });
    appendCell(tr, formatMoney(row.filled_price), { className: "num" });
    appendCell(tr, formatMoney(row.notional), { className: "num" });
    appendCell(tr, formatMoney(row.fee), { className: "num" });
    body.appendChild(tr);
  });
  paintTradePager("paper-fill", info);
}

function renderPaperChart(rows, board) {
  const host = document.getElementById("paper-equity-chart");
  const meta = document.getElementById("paper-chart-meta");
  paperChartView = null;
  if (!host) {
    return;
  }
  host.innerHTML = "";
  if (meta) {
    meta.textContent = board.window_start
      ? `${board.window_start} ~ ${board.window_end} · 本金 ${formatMoney(board.initial_cash)} · 区间 ${formatPct(board.total_return)}`
      : "相对本金 1,000,000";
  }
  if (!rows.length) {
    host.textContent = "暂无净值曲线";
    return;
  }
  const width = 720;
  const height = 248;
  const pad = { top: 16, right: 36, bottom: 28, left: 58 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const assets = rows.map((row) => Number(row.total_asset));
  const minY = Math.min(...assets);
  const maxY = Math.max(...assets);
  const spanY = maxY - minY || Math.abs(maxY) * 0.02 || 1;
  const xAt = (index) => pad.left + (rows.length === 1 ? innerW / 2 : (index / (rows.length - 1)) * innerW);
  const yAt = (value) => pad.top + (1 - (value - minY) / spanY) * innerH;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "paper-chart-svg");
  const ticks = [maxY, (maxY + minY) / 2, minY];
  ticks.forEach((value, tickIndex) => {
    const y = yAt(value);
    const grid = document.createElementNS(ns, "line");
    grid.setAttribute("x1", String(pad.left));
    grid.setAttribute("x2", String(width - pad.right));
    grid.setAttribute("y1", String(y));
    grid.setAttribute("y2", String(y));
    grid.setAttribute("class", "paper-chart-grid");
    svg.appendChild(grid);
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", String(pad.left - 8));
    label.setAttribute("y", String(tickIndex === 0 ? y + 9 : tickIndex === ticks.length - 1 ? y - 2 : y + 3));
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", "paper-chart-label");
    label.textContent = formatAxisMoney(value);
    svg.appendChild(label);
  });
  const points = rows.map((row, index) => ({
    date: row.trade_date,
    x: xAt(index),
    y: yAt(Number(row.total_asset)),
    row,
  }));
  const lineD = smoothLinePath(points);
  const area = document.createElementNS(ns, "path");
  area.setAttribute(
    "d",
    `${lineD} L ${points[points.length - 1].x} ${height - pad.bottom} L ${points[0].x} ${height - pad.bottom} Z`,
  );
  area.setAttribute("class", "paper-chart-area");
  svg.appendChild(area);
  const line = document.createElementNS(ns, "path");
  line.setAttribute("d", lineD);
  line.setAttribute("class", "paper-chart-line");
  svg.appendChild(line);
  const tickIndexes = xTickIndexes(rows.length);
  tickIndexes.forEach((index, order) => {
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", String(xAt(index)));
    text.setAttribute("y", String(height - 8));
    text.setAttribute(
      "text-anchor",
      order === 0 ? "start" : order === tickIndexes.length - 1 ? "end" : "middle",
    );
    text.setAttribute("class", "paper-chart-label");
    text.textContent = shortMd(rows[index].trade_date);
    svg.appendChild(text);
  });
  points.forEach((point) => {
    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", String(point.x));
    dot.setAttribute("cy", String(point.y));
    dot.setAttribute("r", "3.4");
    dot.setAttribute("class", "paper-chart-dot");
    svg.appendChild(dot);
  });
  const cursor = document.createElementNS(ns, "line");
  cursor.setAttribute("class", "paper-chart-cursor");
  cursor.setAttribute("visibility", "hidden");
  svg.appendChild(cursor);
  const hCursor = document.createElementNS(ns, "line");
  hCursor.setAttribute("class", "paper-chart-cursor");
  hCursor.setAttribute("visibility", "hidden");
  svg.appendChild(hCursor);
  const marker = document.createElementNS(ns, "circle");
  marker.setAttribute("r", "5");
  marker.setAttribute("class", "paper-chart-marker");
  marker.setAttribute("visibility", "hidden");
  svg.appendChild(marker);
  const axisDot = document.createElementNS(ns, "circle");
  axisDot.setAttribute("r", "5");
  axisDot.setAttribute("class", "paper-chart-axis-dot");
  axisDot.setAttribute("visibility", "hidden");
  svg.appendChild(axisDot);
  const yAxisDot = document.createElementNS(ns, "circle");
  yAxisDot.setAttribute("r", "5");
  yAxisDot.setAttribute("class", "paper-chart-axis-dot");
  yAxisDot.setAttribute("visibility", "hidden");
  svg.appendChild(yAxisDot);
  const yValueBg = document.createElementNS(ns, "rect");
  yValueBg.setAttribute("class", "paper-chart-y-value-bg");
  yValueBg.setAttribute("rx", "3");
  yValueBg.setAttribute("visibility", "hidden");
  svg.appendChild(yValueBg);
  const yValueLabel = document.createElementNS(ns, "text");
  yValueLabel.setAttribute("class", "paper-chart-y-value");
  yValueLabel.setAttribute("text-anchor", "end");
  yValueLabel.setAttribute("visibility", "hidden");
  svg.appendChild(yValueLabel);
  const hit = document.createElementNS(ns, "g");
  const band = rows.length === 1 ? innerW : innerW / (rows.length - 1);
  points.forEach((point) => {
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("x", String(point.x - band / 2));
    rect.setAttribute("y", String(pad.top));
    rect.setAttribute("width", String(band));
    rect.setAttribute("height", String(innerH + 16));
    rect.setAttribute("class", "paper-chart-hit");
    rect.addEventListener("mouseenter", () => selectPaperDay(point.date, "hover"));
    rect.addEventListener("click", () => selectPaperDay(point.date, "chart"));
    hit.appendChild(rect);
  });
  svg.appendChild(hit);
  const tooltip = document.createElement("div");
  tooltip.className = "paper-chart-tooltip";
  tooltip.hidden = true;
  host.appendChild(svg);
  host.appendChild(tooltip);
  paperChartView = { points, selected: null, cursor, hCursor, marker, axisDot, yAxisDot, yValueLabel, yValueBg, tooltip, host, width, height, pad };
}

bindTradePager("paper-daily", "daily", renderPaperDaily);
bindTradePager("paper-position", "positions", () => renderPaperPositions());
bindTradePager("paper-fill", "fills", () => renderPaperFills());
bindTradePager("paper-order", "orders", () => renderOrders(tradeLists.orders, "order-body"));
bindTradePager("mock-order", "mock", () => renderOrders(tradeLists.mock, "mock-order-body"));

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
resumeActivePaperRun();
