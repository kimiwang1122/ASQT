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
  override_conflict: "模拟覆盖参数冲突或非法，请检查 force_in/cap 权重",
  stale_data: "行情过旧，拒绝用过期价撮合",
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
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
  return response.json();
}

/** Call planned endpoints; on 404 return null and toast (events sibling may lag). */
async function requestJsonOrMissing(url, options, missingLabel) {
  try {
    return await requestJson(url, options);
  } catch (error) {
    if (error && error.status === 404) {
      showToast(missingLabel || `接口暂不可用（404）：${url}`, "warn");
      return null;
    }
    throw error;
  }
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

const DECISION_STATUS_LABEL = {
  pending: "待结算",
  resolved: "已结算",
};

const DECISION_RATING_LABEL = {
  Buy: "买入",
  Overweight: "超配",
  Hold: "持有",
  Underweight: "低配",
  Sell: "卖出",
  REVIEW: "待复核",
};

const FACTOR_NAME_LABEL = {
  etf_ma_gap: "ETF 均线偏离",
  etf_momentum: "ETF 动量",
  stock_momentum: "股票动量",
  stock_volatility: "股票波动率",
  stock_mom_over_vol: "动量/波动",
  stock_reversal: "股票短反转",
  stock_volume_z: "成交量 Z 值",
  stock_momentum_skip_month: "跳月动量",
  stock_holder_net: "股东净增持",
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
  "factor-compute": "因子计算",
  factor_compute: "因子计算",
  "factors-compute": "因子计算",
  factors_compute: "因子计算",
};

const OVERRIDE_ACTION_LABEL = {
  force_in: "强制纳入",
  force_out: "强制剔除",
  cap: "权重上限",
};
const STRATEGY_STATUS_LABEL = {
  unregistered: "未注册",
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

function containPageWidth() {
  document.querySelectorAll(".table-wrap").forEach((wrap) => {
    wrap.style.maxWidth = "100%";
    wrap.style.overflowX = "hidden";
    const table = wrap.querySelector("table");
    if (!table) {
      return;
    }
    table.style.tableLayout = "fixed";
    table.style.width = "100%";
    table.style.maxWidth = "100%";
    if (!table.classList.contains("strategy-table")) {
      return;
    }
    table.querySelectorAll("th:nth-child(5), td:nth-child(5)").forEach((cell) => {
      cell.style.maxWidth = "0";
    });
    table.querySelectorAll("th:nth-child(7), td:nth-child(7)").forEach((cell) => {
      cell.style.width = "7.5rem";
      cell.style.minWidth = "7.5rem";
    });
  });
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
  if (status === "review") {
    return "block";
  }
  if (status === "partial") {
    return "warn";
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

function isReconcileReviewTask(task, status) {
  const name = String(task?.task_name || "");
  return (
    status === "review" ||
    (
      status === "partial" &&
      (
        name === "reconcile-daily" ||
        name === "reconcile_daily" ||
        name === "cash-reconcile" ||
        name === "cash_reconcile"
      )
    )
  );
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
    td.textContent = "当前筛选没有行情。请到「同步」页点「追加行情」同步或拉取数据。";
    tr.appendChild(td);
    body.appendChild(tr);
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

let overviewTaskTimer = 0;
let overviewTaskStamp = "";

function renderTasks(tasks) {
  const list = document.getElementById("task-list");
  if (!list) {
    return;
  }
  const stamp = JSON.stringify(
    (tasks || []).map((task) => [
      task.run_id,
      task.status,
      task.started_at,
      task.finished_at,
      task.message,
    ]),
  );
  if (stamp === overviewTaskStamp) {
    return;
  }
  overviewTaskStamp = stamp;
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
    const review = isReconcileReviewTask(task, status);
    const statusLabel = review
      ? "待复核"
      : SYNC_STATUS_LABEL[status] || status || "-";
    left.textContent = `${formatTaskName(task.task_name)} ${formatDateTime(task.started_at)}`;
    const tag = makeTag(statusLabel, review ? "block" : toneForSync(status));
    if (review) {
      tag.classList.add("is-review-alert");
    }
    if (task.message) {
      tag.title = typeof task.message === "string" ? task.message : JSON.stringify(task.message);
    }
    li.append(left, tag);
    list.appendChild(li);
  }
}

function pollOverviewTasks() {
  if (currentPage() !== "overview" || document.hidden) {
    return;
  }
  requestJson("/api/status")
    .then((status) => {
      renderTasks(status.recent_tasks || []);
    })
    .catch(() => {});
}

function watchOverviewTasks() {
  if (overviewTaskTimer) {
    return;
  }
  pollOverviewTasks();
  overviewTaskTimer = window.setInterval(pollOverviewTasks, 2000);
}

function stopOverviewTasks() {
  window.clearInterval(overviewTaskTimer);
  overviewTaskTimer = 0;
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
    td.textContent = "暂无数据源。请到「同步」页点「追加行情」同步后刷新。";
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
  stale_asof: "行情过旧",
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
  "max drawdown stop": "组合回撤触发急停",
  "strategy drawdown halt": "单策略回撤平仓",
  "flatten incomplete": "未完成平仓",
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
    const kind = String(payload.kind || "");
    const strategyStop = kind.endsWith("strategy_stop") || String(row?.title || "").includes("strategy drawdown");
    const stop =
      row?.level === "critical" ||
      kind.endsWith("stop") ||
      String(row?.title || "").includes("stop");
    const warn = kind.endsWith("warn") || String(row?.title || "").includes("warning");
    if (strategyStop) {
      return `回撤 ${pctText(payload.dd)} 触发单策略平仓`;
    }
    if (stop) {
      return `回撤 ${pctText(payload.dd)} 触发组合急停`;
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

  const isDrawdown =
    String(payload.kind || "").startsWith("drawdown") ||
    category === "drawdown" ||
    String(row?.title || "").includes("drawdown");

  if (isDrawdown) {
    if (payload.strategy_id) {
      push("策略", STRATEGY_LABEL[payload.strategy_id] || payload.strategy_id);
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

  if (
    String(payload.kind || "").startsWith("drawdown") ||
    category === "drawdown" ||
    String(row?.title || "").includes("drawdown")
  ) {
    if (payload.strategy_id) {
      lines.push(`策略：${STRATEGY_LABEL[payload.strategy_id] || payload.strategy_id}`);
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
    watchOverviewTasks();
    if ((location.hash || "").includes("overview-alerts")) {
      window.setTimeout(focusOverviewAlerts, 80);
    }
  } else {
    stopOverviewTasks();
  }
  if (page === "data") {
    loadQualityIssues().catch((error) => {
      setText("quality-page-meta", `加载失败：${error.message}`);
    });
    loadEventsPage().catch((error) => {
      setText("events-page-meta", `加载失败：${error.message}`);
    });
    resumeActiveEventsPull().catch(() => {});
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
    loadOverridesPage().catch((error) => {
      setText("override-page-meta", `加载失败：${error.message}`);
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
    loadFactorsPage().catch((error) => {
      setText("factor-compute-meta", `加载失败：${error.message}`);
    });
    loadTagsPage().catch((error) => {
      setText("tags-page-meta", `加载失败：${error.message}`);
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
  syncPaperRunDaysMax(status.max_paper_days);
  syncPaperRunDateBounds(status.paper_first_date, status.paper_last_date);
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
    ["模拟天数上限", status.max_paper_days],
  ]);
  renderKv(
    "layout-grid",
    Object.entries(status.layout || health.layout || {}).map(([k, v]) => [k, v]),
  );
}

let paperRunDaysMax = 2000;
let paperRunFirstDate = "";
let paperRunLastDate = "";

function syncPaperRunDaysMax(maxDays) {
  const max = Math.max(1, Number(maxDays) || 0);
  if (!max) {
    return;
  }
  paperRunDaysMax = max;
  const input = document.getElementById("paper-run-days");
  if (!input) {
    return;
  }
  input.max = String(max);
  input.title = `从最近行情往前推；上限 ${max}。填写开始/结束日期时以日期为准`;
  const current = Number(input.value);
  if (Number.isFinite(current) && current > max) {
    input.value = String(max);
  }
}

function syncPaperRunDateBounds(firstDate, lastDate) {
  paperRunFirstDate = firstDate || "";
  paperRunLastDate = lastDate || "";
  for (const id of ["paper-run-start", "paper-run-end"]) {
    const input = document.getElementById(id);
    if (!input) {
      continue;
    }
    if (paperRunFirstDate) {
      input.min = paperRunFirstDate;
    }
    if (paperRunLastDate) {
      input.max = paperRunLastDate;
    }
  }
}

function paperRunDateRange() {
  const start = document.getElementById("paper-run-start")?.value || "";
  const end = document.getElementById("paper-run-end")?.value || "";
  if (!start && !end) {
    return { start_date: null, end_date: null };
  }
  if (!start || !end) {
    return { error: "开始与结束日期需同时填写，或都留空改用「天数」" };
  }
  if (start > end) {
    return { error: "开始日期不能晚于结束日期" };
  }
  return { start_date: start, end_date: end };
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
let confirmOptions = {};

const CONFIRM_REASON_HINT = "请填写原因（不能全是空格）";

function showConfirmReasonError(message) {
  const reasonInput = document.getElementById("confirm-reason");
  const reasonError = document.getElementById("confirm-reason-error");
  if (reasonError) {
    reasonError.hidden = !message;
    reasonError.textContent = message || "";
  }
  if (reasonInput) {
    reasonInput.classList.toggle("is-invalid", Boolean(message));
    if (message) {
      reasonInput.focus();
      reasonInput.select?.();
    }
  }
}

function closeConfirmDialog(ok) {
  const requireReason = Boolean(confirmOptions.requireReason);
  if (ok && requireReason) {
    const reasonInput = document.getElementById("confirm-reason");
    const value = (reasonInput?.value || "").trim();
    if (!value) {
      showConfirmReasonError(CONFIRM_REASON_HINT);
      return;
    }
  }
  const mask = document.getElementById("confirm-dialog");
  const card = mask?.querySelector(".confirm-card");
  const reasonWrap = document.getElementById("confirm-reason-wrap");
  const reasonInput = document.getElementById("confirm-reason");
  const reason = (reasonInput?.value || "").trim();
  if (mask) {
    mask.hidden = true;
  }
  if (card) {
    card.classList.remove("has-reason");
  }
  if (reasonWrap) {
    reasonWrap.hidden = true;
  }
  if (reasonInput) {
    reasonInput.value = "";
    reasonInput.classList.remove("is-invalid");
  }
  showConfirmReasonError("");
  const resolve = confirmResolver;
  const options = confirmOptions;
  confirmResolver = null;
  confirmOptions = {};
  if (!resolve) {
    return;
  }
  if (options.requireReason) {
    resolve(ok ? { ok: true, reason } : { ok: false, reason: "" });
    return;
  }
  resolve(Boolean(ok));
}

function confirmDialog(message, options = {}) {
  const mask = document.getElementById("confirm-dialog");
  const text = document.getElementById("confirm-message");
  const okBtn = document.getElementById("confirm-ok");
  const card = mask?.querySelector(".confirm-card");
  const reasonWrap = document.getElementById("confirm-reason-wrap");
  const reasonInput = document.getElementById("confirm-reason");
  if (!mask || !text) {
    if (options.requireReason) {
      const reason = window.prompt(message, "");
      if (reason == null) {
        return Promise.resolve({ ok: false, reason: "" });
      }
      const trimmed = String(reason).trim();
      if (!trimmed) {
        return Promise.resolve({ ok: false, reason: "" });
      }
      return Promise.resolve({ ok: true, reason: trimmed });
    }
    return Promise.resolve(window.confirm(message));
  }
  if (confirmResolver) {
    closeConfirmDialog(false);
  }
  confirmOptions = options || {};
  text.textContent = message;
  const requireReason = Boolean(confirmOptions.requireReason);
  if (card) {
    card.classList.toggle("has-reason", requireReason);
  }
  if (reasonWrap) {
    reasonWrap.hidden = !requireReason;
  }
  if (reasonInput) {
    reasonInput.value = "";
    reasonInput.classList.remove("is-invalid");
    reasonInput.placeholder = confirmOptions.reasonPlaceholder || "必填";
  }
  showConfirmReasonError("");
  mask.hidden = false;
  if (requireReason && reasonInput) {
    reasonInput.focus();
  } else {
    okBtn?.focus();
  }
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
document.getElementById("confirm-reason")?.addEventListener("input", () => {
  const reasonInput = document.getElementById("confirm-reason");
  const reasonError = document.getElementById("confirm-reason-error");
  if (reasonError && !reasonError.hidden) {
    const value = (reasonInput?.value || "").trim();
    showConfirmReasonError(value ? "" : CONFIRM_REASON_HINT);
  } else if (reasonInput) {
    reasonInput.classList.remove("is-invalid");
  }
});
document.getElementById("confirm-reason")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    closeConfirmDialog(true);
  }
});
window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (confirmResolver) {
    closeConfirmDialog(false);
    return;
  }
  const lookup = document.getElementById("lookup-dialog");
  if (lookup && !lookup.hidden) {
    closeLookupDialog();
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
    return "自动同步已关闭。可到「同步」页点「追加行情」人工触发。";
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

function syncFailReasonTitle(row) {
  const reason = String(row?.fail_reason || "").trim();
  if (!reason) {
    return "";
  }
  // Never surface raw job detail JSON on hover.
  if (reason.startsWith("{") || reason.startsWith("[")) {
    return "";
  }
  return reason;
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
      const failTitle = syncFailReasonTitle(row);
      appendCell(tr, String(startNo + index + 1), { className: "num" });
      appendCell(tr, formatDateTime(row.started_at || row.created_at));
      appendCell(tr, formatDateTime(row.finished_at));
      appendCell(tr, SYNC_TRIGGER_LABEL[row.trigger] || row.trigger || "-");
      appendCell(tr, syncStatusLabel(row), {
        tone: toneForSync(row.status),
        title: syncStatusTitle(row) || failTitle,
      });
      appendCell(tr, windowLabel);
      appendCell(tr, row.max_trade_date_after || row.max_trade_date_before || "-");
      appendCell(tr, row.normalized_rows == null ? "-" : String(row.normalized_rows), { className: "num" });
      appendCell(tr, qualityLabel, {
        tone: row.quality_ok == null ? "muted" : Number(row.quality_ok) ? "ok" : "block",
      });
      appendCell(tr, failTitle || (row.fail_reason ? "见质检详情" : "-"), {
        className: "cell-clip",
        title: failTitle,
      });
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
  const modes = String(select.dataset.asqtSelect || "")
    .split(/\s+/)
    .filter(Boolean);
  const multi = select.multiple || modes.includes("multi");
  if (multi) {
    select.multiple = true;
    enhanceMultiSelect(select, modes);
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = modes.includes("wide") ? "asqt-select asqt-select-wide" : "asqt-select";
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "asqt-select-trigger";
  const triggerLabel = document.createElement("span");
  triggerLabel.className = "asqt-select-trigger-label";
  trigger.appendChild(triggerLabel);
  const menu = document.createElement("ul");
  menu.className = "asqt-select-menu";
  menu.hidden = true;
  wrap.append(trigger, menu);
  const searchable = modes.includes("search");
  let query = "";
  let search = null;
  if (searchable) {
    const searchRow = document.createElement("li");
    searchRow.className = "asqt-select-search-row";
    search = document.createElement("input");
    search.type = "search";
    search.className = "asqt-select-filter";
    search.autocomplete = "off";
    search.spellcheck = false;
    search.placeholder = "搜索参数组";
    search.setAttribute("aria-label", "搜索参数组");
    search.addEventListener("click", (event) => event.stopPropagation());
    search.addEventListener("input", () => {
      query = search.value || "";
      renderOptions();
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeAllSelects();
      }
    });
    searchRow.appendChild(search);
    menu.appendChild(searchRow);
  }

  function currentLabel() {
    const selected = select.options[select.selectedIndex];
    return selected ? selected.textContent : "请选择";
  }

  function renderOptions() {
    menu.querySelectorAll("li[data-value], li.asqt-select-empty").forEach((node) => node.remove());
    const needle = query.trim().toLowerCase();
    let visible = 0;
    [...select.options].forEach((option) => {
      const hay = `${option.textContent} ${option.value}`.toLowerCase();
      if (needle && !hay.includes(needle)) {
        return;
      }
      visible += 1;
      const li = document.createElement("li");
      li.textContent = option.textContent;
      li.dataset.value = option.value;
      if (option.selected) {
        li.classList.add("is-active");
      }
      li.addEventListener("click", () => {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        closeAllSelects();
      });
      menu.appendChild(li);
    });
    if (searchable && needle && !visible) {
      const empty = document.createElement("li");
      empty.className = "asqt-select-empty";
      empty.textContent = "无匹配参数组";
      menu.appendChild(empty);
    }
  }

  function renderMenu() {
    renderOptions();
    const label = currentLabel() || "请选择";
    triggerLabel.textContent = label;
    trigger.title = label;
    trigger.classList.toggle("is-placeholder", !select.value && currentLabel() === "全部");
  }

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    const open = menu.hidden;
    closeAllSelects();
    if (open) {
      menu.hidden = false;
      wrap.classList.add("is-open");
      if (search) {
        search.focus();
      }
    }
  });
  select.addEventListener("change", renderMenu);
  wrap._asqtSingleClear = () => {
    query = "";
    if (search) {
      search.value = "";
    }
    renderOptions();
  };
  renderMenu();
}

function enhanceMultiSelect(select, modes) {
  const parsedMax = Number(select.dataset.maxTags);
  const maxTags = Number.isFinite(parsedMax) && parsedMax > 0 ? parsedMax : Number.POSITIVE_INFINITY;
  const wrap = document.createElement("div");
  wrap.className = modes.includes("wide")
    ? "asqt-select asqt-select-wide asqt-select-multi"
    : "asqt-select asqt-select-multi";
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);

  const control = document.createElement("div");
  control.className = "asqt-select-control asqt-select-trigger";
  control.tabIndex = 0;
  control.setAttribute("role", "combobox");
  control.setAttribute("aria-expanded", "false");
  control.setAttribute("aria-haspopup", "listbox");

  const tags = document.createElement("div");
  tags.className = "asqt-select-tags";
  const search = document.createElement("input");
  search.type = "search";
  search.className = "asqt-select-search";
  search.autocomplete = "off";
  search.spellcheck = false;
  search.setAttribute("aria-label", "搜索策略");
  search.placeholder = "";
  const icon = document.createElement("span");
  icon.className = "asqt-select-search-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.innerHTML =
    '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.5 10.5 L14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
  tags.appendChild(search);
  control.append(tags, icon);

  const menu = document.createElement("ul");
  menu.className = "asqt-select-menu";
  menu.hidden = true;
  menu.setAttribute("role", "listbox");
  menu.setAttribute("aria-multiselectable", "true");
  wrap.append(control, menu);

  let query = "";

  function strategyOptions() {
    return [...select.options].filter((option) => option.value !== "all");
  }

  function selectedStrategyOptions() {
    return strategyOptions().filter((option) => option.selected);
  }

  function syncAllOptionState() {
    const allOpt = [...select.options].find((option) => option.value === "all");
    if (!allOpt) {
      return;
    }
    const strategies = strategyOptions();
    allOpt.selected = strategies.length > 0 && strategies.every((option) => option.selected);
  }

  function openMenu() {
    closeAllSelects();
    menu.hidden = false;
    wrap.classList.add("is-open");
    control.setAttribute("aria-expanded", "true");
    search.focus();
  }

  function renderControl() {
    syncAllOptionState();
    const selected = selectedStrategyOptions();
    const allSelected = selected.length > 0 && selected.length === strategyOptions().length;
    tags.querySelectorAll(".asqt-select-tag").forEach((node) => node.remove());
    if (allSelected) {
      const tag = document.createElement("span");
      tag.className = "asqt-select-tag";
      const label = document.createElement("em");
      label.textContent = "全部";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "asqt-select-tag-remove";
      remove.setAttribute("aria-label", "清空策略选择");
      remove.textContent = "×";
      remove.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        strategyOptions().forEach((option) => {
          option.selected = false;
        });
        syncAllOptionState();
        select.dispatchEvent(new Event("change", { bubbles: true }));
        renderAll();
      });
      tag.append(label, remove);
      tags.insertBefore(tag, search);
    } else {
      const visible = selected.slice(0, maxTags);
      const overflow = selected.length - visible.length;
      visible.forEach((option) => {
        const tag = document.createElement("span");
        tag.className = "asqt-select-tag";
        const label = document.createElement("em");
        label.textContent = option.textContent;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "asqt-select-tag-remove";
        remove.setAttribute("aria-label", `移除 ${option.textContent}`);
        remove.textContent = "×";
        remove.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          option.selected = false;
          syncAllOptionState();
          select.dispatchEvent(new Event("change", { bubbles: true }));
          renderAll();
        });
        tag.append(label, remove);
        tags.insertBefore(tag, search);
      });
      if (overflow > 0) {
        const more = document.createElement("span");
        more.className = "asqt-select-tag asqt-select-tag-more";
        more.textContent = `+ ${overflow} ...`;
        more.title = selected
          .slice(maxTags)
          .map((option) => option.textContent)
          .join("、");
        tags.insertBefore(more, search);
      }
    }
    search.placeholder = selected.length ? "" : "搜索策略";
    control.classList.toggle("is-placeholder", selected.length === 0);
  }

  function renderMenu() {
    menu.innerHTML = "";
    const needle = query.trim().toLowerCase();
    let visibleCount = 0;
    syncAllOptionState();
    [...select.options].forEach((option) => {
      const label = option.textContent || "";
      const isAll = option.value === "all";
      if (
        needle &&
        !isAll &&
        !label.toLowerCase().includes(needle) &&
        !option.value.toLowerCase().includes(needle)
      ) {
        return;
      }
      if (needle && isAll) {
        return;
      }
      visibleCount += 1;
      const li = document.createElement("li");
      li.dataset.value = option.value;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", option.selected ? "true" : "false");
      if (isAll) {
        li.classList.add("asqt-select-option-all");
      }
      const text = document.createElement("span");
      text.className = "asqt-select-option-label";
      text.textContent = label;
      const mark = document.createElement("span");
      mark.className = "asqt-select-check";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "✓";
      li.append(text, mark);
      if (option.selected) {
        li.classList.add("is-active");
      }
      li.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (isAll) {
          const strategies = strategyOptions();
          const selectAll = !strategies.every((item) => item.selected);
          strategies.forEach((item) => {
            item.selected = selectAll;
          });
          option.selected = selectAll;
        } else {
          option.selected = !option.selected;
          syncAllOptionState();
        }
        select.dispatchEvent(new Event("change", { bubbles: true }));
        renderAll();
        search.focus();
      });
      menu.appendChild(li);
    });
    if (!visibleCount) {
      const empty = document.createElement("li");
      empty.className = "asqt-select-empty";
      empty.textContent = "无匹配策略";
      menu.appendChild(empty);
    }
  }

  function renderAll() {
    renderControl();
    renderMenu();
  }

  control.addEventListener("click", (event) => {
    if (event.target.closest(".asqt-select-tag-remove")) {
      return;
    }
    if (menu.hidden) {
      openMenu();
    } else if (!event.target.closest(".asqt-select-search")) {
      search.focus();
    }
  });
  search.addEventListener("click", (event) => {
    event.stopPropagation();
    if (menu.hidden) {
      openMenu();
    }
  });
  search.addEventListener("input", () => {
    query = search.value || "";
    if (menu.hidden) {
      openMenu();
    } else {
      renderMenu();
    }
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "Backspace" && !search.value) {
      const selected = selectedStrategyOptions();
      if (selected.length) {
        selected[selected.length - 1].selected = false;
        syncAllOptionState();
        select.dispatchEvent(new Event("change", { bubbles: true }));
        renderAll();
      }
    }
    if (event.key === "Escape") {
      closeAllSelects();
    }
  });
  select.addEventListener("change", renderAll);
  wrap._asqtMultiClear = () => {
    query = "";
    if (search.value) {
      search.value = "";
    }
    control.setAttribute("aria-expanded", "false");
    renderControl();
    renderMenu();
  };
  renderAll();
}

function closeAllSelects() {
  document.querySelectorAll(".asqt-select").forEach((wrap) => {
    wrap.classList.remove("is-open");
    const menu = wrap.querySelector(".asqt-select-menu");
    if (menu) {
      menu.hidden = true;
    }
    if (typeof wrap._asqtMultiClear === "function") {
      wrap._asqtMultiClear();
    }
    if (typeof wrap._asqtSingleClear === "function") {
      wrap._asqtSingleClear();
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

const LOOKUP_TYPE_LABEL = { stock: "股票", etf: "ETF" };
let lookupTimer = 0;
let lookupSeq = 0;

function applyLookup(collapsed) {
  document.querySelector(".shell")?.classList.toggle("lookup-collapsed", collapsed);
  localStorage.setItem("asqt-lookup", collapsed ? "1" : "0");
  const btn = document.getElementById("lookup-toggle");
  if (btn) {
    btn.textContent = collapsed ? "⟨" : "⟩";
    btn.setAttribute("aria-label", collapsed ? "展开查询助手" : "收起查询助手");
  }
}

function lookupDash(value) {
  if (value == null || value === "") {
    return "—";
  }
  return String(value);
}

function lookupMoney(value) {
  if (value == null || value === "") {
    return "—";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return String(value);
  }
  if (Math.abs(number) >= 10000) {
    return `${(number / 10000).toFixed(2)} 万`;
  }
  return number.toFixed(2);
}

function renderLookupHits(items, q) {
  const list = document.getElementById("lookup-results");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  if (!q) {
    setHint("lookup-hint", "模糊匹配股票池内标的，点结果看 F10 资料。");
    return;
  }
  if (!items.length) {
    setHint("lookup-hint", `没有匹配「${q}」`);
    return;
  }
  setHint("lookup-hint", `${items.length} 条结果`);
  for (const row of items) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    const title = document.createElement("span");
    title.className = "lookup-sym";
    title.textContent = `${row.name || "—"}  ${row.symbol}`;
    const meta = document.createElement("span");
    meta.className = "lookup-meta";
    meta.textContent = `${LOOKUP_TYPE_LABEL[row.instrument_type] || row.instrument_type} · ${row.exchange || "—"}`;
    btn.append(title, meta);
    btn.addEventListener("click", () => {
      openLookupProfile(row.symbol).catch((error) => showToast(error.message || "查询失败", "block"));
    });
    li.appendChild(btn);
    list.appendChild(li);
  }
}

async function runLookupSearch(q) {
  const seq = ++lookupSeq;
  const needle = (q || "").trim();
  if (!needle) {
    renderLookupHits([], "");
    return;
  }
  const payload = await requestJson(`/api/lookup/search?q=${encodeURIComponent(needle)}&limit=20`);
  if (seq !== lookupSeq) {
    return;
  }
  renderLookupHits(payload.items || [], needle);
}

function scheduleLookupSearch() {
  window.clearTimeout(lookupTimer);
  lookupTimer = window.setTimeout(() => {
    runLookupSearch(document.getElementById("lookup-q")?.value || "").catch((error) => {
      setHint("lookup-hint", error.message || "查询失败");
    });
  }, 200);
}

function lookupKv(entries) {
  const grid = document.createElement("div");
  grid.className = "lookup-kv";
  for (const [label, value] of entries) {
    const item = document.createElement("div");
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = lookupDash(value);
    item.append(k, v);
    grid.appendChild(item);
  }
  return grid;
}

function lookupSection(title, child) {
  const section = document.createElement("section");
  section.className = "lookup-section";
  const h = document.createElement("h4");
  h.textContent = title;
  section.append(h, child);
  return section;
}

function lookupTable(headers, rows) {
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "暂无";
    return p;
  }
  const table = document.createElement("table");
  table.className = "lookup-mini";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const name of headers) {
    const th = document.createElement("th");
    th.textContent = name;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = lookupDash(cell);
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  table.append(thead, body);
  return table;
}

function closeLookupDialog() {
  const dialog = document.getElementById("lookup-dialog");
  if (dialog) {
    dialog.hidden = true;
  }
}

function paintLookupProfile(payload) {
  const inst = payload.instrument || {};
  const quote = payload.quote || {};
  setText("lookup-dialog-title", `${inst.name || "标的"} ${inst.symbol || ""}`.trim());
  const sub = document.getElementById("lookup-dialog-sub");
  if (sub) {
    const bits = [
      LOOKUP_TYPE_LABEL[inst.instrument_type] || inst.instrument_type,
      inst.exchange,
      (payload.tags || []).join(" / "),
      payload.sources?.tushare ? "Tushare F10" : "本地档案",
    ].filter(Boolean);
    sub.textContent = bits.join(" · ");
    sub.hidden = !bits.length;
  }
  const host = document.getElementById("lookup-dialog-body");
  if (!host) {
    return;
  }
  host.innerHTML = "";
  host.appendChild(
    lookupSection(
      "基本资料",
      lookupKv([
        ["代码", inst.symbol],
        ["名称", inst.name],
        ["类型", LOOKUP_TYPE_LABEL[inst.instrument_type] || inst.instrument_type],
        ["交易所", inst.exchange],
        ["板块", inst.board],
        ["上市日", inst.list_date],
        ["状态", inst.status],
        ["ST", inst.is_st ? "是" : "否"],
        ["标签", (payload.tags || []).join("、") || "—"],
      ]),
    ),
  );
  host.appendChild(
    lookupSection(
      "最新行情",
      lookupKv([
        ["日期", quote.trade_date],
        ["收盘", quote.close],
        ["开盘", quote.open],
        ["最高", quote.high],
        ["最低", quote.low],
        ["涨跌", quote.change_pct == null ? "—" : formatPct(quote.change_pct)],
        ["成交量", lookupMoney(quote.volume)],
        ["成交额", lookupMoney(quote.amount)],
      ]),
    ),
  );
  const lim = payload.limit;
  if (lim) {
    host.appendChild(
      lookupSection(
        "涨跌停 / 停牌",
        lookupKv([
          ["日期", lim.trade_date],
          ["涨停", lim.limit_up],
          ["跌停", lim.limit_down],
          ["停牌", lim.is_suspended ? "是" : "否"],
          ["原因", lim.reason],
        ]),
      ),
    );
  }
  const company = payload.company || {};
  if (Object.keys(company).length) {
    host.appendChild(
      lookupSection(
        "公司概况",
        lookupKv([
          ["董事长", company.chairman],
          ["总经理", company.manager],
          ["注册资本", company.reg_capital],
          ["成立日期", company.setup_date || company.found_date],
          ["省份", company.province],
          ["城市", company.city],
          ["员工数", company.employees],
          ["网站", company.website],
          ["基金管理人", company.management],
          ["托管人", company.custodian],
        ].filter(([, value]) => value != null && value !== "")),
      ),
    );
    if (company.main_business || company.introduction) {
      const p = document.createElement("p");
      p.className = "lookup-prose";
      p.textContent = company.main_business || company.introduction;
      host.appendChild(lookupSection("主营 / 简介", p));
    }
  }
  const valuation = payload.valuation || {};
  if (Object.keys(valuation).length) {
    host.appendChild(
      lookupSection(
        "估值",
        lookupKv([
          ["PE", valuation.pe],
          ["PE(TTM)", valuation.pe_ttm],
          ["PB", valuation.pb],
          ["PS", valuation.ps],
          ["换手率%", valuation.turnover_rate],
          ["股息率%", valuation.dv_ratio],
          ["总市值", lookupMoney(valuation.total_mv)],
          ["流通市值", lookupMoney(valuation.circ_mv)],
        ]),
      ),
    );
  }
  const financials = payload.financials || [];
  if (financials.length) {
    host.appendChild(
      lookupSection(
        "财务摘要",
        lookupTable(
          ["报告期", "ROE", "ROA", "毛利率", "净利率", "EPS", "BPS"],
          financials.map((row) => [
            row.end_date,
            row.roe,
            row.roa,
            row.grossprofit_margin,
            row.netprofit_margin,
            row.eps,
            row.bps,
          ]),
        ),
      ),
    );
  }
  const holders = payload.holders || [];
  if (holders.length) {
    host.appendChild(
      lookupSection(
        "十大股东",
        lookupTable(
          ["股东", "持股", "占比%", "报告期"],
          holders.map((row) => [row.holder_name, lookupMoney(row.hold_amount), row.hold_ratio, row.end_date]),
        ),
      ),
    );
  }
  const dividends = payload.dividends || [];
  if (dividends.length) {
    host.appendChild(
      lookupSection(
        "分红",
        lookupTable(
          ["报告期", "方案", "派息", "送转"],
          dividends.map((row) => [row.end_date, row.div_proc, row.cash_div, row.stk_div]),
        ),
      ),
    );
  }
  const bars = payload.bars || [];
  if (bars.length) {
    host.appendChild(
      lookupSection(
        "近期日K",
        lookupTable(
          ["日期", "开", "高", "低", "收", "量"],
          bars.map((row) => [row.trade_date, row.open, row.high, row.low, row.close, lookupMoney(row.volume)]),
        ),
      ),
    );
  }
}

async function openLookupProfile(symbol) {
  const dialog = document.getElementById("lookup-dialog");
  const host = document.getElementById("lookup-dialog-body");
  setText("lookup-dialog-title", "加载中…");
  const sub = document.getElementById("lookup-dialog-sub");
  if (sub) {
    sub.hidden = true;
  }
  if (host) {
    host.innerHTML = "";
  }
  if (dialog) {
    dialog.hidden = false;
  }
  const payload = await requestJson(`/api/lookup/profile?symbol=${encodeURIComponent(symbol)}`);
  paintLookupProfile(payload);
}

document.getElementById("lookup-toggle")?.addEventListener("click", () => {
  applyLookup(!document.querySelector(".shell")?.classList.contains("lookup-collapsed"));
});
document.getElementById("lookup-q")?.addEventListener("input", scheduleLookupSearch);
document.getElementById("lookup-q")?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }
  event.preventDefault();
  const first = document.querySelector("#lookup-results button");
  if (first) {
    first.click();
  }
});
document.getElementById("lookup-dialog-close")?.addEventListener("click", closeLookupDialog);
document.getElementById("lookup-dialog")?.addEventListener("click", (event) => {
  if (event.target?.id === "lookup-dialog") {
    closeLookupDialog();
  }
});

function applySettingsPanelCollapse(panel, collapsed) {
  if (!panel) {
    return;
  }
  panel.classList.toggle("panel-collapsed", collapsed);
  const key = panel.dataset.collapseKey;
  if (key) {
    localStorage.setItem(`asqt-${key}`, collapsed ? "1" : "0");
  }
  const title = panel.querySelector("h2")?.textContent?.trim() || "区块";
  const btn = panel.querySelector(".panel-collapse-toggle");
  if (btn) {
    btn.textContent = collapsed ? "▸" : "▾";
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.setAttribute("aria-label", collapsed ? `展开${title}` : `收起${title}`);
  }
}

function initSettingsCollapsiblePanels() {
  document.querySelectorAll("#page-settings .panel[data-collapse-key]").forEach((panel) => {
    const key = panel.dataset.collapseKey;
    const saved = localStorage.getItem(`asqt-${key}`) === "1";
    applySettingsPanelCollapse(panel, saved);
    panel.querySelector(".panel-collapse-toggle")?.addEventListener("click", () => {
      applySettingsPanelCollapse(panel, !panel.classList.contains("panel-collapsed"));
    });
  });
}

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
  stock_short_reversal_topk: "股票短反转 TopK",
  stock_momentum_volume_confirm: "股票动量量能确认",
  stock_momentum_skip_month: "股票跳月动量",
  stock_holder_increase_follow: "股票股东增持跟随",
  stock_2560: "股票2560战法",
  stock_yin_arb: "股票阴线套利",
};

const PARAM_LABEL = {
  lookback: "回看天数",
  top_k: "选取数量",
  max_weight: "单票上限",
  gross_limit: "总仓上限",
  window: "均线窗口",
  vol_window: "波动窗口",
  vol_z_window: "量能窗口",
  min_volume_z: "最小量能Z",
    skip: "跳过天数",
    ma_window: "均线窗口",
    mom_lookback: "动量回看",
    event_lookback: "事件回看",
    min_momentum: "最小动量",
    ma_fast: "快线天数",
    ma_slow: "慢线天数",
    vol_fast: "快量天数",
    vol_slow: "慢量天数",
    pullback_band: "回踩带宽",
    stop_loss: "止损",
    take_profit: "止盈",
    burst_lookback: "爆量回看",
    burst_ratio: "爆量倍数",
    min_body: "最小阴线实体",
    ma_gap_max: "均线间距",
};

const PARAM_PCT_KEYS = new Set([
  "max_weight",
  "gross_limit",
  "pullback_band",
  "stop_loss",
  "take_profit",
  "min_body",
  "ma_gap_max",
]);

/** 与后端 STRATEGY_SPECS.params 对齐；策略页无 params 字段时用此展示。 */
const STRATEGY_PARAMS = {
  etf_ma_rotate: { window: 40, max_weight: 0.2, gross_limit: 0.95 },
  stock_momentum_topk: { lookback: 40, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  etf_momentum_topk: { lookback: 20, top_k: 2, max_weight: 0.2, gross_limit: 0.95 },
  stock_lowvol_momentum: { lookback: 40, vol_window: 20, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  etf_ma_momentum_filter: { ma_window: 20, mom_lookback: 20, top_k: 3, max_weight: 0.2, gross_limit: 0.95 },
  stock_short_reversal_topk: { lookback: 5, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  stock_momentum_volume_confirm: { lookback: 40, vol_z_window: 20, min_volume_z: 0.0, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  stock_momentum_skip_month: { lookback: 252, skip: 21, top_k: 5, max_weight: 0.1, gross_limit: 0.95 },
  stock_holder_increase_follow: {
    event_lookback: 20,
    lookback: 20,
    min_momentum: 0.0,
    top_k: 5,
    max_weight: 0.1,
    gross_limit: 0.95,
  },
  stock_2560: {
    ma_fast: 5,
    ma_slow: 20,
    vol_fast: 5,
    vol_slow: 90,
    pullback_band: 0.03,
    top_k: 10,
    max_weight: 0.1,
    gross_limit: 0.95,
    stop_loss: 0.08,
    take_profit: 0.2,
  },
  stock_yin_arb: {
    ma_fast: 10,
    ma_slow: 20,
    burst_lookback: 5,
    burst_ratio: 1.8,
    pullback_band: 0.025,
    min_body: 0.005,
    ma_gap_max: 0.03,
    top_k: 10,
    max_weight: 0.1,
    gross_limit: 0.95,
    stop_loss: 0,
    take_profit: 0,
  },
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

function formatEventValue(value) {
  if (value == null || value === "") {
    return "-";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return String(value);
  }
  const digits = Number.isInteger(number) ? 0 : Math.abs(number) >= 1 ? 2 : 4;
  return number.toLocaleString("zh-CN", { maximumFractionDigits: digits });
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
  strategyVersionRows = Array.isArray(rows) ? rows.slice() : [];
  body.innerHTML = "";
  if (!strategyVersionRows.length) {
    strategySelected.clear();
    strategyPage = 1;
    paintStrategyPager(0, 1, 1);
    syncStrategyBatchUi();
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "table-empty";
    td.textContent = "还没有策略版本。勾选后点「重跑回测」或命令行 asqt research-backtest --strategy all。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  const known = new Set(strategyVersionRows.map((row) => row.strategy_id));
  for (const id of [...strategySelected]) {
    if (!known.has(id)) {
      strategySelected.delete(id);
    }
  }
  const total = strategyVersionRows.length;
  const pages = Math.max(1, Math.ceil(total / STRATEGY_PAGE_SIZE));
  if (strategyPage > pages) {
    strategyPage = pages;
  }
  if (strategyPage < 1) {
    strategyPage = 1;
  }
  const start = (strategyPage - 1) * STRATEGY_PAGE_SIZE;
  const pageRows = strategyVersionRows.slice(start, start + STRATEGY_PAGE_SIZE);
  pageRows.forEach((row, offset) => {
    const index = start + offset;
    const tr = document.createElement("tr");
    tr.className = "strategy-row";
    tr.dataset.strategyId = row.strategy_id;
    tr.dataset.status = row.status || "";
    tr.dataset.index = String(index);
    if (strategySelected.has(row.strategy_id)) {
      tr.classList.add("is-selected");
    }
    const checkTd = document.createElement("td");
    checkTd.className = "strategy-check-col";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "strategy-row-check";
    check.checked = strategySelected.has(row.strategy_id);
    check.setAttribute("aria-label", `选择 ${STRATEGY_LABEL[row.strategy_id] || row.strategy_id}`);
    check.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleStrategySelection(row.strategy_id, index, { shiftKey: event.shiftKey, force: check.checked });
    });
    checkTd.appendChild(check);
    tr.appendChild(checkTd);
    appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id);
    appendCell(tr, row.version || "v1");
    appendCell(tr, STRATEGY_STATUS_LABEL[row.status] || row.status || "-", { tone: toneForStrategy(row.status) });
    const paramsLabel = formatParameterSetDisplay(row);
    appendCell(tr, paramsLabel, { title: paramsLabel });
    appendCell(tr, row.code_version || "-");
    appendCell(tr, row.effective_date || "-");
    tr.addEventListener("click", (event) => {
      if (event.target.closest("input,button,a,label")) {
        return;
      }
      toggleStrategySelection(row.strategy_id, index, { shiftKey: event.shiftKey });
    });
    body.appendChild(tr);
  });
  paintStrategyPager(total, strategyPage, pages);
  syncStrategyBatchUi();
  containPageWidth();
}

const STRATEGY_PAGE_SIZE = 10;
let strategyVersionRows = [];
let strategySelected = new Set();
let strategyLastIndex = -1;
let strategyPage = 1;

function strategyPageSlice() {
  const start = (strategyPage - 1) * STRATEGY_PAGE_SIZE;
  return strategyVersionRows.slice(start, start + STRATEGY_PAGE_SIZE);
}

function paintStrategyPager(total, page, pages) {
  setText(
    "strategy-page-label",
    total ? `共 ${total} 条 · ${page} / ${pages} · 每页 ${STRATEGY_PAGE_SIZE}` : "共 0 条",
  );
  const prev = document.getElementById("strategy-prev");
  const next = document.getElementById("strategy-next");
  if (prev) {
    prev.disabled = page <= 1 || total === 0;
  }
  if (next) {
    next.disabled = page >= pages || total === 0;
  }
}

function strategyStatusById(strategyId) {
  const row = strategyVersionRows.find((item) => item.strategy_id === strategyId);
  return row?.status || "";
}

function toggleStrategySelection(strategyId, index, { shiftKey = false, force } = {}) {
  if (!strategyId) {
    return;
  }
  const selecting = force == null ? !strategySelected.has(strategyId) : Boolean(force);
  if (shiftKey && strategyLastIndex >= 0 && index != null) {
    const lo = Math.min(strategyLastIndex, index);
    const hi = Math.max(strategyLastIndex, index);
    for (let i = lo; i <= hi; i += 1) {
      const id = strategyVersionRows[i]?.strategy_id;
      if (!id) {
        continue;
      }
      if (selecting) {
        strategySelected.add(id);
      } else {
        strategySelected.delete(id);
      }
    }
  } else if (selecting) {
    strategySelected.add(strategyId);
  } else {
    strategySelected.delete(strategyId);
  }
  if (index != null) {
    strategyLastIndex = index;
  }
  document.querySelectorAll("#strategy-body tr.strategy-row").forEach((tr) => {
    const id = tr.dataset.strategyId;
    const on = strategySelected.has(id);
    tr.classList.toggle("is-selected", on);
    const box = tr.querySelector(".strategy-row-check");
    if (box) {
      box.checked = on;
    }
  });
  syncStrategyBatchUi();
}

function syncStrategyBatchUi() {
  const count = strategySelected.size;
  setText("strategy-batch-count", `已选 ${count}`);
  const all = document.getElementById("strategy-select-all");
  if (all) {
    const pageIds = strategyPageSlice().map((row) => row.strategy_id);
    const pageSelected = pageIds.filter((id) => strategySelected.has(id)).length;
    all.checked = pageIds.length > 0 && pageSelected === pageIds.length;
    all.indeterminate = pageSelected > 0 && pageSelected < pageIds.length;
  }
  const selected = [...strategySelected];
  const canAdmit = selected.some((id) => strategyStatusById(id) === "candidate");
  const canRemove = selected.some((id) => strategyStatusById(id) === "paper");
  const canResume = selected.some((id) => strategyStatusById(id) === "paused");
  const admitBtn = document.getElementById("strategy-batch-admit");
  const removeBtn = document.getElementById("strategy-batch-remove");
  const resumeBtn = document.getElementById("strategy-batch-resume");
  const runBtn = document.getElementById("strategy-run");
  if (admitBtn) {
    admitBtn.disabled = !canAdmit || backtestBusy || paperBusy;
  }
  if (removeBtn) {
    removeBtn.disabled = !canRemove || backtestBusy || paperBusy;
  }
  if (resumeBtn) {
    resumeBtn.disabled = !canResume || backtestBusy || paperBusy;
  }
  if (runBtn && !backtestBusy && !paperBusy) {
    runBtn.disabled = count === 0;
    runBtn.title = count === 0 ? "请先勾选要重跑回测的策略" : "对勾选策略重跑回测";
  }
}

function showStrategyBatchError(message) {
  const el = document.getElementById("strategy-batch-error");
  if (!el) {
    return;
  }
  el.hidden = !message;
  el.textContent = message || "";
}

async function runStrategyBatch(action, allowedStatuses, emptyHint) {
  const reasonInput = document.getElementById("strategy-batch-reason");
  const reason = (reasonInput?.value || "").trim();
  const result = document.getElementById("strategy-life-result");
  showStrategyBatchError("");
  if (!reason) {
    showStrategyBatchError("请填写原因（不能全是空格）");
    reasonInput?.focus();
    return;
  }
  const targets = [...strategySelected].filter((id) => allowedStatuses.includes(strategyStatusById(id)));
  if (!targets.length) {
    showStrategyBatchError(emptyHint);
    return;
  }
  if (result) {
    result.hidden = false;
    result.textContent = `批量处理中 0/${targets.length}…`;
  }
  const ok = [];
  const failed = [];
  for (let i = 0; i < targets.length; i += 1) {
    const strategyId = targets[i];
    if (result) {
      result.textContent = `批量处理中 ${i + 1}/${targets.length}… ${STRATEGY_LABEL[strategyId] || strategyId}`;
    }
    try {
      const payload = await requestJson(`/api/strategies/${encodeURIComponent(strategyId)}/lifecycle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reason }),
      });
      ok.push(`${STRATEGY_LABEL[payload.strategy_id] || payload.strategy_id}→${STRATEGY_STATUS_LABEL[payload.status] || payload.status}`);
    } catch (error) {
      failed.push(`${STRATEGY_LABEL[strategyId] || strategyId}：${error.message || "失败"}`);
    }
  }
  const summary = [
    ok.length ? `成功 ${ok.length}：${ok.join("；")}` : "",
    failed.length ? `失败 ${failed.length}：${failed.join("；")}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  if (result) {
    result.textContent = summary || "无变更";
  }
  showToast(failed.length ? `批量完成（失败 ${failed.length}）` : `批量完成 ${ok.length} 条`, failed.length ? "warn" : "ok");
  strategySelected.clear();
  if (reasonInput) {
    reasonInput.value = "";
  }
  await loadStrategyPage();
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
    td.colSpan = 8;
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
    appendCell(tr, formatDateTime(row.created_at) || "-");
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
  loadLabRuleEngine().catch((error) => showToast(error.message || "加载规则引擎失败", "warn"));
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

const labRuleState = {
  strategyId: "",
  schema: [],
  presets: [],
  editId: "",
  editable: false,
};

function labRuleStrategyId() {
  return document.getElementById("lab-rule-strategy")?.value || "etf_ma_momentum_filter";
}

function labRuleDialogOpen() {
  const dialog = document.getElementById("lab-rule-dialog");
  return Boolean(dialog && !dialog.hidden);
}

function openLabRuleDialog(title, hint) {
  const dialog = document.getElementById("lab-rule-dialog");
  const heading = document.getElementById("lab-rule-dialog-title");
  if (heading) {
    heading.textContent = title;
  }
  if (dialog) {
    dialog.hidden = false;
  }
  setHint("lab-rule-hint", hint || "");
  document.getElementById("lab-rule-fields")?.querySelector("input")?.focus();
}

function closeLabRuleDialog() {
  const dialog = document.getElementById("lab-rule-dialog");
  if (dialog) {
    dialog.hidden = true;
  }
}

function fillLabRuleFields(params) {
  const host = document.getElementById("lab-rule-fields");
  if (!host) {
    return;
  }
  const values = params && typeof params === "object" ? params : {};
  host.innerHTML = "";
  for (const field of labRuleState.schema) {
    const label = document.createElement("label");
    label.className = "filter-inline";
    const input = document.createElement("input");
    input.id = `lab-rule-${field.key}`;
    input.name = field.key;
    input.type = "number";
    input.required = true;
    input.step = field.kind === "integer" ? "1" : "any";
    const fallback = values[field.key] ?? field.default;
    input.value = fallback == null ? "" : String(fallback);
    label.append(document.createTextNode(PARAM_LABEL[field.key] || field.key), input);
    host.appendChild(label);
  }
}

function readLabRuleFields() {
  const params = {};
  for (const field of labRuleState.schema) {
    const input = document.getElementById(`lab-rule-${field.key}`);
    const raw = input?.value?.trim();
    if (raw === "" || raw == null) {
      throw new Error(`请填写${PARAM_LABEL[field.key] || field.key}`);
    }
    const number = Number(raw);
    if (Number.isNaN(number)) {
      throw new Error(`${PARAM_LABEL[field.key] || field.key} 无效`);
    }
    params[field.key] = field.kind === "integer" ? Math.round(number) : number;
  }
  return params;
}

function renderLabRuleEngine() {
  const body = document.getElementById("lab-rule-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const needle = (document.getElementById("lab-rule-q")?.value || "").trim().toLowerCase();
  const list = needle
    ? labRuleState.presets.filter((row) => {
        const hay = `${row.short_id || ""} ${row.parameter_set_id}`.toLowerCase();
        return hay.includes(needle);
      })
    : labRuleState.presets;
  if (!list.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty-hint";
    td.textContent = "暂无参数组。";
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    for (const row of list) {
      const tr = document.createElement("tr");
      if (row.parameter_set_id === labRuleState.editId) {
        tr.classList.add("is-active");
      }
      appendCell(tr, row.short_id || row.parameter_set_id, {
        title: row.parameter_set_id,
      });
      appendCell(tr, formatParamsChinese(row.params, row.parameter_set_id));
      appendCell(tr, row.source === "custom" ? "自定义" : "内置", {
        tone: row.source === "custom" ? "accent" : "muted",
      });
      if (row.is_default) {
        appendCell(tr, "默认", { tone: "ok" });
      } else {
        appendCell(tr, "—", { tone: "muted" });
      }
      const td = document.createElement("td");
      const actions = document.createElement("div");
      actions.className = "lab-rule-actions";
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "secondary";
      editBtn.textContent = "编辑";
      editBtn.addEventListener("click", () => {
        labRuleState.editId = row.parameter_set_id;
        labRuleState.editable = Boolean(row.editable);
        fillLabRuleFields(row.params);
        openLabRuleDialog(
          row.editable ? "编辑参数组" : "另存参数组",
          row.editable
            ? `正在编辑 ${row.parameter_set_id}`
            : `内置组 ${row.parameter_set_id}：保存将另存为新组`,
        );
        renderLabRuleEngine();
      });
      const defaultBtn = document.createElement("button");
      defaultBtn.type = "button";
      defaultBtn.className = "secondary";
      defaultBtn.textContent = "设为默认";
      defaultBtn.disabled = Boolean(row.is_default);
      defaultBtn.addEventListener("click", () => {
        setLabRuleDefault(row).catch((error) => showToast(error.message || "设置默认失败", "block"));
      });
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "secondary";
      delBtn.textContent = "删除";
      delBtn.disabled = !row.editable;
      delBtn.title = row.editable ? "删除自定义参数组" : "内置参数组不能删除";
      delBtn.addEventListener("click", () => {
        deleteLabRule(row).catch((error) => showToast(error.message || "删除失败", "block"));
      });
      actions.append(editBtn, defaultBtn, delBtn);
      td.appendChild(actions);
      tr.appendChild(td);
      body.appendChild(tr);
    }
  }
  const sid = labRuleState.strategyId;
  setText(
    "lab-rule-meta",
    `${STRATEGY_LABEL[sid] || sid} · ${list.length} 组 · 自定义 ${list.filter((row) => row.source === "custom").length}`,
  );
}

async function loadLabRuleEngine(strategyId = labRuleStrategyId()) {
  const payload = await requestJson(`/api/paper/lab/presets?strategy_id=${encodeURIComponent(strategyId)}`);
  labRuleState.strategyId = strategyId;
  labRuleState.schema = payload.schema || [];
  labRuleState.presets = payload.presets || [];
  const current = labRuleState.presets.find((row) => row.parameter_set_id === labRuleState.editId);
  if (!current) {
    labRuleState.editId = "";
    labRuleState.editable = false;
  }
  if (labRuleDialogOpen()) {
    const fallback = current || labRuleState.presets.find((row) => row.is_default) || labRuleState.presets[0];
    fillLabRuleFields(fallback?.params);
  }
  renderLabRuleEngine();
  if (isPaperLabSoloMode() && getPaperSelectedStrategyIds()[0] === strategyId) {
    loadPaperLabPresets(strategyId).catch(() => {});
  }
}

async function saveLabRule(event) {
  event.preventDefault();
  const strategyId = labRuleStrategyId();
  const params = readLabRuleFields();
  const replaceId = labRuleState.editable ? labRuleState.editId : "";
  const payload = await requestJson("/api/paper/lab/presets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      strategy_id: strategyId,
      params,
      replace_id: replaceId || null,
    }),
  });
  labRuleState.editId = payload.preset?.parameter_set_id || "";
  labRuleState.editable = true;
  showToast(`已保存 ${labRuleState.editId}`, "ok");
  closeLabRuleDialog();
  await loadLabRuleEngine(strategyId);
}

async function setLabRuleDefault(row) {
  const strategyId = labRuleStrategyId();
  await requestJson("/api/paper/lab/defaults", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      strategy_id: strategyId,
      params: row.params,
      parameter_set_id: row.parameter_set_id,
    }),
  });
  showToast(`已设默认：${row.parameter_set_id}`, "ok");
  await loadLabRuleEngine(strategyId);
}

async function deleteLabRule(row) {
  if (!row?.editable) {
    showToast("内置参数组不能删除", "warn");
    return;
  }
  const ok = await confirmDialog(`删除自定义参数组 ${row.parameter_set_id}？`);
  if (!ok) {
    return;
  }
  const strategyId = labRuleStrategyId();
  await requestJson(
    `/api/paper/lab/presets?strategy_id=${encodeURIComponent(strategyId)}&parameter_set_id=${encodeURIComponent(row.parameter_set_id)}`,
    { method: "DELETE" },
  );
  if (labRuleState.editId === row.parameter_set_id) {
    labRuleState.editId = "";
    labRuleState.editable = false;
  }
  showToast("已删除参数组", "ok");
  await loadLabRuleEngine(strategyId);
}

document.getElementById("lab-rule-strategy")?.addEventListener("change", () => {
  labRuleState.editId = "";
  labRuleState.editable = false;
  const q = document.getElementById("lab-rule-q");
  if (q) {
    q.value = "";
  }
  loadLabRuleEngine().catch((error) => showToast(error.message || "加载规则失败", "block"));
});

document.getElementById("lab-rule-q")?.addEventListener("input", () => {
  renderLabRuleEngine();
});

document.getElementById("lab-rule-new")?.addEventListener("click", () => {
  labRuleState.editId = "";
  labRuleState.editable = false;
  fillLabRuleFields();
  openLabRuleDialog("新建参数组", "填写参数后保存为新组");
  renderLabRuleEngine();
});

document.getElementById("lab-rule-dialog")?.addEventListener("click", (event) => {
  if (event.target?.id === "lab-rule-dialog") {
    closeLabRuleDialog();
  }
});
document.getElementById("lab-rule-dialog-close")?.addEventListener("click", () => closeLabRuleDialog());
document.getElementById("lab-rule-dialog-cancel")?.addEventListener("click", () => closeLabRuleDialog());

document.getElementById("lab-rule-form")?.addEventListener("submit", (event) => {
  saveLabRule(event).catch((error) => showToast(error.message || "保存失败", "block"));
});

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

function renderDecisions(payload) {
  const body = document.getElementById("review-decisions-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const items = payload?.items || [];
  setText(
    "review-decisions-hint",
    items.length
      ? `最近 ${items.length} 条决策（待结算 / 已结算）。`
      : "尚无决策日志。跑一轮模拟日终后会出现「待结算 → 已结算」。",
  );
  if (!items.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "table-empty";
    td.textContent = "暂无决策记录";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of items) {
    const tr = document.createElement("tr");
    const ret = row.outcome?.session_return;
    const status = row.status || "";
    const rating = row.rating || "";
    appendCell(tr, row.signal_date || "-");
    appendCell(tr, DECISION_STATUS_LABEL[status] || status || "-", {
      tone: status === "pending" ? "warn" : status === "resolved" ? "ok" : "muted",
    });
    appendCell(tr, DECISION_RATING_LABEL[rating] || rating || "-", {
      tone:
        rating === "Buy" || rating === "Overweight"
          ? "ok"
          : rating === "Sell" || rating === "Underweight"
            ? "block"
            : rating === "REVIEW"
              ? "warn"
              : "muted",
    });
    appendCell(tr, row.fill_date || "-");
    appendCell(tr, ret == null ? "-" : formatPct(ret), {
      className: ret == null ? "num" : pnlClass(ret),
    });
    appendCell(tr, row.lesson || "-");
    body.appendChild(tr);
  }
}

let reviewBusy = false;

async function loadReviewPage() {
  if (reviewBusy) {
    return;
  }
  const select = document.getElementById("review-strategy");
  const strategyId = select?.value || "etf_ma_rotate";
  reviewBusy = true;
  setText("review-hint", "正在按日重算归因，请稍候…");
  try {
    const [payload, decisions] = await Promise.all([
      requestJson(`/api/research/attribution?strategy_id=${encodeURIComponent(strategyId)}`),
      requestJson(`/api/decisions?strategy_id=${encodeURIComponent(strategyId)}&limit=30`).catch(() => ({
        items: [],
      })),
    ]);
    renderAttribution(payload);
    renderDecisions(decisions);
  } finally {
    reviewBusy = false;
  }
}

let backtestTimer = 0;
let watchedBacktestId = "";
let backtestBusy = false;
let paperBusy = false;
let paperStopping = false;
let syncInFlight = false;

function syncPaperStopBtn() {
  const btn = document.getElementById("paper-run-stop");
  if (!btn) {
    return;
  }
  const show = Boolean(paperBusy);
  btn.hidden = !show;
  btn.disabled = !show;
  btn.textContent = paperStopping ? "终止中…" : "终止";
  btn.title = paperStopping ? "正在终止当前模拟" : "终止当前这次跑模拟，已写出的快照会留下";
}

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
    btn.classList.toggle("is-locked", Boolean(on));
  });
  root.querySelectorAll(".asqt-select-search").forEach((input) => {
    setControlReadonly(input, on);
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
  const parallelBtn = document.getElementById("paper-run-parallel");
  setControlReadonly(document.getElementById("strategy-run"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-batch-admit"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-batch-remove"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-batch-resume"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-batch-reason"), locked, lockTitle);
  setControlReadonly(document.getElementById("strategy-select-all"), locked, lockTitle);
  setControlReadonly(runBtn, locked, lockTitle);
  setControlReadonly(parallelBtn, locked, lockTitle);
  if (runBtn && !backtestBusy) {
    runBtn.textContent = paperBusy ? "运行中…" : "跑模拟";
  }
  if (parallelBtn && !backtestBusy) {
    parallelBtn.textContent = paperBusy ? "运行中…" : "并行模式";
  }
  setControlReadonly(document.getElementById("paper-reset"), locked, lockTitle);
  setControlReadonly(document.getElementById("paper-clear-halt"), locked, lockTitle);
  setControlReadonly(document.getElementById("paper-run-days"), paperBusy, lockTitle);
  setControlReadonly(document.getElementById("paper-run-start"), paperBusy, lockTitle);
  setControlReadonly(document.getElementById("paper-run-end"), paperBusy, lockTitle);
  lockSelectTriggers(document.getElementById("paper-run-form"), locked);
  syncPaperStopBtn();
  syncStrategyBatchUi();
  refreshHeaderActionLocks();
}

function setBacktestBusy(busy) {
  backtestBusy = Boolean(busy);
  applyTradeLocks();
}

function setPaperBusy(busy) {
  paperBusy = Boolean(busy);
  if (!paperBusy) {
    paperStopping = false;
  }
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

const strategyRunBtn = document.getElementById("strategy-run");
if (strategyRunBtn) {
  strategyRunBtn.addEventListener("click", async () => {
    const result = document.getElementById("strategy-run-result");
    const ids = [...strategySelected];
    showStrategyBatchError("");
    if (!ids.length) {
      showStrategyBatchError("请先勾选要重跑回测的策略");
      return;
    }
    if (result) {
      result.hidden = false;
      result.textContent = `回测入队中…（${ids.length} 个策略）`;
    }
    setBacktestBusy(true);
    try {
      const payload = await requestJson("/api/research/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_ids: ids }),
      });
      showToast(`回测已在后台开始（${ids.length}）`, "ok");
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

document.getElementById("strategy-select-all")?.addEventListener("change", (event) => {
  const on = Boolean(event.target.checked);
  const pageRows = strategyPageSlice();
  for (const row of pageRows) {
    if (on) {
      strategySelected.add(row.strategy_id);
    } else {
      strategySelected.delete(row.strategy_id);
    }
  }
  strategyLastIndex = pageRows.length
    ? (strategyPage - 1) * STRATEGY_PAGE_SIZE + pageRows.length - 1
    : -1;
  document.querySelectorAll("#strategy-body tr.strategy-row").forEach((tr) => {
    const id = tr.dataset.strategyId;
    const selected = strategySelected.has(id);
    tr.classList.toggle("is-selected", selected);
    const box = tr.querySelector(".strategy-row-check");
    if (box) {
      box.checked = selected;
    }
  });
  syncStrategyBatchUi();
});

document.getElementById("strategy-prev")?.addEventListener("click", () => {
  if (strategyPage <= 1) {
    return;
  }
  strategyPage -= 1;
  renderStrategyVersions(strategyVersionRows);
});

document.getElementById("strategy-next")?.addEventListener("click", () => {
  const pages = Math.max(1, Math.ceil(strategyVersionRows.length / STRATEGY_PAGE_SIZE));
  if (strategyPage >= pages) {
    return;
  }
  strategyPage += 1;
  renderStrategyVersions(strategyVersionRows);
});

document.getElementById("strategy-batch-admit")?.addEventListener("click", () => {
  runStrategyBatch("paper", ["candidate"], "请先勾选状态为「候选」的策略").catch((error) => {
    showToast(error.message || "批量准入失败", "block");
  });
});

document.getElementById("strategy-batch-remove")?.addEventListener("click", () => {
  runStrategyBatch("pause", ["paper"], "请先勾选状态为「模拟」的策略（移出后为暂停）").catch((error) => {
    showToast(error.message || "批量移出失败", "block");
  });
});

document.getElementById("strategy-batch-resume")?.addEventListener("click", () => {
  runStrategyBatch("resume", ["paused"], "请先勾选状态为「暂停」的策略").catch((error) => {
    showToast(error.message || "批量恢复失败", "block");
  });
});

document.getElementById("strategy-batch-reason")?.addEventListener("input", () => {
  if (document.getElementById("strategy-batch-error") && !document.getElementById("strategy-batch-error").hidden) {
    const reason = (document.getElementById("strategy-batch-reason")?.value || "").trim();
    if (reason) {
      showStrategyBatchError("");
    }
  }
});

function getPaperSelectedStrategyIds() {
  const select = document.getElementById("paper-run-id");
  if (!select) {
    return Object.keys(STRATEGY_LABEL);
  }
  return [...select.options]
    .filter((option) => option.selected && option.value && option.value !== "all")
    .map((option) => option.value);
}

/** Match backend split_parallel_cash: floor share each, remainder on first. */
function splitPortfolioCash(total, n) {
  const count = Math.max(0, Math.floor(Number(n) || 0));
  if (count <= 0) {
    return [];
  }
  const amount = Number(total) || 0;
  const base = Math.floor(amount / count);
  const shares = Array.from({ length: count }, () => base);
  shares[0] = amount - base * (count - 1);
  return shares;
}

function plannedPaperBookCash(strategyId, selectedIds) {
  const ids = Array.isArray(selectedIds) && selectedIds.length
    ? selectedIds
    : getPaperSelectedStrategyIds();
  if (!ids.length) {
    return 0;
  }
  const total = Number(lastPaperConfig?.initial_cash) || 0;
  const shares = splitPortfolioCash(total, ids.length);
  const idx = ids.indexOf(strategyId);
  return idx >= 0 ? shares[idx] : 0;
}

/** Empty books (sessions===0): show planned split of portfolio cash for UI. */
function paperDisplayBoard(id, board, selectedIds) {
  const src = board && typeof board === "object" ? board : {};
  if (Number(src.sessions || 0) > 0) {
    return src;
  }
  const planned = plannedPaperBookCash(id, selectedIds);
  return {
    ...src,
    initial_cash: planned,
    end_asset: planned,
    cash: planned,
    peak_asset: planned,
  };
}

function paperStrategyRequestBody(extra = {}) {
  const ids = getPaperSelectedStrategyIds();
  if (!ids.length) {
    return { error: "请至少选择一个策略" };
  }
  const allIds = Object.keys(STRATEGY_LABEL);
  if (ids.length === allIds.length && allIds.every((id) => ids.includes(id))) {
    return { ...extra, strategy_id: "all" };
  }
  return { ...extra, strategy_ids: ids };
}

let paperLabDefaults = {};
let paperLabPresets = [];

function isPaperLabSoloMode() {
  const ids = getPaperSelectedStrategyIds();
  return ids.length === 1;
}

function selectedPaperLabPreset() {
  const select = document.getElementById("paper-lab-preset");
  if (!select || !select.value) {
    return null;
  }
  return paperLabPresets.find((row) => row.parameter_set_id === select.value) || null;
}

function syncPaperLabParamsUi() {
  const row = document.getElementById("paper-lab-row");
  const select = document.getElementById("paper-lab-preset");
  const btn = document.getElementById("paper-lab-set-default");
  const solo = isPaperLabSoloMode();
  const lockTip = "多策略时不可改参，统一使用默认参数组";
  if (row) {
    row.hidden = false;
    row.classList.toggle("is-lab-locked", !solo);
  }
  if (select) {
    select.disabled = !solo;
    select.setAttribute("aria-disabled", solo ? "false" : "true");
    select.title = solo
      ? "仅单策略顺序模拟可改参；多策略/并行强制默认参数组"
      : lockTip;
  }
  if (btn) {
    btn.disabled = !solo;
    btn.setAttribute("aria-disabled", solo ? "false" : "true");
    btn.title = solo ? "把当前参数组设为多策略/并行时的默认钉扎" : lockTip;
  }
  lockSelectTriggers(row, !solo);
  if (row && !solo) {
    row.querySelectorAll(".asqt-select-trigger").forEach((el) => {
      el.title = lockTip;
    });
  }
  if (!solo || !select) {
    return;
  }
  const sid = getPaperSelectedStrategyIds()[0];
  loadPaperLabPresets(sid).catch((error) => showToast(error.message || "加载实验室参数失败", "warn"));
}

async function loadPaperLabPresets(strategyId) {
  const select = document.getElementById("paper-lab-preset");
  if (!select) {
    return;
  }
  const [presetsPayload, defaultsPayload] = await Promise.all([
    requestJson(`/api/paper/lab/presets?strategy_id=${encodeURIComponent(strategyId)}`),
    requestJson("/api/paper/lab/defaults").catch(() => ({ defaults: {} })),
  ]);
  paperLabDefaults = defaultsPayload.defaults || {};
  paperLabPresets = presetsPayload.presets || [];
  const defaultId = paperLabDefaults[strategyId]?.parameter_set_id
    || presetsPayload.default?.parameter_set_id
    || paperLabPresets[0]?.parameter_set_id
    || "";
  // Ensure default pin appears in the list even if not in hardcoded presets.
  if (
    paperLabDefaults[strategyId]
    && !paperLabPresets.some((row) => row.parameter_set_id === paperLabDefaults[strategyId].parameter_set_id)
  ) {
    paperLabPresets = [paperLabDefaults[strategyId], ...paperLabPresets];
  }
  const prev = select.value;
  select.innerHTML = "";
  for (const row of paperLabPresets) {
    const opt = document.createElement("option");
    opt.value = row.parameter_set_id;
    const mark = row.parameter_set_id === defaultId ? "（默认）" : "";
    const shown = row.short_id || row.parameter_set_id;
    opt.textContent = `${shown}${mark}`;
    opt.title = row.parameter_set_id;
    select.appendChild(opt);
  }
  select.value = paperLabPresets.some((row) => row.parameter_set_id === prev)
    ? prev
    : defaultId;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

async function setPaperLabDefaultFromUi() {
  const ids = getPaperSelectedStrategyIds();
  if (ids.length !== 1) {
    showToast("请先只选一个策略，再设默认参数组", "warn");
    return;
  }
  const preset = selectedPaperLabPreset();
  if (!preset) {
    showToast("请选择参数组", "warn");
    return;
  }
  await requestJson("/api/paper/lab/defaults", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      strategy_id: ids[0],
      params: preset.params,
      parameter_set_id: preset.parameter_set_id,
    }),
  });
  showToast(`已设默认：${preset.parameter_set_id}`, "ok");
  await loadPaperLabPresets(ids[0]);
}

const paperRunId = document.getElementById("paper-run-id");
if (paperRunId) {
  paperRunId.addEventListener("change", () => {
    syncPaperLabParamsUi();
    loadOrders().catch((error) => showToast(error.message || "加载模拟账户失败", "block"));
  });
}

document.getElementById("paper-lab-set-default")?.addEventListener("click", () => {
  setPaperLabDefaultFromUi().catch((error) => showToast(error.message || "设置默认失败", "block"));
});

// Initial lab params visibility (after DOM ready).
queueMicrotask(() => syncPaperLabParamsUi());

let paperRunTimer = 0;
let watchedPaperRunId = "";

function paperProgressText(row) {
  const pct = row.progress_pct == null || row.progress_pct === "" ? "" : `${Number(row.progress_pct)}%`;
  const label = row.progress_label || "";
  if (row.status === "queued") {
    return pct ? `模拟排队 ${pct}` : "模拟已入队";
  }
  if (row.status === "cancelled") {
    return row.fail_reason || label || "已终止跑模拟";
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
  const cancelled = row.status === "cancelled";
  const message = paperProgressText(row);
  setText("paper-account-hint", message);
  showToast(
    ok ? "模拟已跑完" : cancelled ? "已终止跑模拟" : message || "模拟未完整",
    ok ? "ok" : partial || cancelled ? "warn" : "block",
  );
  loadOrders().catch(() => {});
}

let paperLiveRefreshInFlight = false;
let paperLiveRefreshQueued = false;
let lastPaperLiveKey = "";
let lastPaperLiveAt = 0;

async function refreshPaperBooksDuringRun() {
  if (paperLiveRefreshInFlight) {
    paperLiveRefreshQueued = true;
    return;
  }
  paperLiveRefreshInFlight = true;
  try {
    const selected = getPaperSelectedStrategyIds();
    const ids = selected.length ? selected : Object.keys(STRATEGY_LABEL);
    const [kill, paperGate, ...accounts] = await Promise.all([
      requestJson("/api/ops/kill-switch"),
      requestJson("/api/ops/paper-trading"),
      ...ids.map((id) => requestJson(`/api/paper/account?strategy_id=${encodeURIComponent(id)}`)),
    ]);
    if (!watchedPaperRunId) {
      return;
    }
    paperKillState = kill;
    paperGateState = paperGate;
    paperBooks = {};
    for (const account of accounts) {
      if (account?.strategy_id) {
        paperBooks[account.strategy_id] = account;
      }
    }
    const bookIds = paperBookIds();
    if (
      !paperFocusId
      || (paperFocusId !== PAPER_OVERVIEW_ID && !paperBooks[paperFocusId])
    ) {
      paperFocusId = bookIds.length > 1 ? PAPER_OVERVIEW_ID : bookIds[0] || null;
    }
    await showPaperFocus({ skipOrders: true });
  } finally {
    paperLiveRefreshInFlight = false;
    if (paperLiveRefreshQueued && watchedPaperRunId) {
      paperLiveRefreshQueued = false;
      refreshPaperBooksDuringRun().catch(() => {});
    } else {
      paperLiveRefreshQueued = false;
    }
  }
}

function watchPaperRun(runId) {
  watchedPaperRunId = runId;
  lastPaperLiveKey = "";
  lastPaperLiveAt = 0;
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
        const parallelBtn = document.getElementById("paper-run-parallel");
        const pct = row.progress_pct == null ? "" : ` ${row.progress_pct}%`;
        if (runBtn && paperBusy) {
          runBtn.textContent = row.status === "queued" ? "排队中…" : `运行中…${pct}`;
        }
        if (parallelBtn && paperBusy) {
          parallelBtn.textContent = row.status === "queued" ? "排队中…" : `运行中…${pct}`;
        }
        if (row.status === "running" || row.status === "queued") {
          const key = `${row.status}:${row.progress_done || 0}:${row.progress_label || ""}`;
          const now = Date.now();
          if (key !== lastPaperLiveKey && now - lastPaperLiveAt >= 1200) {
            lastPaperLiveKey = key;
            lastPaperLiveAt = now;
            refreshPaperBooksDuringRun().catch(() => {});
          }
        }
        if (row.status === "success" || row.status === "failed" || row.status === "partial" || row.status === "cancelled") {
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
    startPaperRunFromUi("sequential");
  });
}

const paperRunStop = document.getElementById("paper-run-stop");
if (paperRunStop) {
  paperRunStop.addEventListener("click", async () => {
    if (!paperBusy || !watchedPaperRunId || paperStopping) {
      return;
    }
    paperStopping = true;
    syncPaperStopBtn();
    try {
      await requestJson(`/api/paper/run/${encodeURIComponent(watchedPaperRunId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "用户终止跑模拟" }),
      });
      showToast("已请求终止，当前交易日结束后停止", "warn");
    } catch (error) {
      paperStopping = false;
      syncPaperStopBtn();
      showToast(error.message || "终止失败", "block");
    }
  });
}

const paperRunParallel = document.getElementById("paper-run-parallel");
if (paperRunParallel) {
  paperRunParallel.addEventListener("click", () => {
    startPaperRunFromUi("parallel");
  });
}

async function startPaperRunFromUi(mode) {
  if (paperBusy || backtestBusy) {
    showToast("模拟盘运行中，请勿重复提交", "warn");
    return;
  }
  setPaperBusy(true);
  const parallel = mode === "parallel";
  setText("paper-account-hint", parallel ? "并行模拟入队中…请勿重复提交。" : "模拟盘入队中…请勿重复提交。");
  try {
    const range = paperRunDateRange();
    if (range.error) {
      setPaperBusy(false);
      setText("paper-account-hint", range.error);
      showToast(range.error, "warn");
      return;
    }
    const body = paperStrategyRequestBody({
      days: Math.min(
        paperRunDaysMax,
        Math.max(1, Number(document.getElementById("paper-run-days").value) || 20),
      ),
      mode: parallel ? "parallel" : "sequential",
    });
    if (range.start_date && range.end_date) {
      body.start_date = range.start_date;
      body.end_date = range.end_date;
    }
    if (body.error) {
      setPaperBusy(false);
      setText("paper-account-hint", body.error);
      showToast(body.error, "warn");
      return;
    }
    const solo = Array.isArray(body.strategy_ids) && body.strategy_ids.length === 1;
    if (!parallel && solo) {
      const preset = selectedPaperLabPreset();
      if (preset) {
        body.params = preset.params;
        body.parameter_set_id = preset.parameter_set_id;
      }
    }
    const payload = await requestJson("/api/paper/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const pinHint = payload.parameter_set_ids
      ? ` · 参数 ${Object.values(payload.parameter_set_ids).join(", ")}`
      : "";
    showToast((parallel ? "并行模拟已在后台开始" : "模拟已在后台开始") + pinHint, "ok");
    watchPaperRun(payload.run_id);
  } catch (error) {
    setPaperBusy(false);
    setText("paper-account-hint", `模拟失败：${error.message}`);
    showToast(error.message || "模拟失败", "block");
  }
}

const paperResetBtn = document.getElementById("paper-reset");
if (paperResetBtn) {
  paperResetBtn.addEventListener("click", async () => {
    if (paperBusy || backtestBusy) {
      showToast(paperBusy ? "模拟盘运行中，请勿重复提交" : "回测进行中，请稍候", "warn");
      return;
    }
    const body = paperStrategyRequestBody();
    if (body.error) {
      showToast(body.error, "warn");
      return;
    }
    const selectedIds = body.strategy_ids || Object.keys(STRATEGY_LABEL);
    const selectedLabel =
      body.strategy_id === "all"
        ? "全部策略"
        : selectedIds.map((id) => STRATEGY_LABEL[id] || id).join("、");
    let cash = Number(lastPaperConfig?.initial_cash) || 1000000;
    try {
      lastPaperConfig = await requestJson("/api/ops/paper-config");
      cash = Number(lastPaperConfig.initial_cash) || cash;
    } catch {
      /* keep last known */
    }
    const ok = await confirmDialog(
      `重置模拟账户数据后，所选（${selectedLabel}）的持仓、成交、快照和模拟订单将清空并回到本金 ${formatMoney(cash)}，急停将恢复为关。此操作不可撤销。是否确定重置？`,
    );
    if (!ok) {
      return;
    }
    setControlReadonly(paperResetBtn, true);
    try {
      const payload = await requestJson("/api/paper/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const deleted = (payload.reports || []).reduce(
        (sum, item) => sum + Number(item.deleted_snapshots || 0) + Number(item.deleted_orders || 0),
        0,
      );
      const killCleared = Boolean(payload.kill_switch?.cleared);
      showToast(
        deleted
          ? killCleared
            ? "模拟账户已重置，急停已关"
            : "模拟账户已重置"
          : killCleared
            ? "没有可清空的模拟数据，急停已关"
            : "没有可清空的模拟数据",
        "ok",
      );
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

const paperClearHaltBtn = document.getElementById("paper-clear-halt");
if (paperClearHaltBtn) {
  paperClearHaltBtn.addEventListener("click", async () => {
    if (paperBusy || backtestBusy) {
      showToast(paperBusy ? "模拟盘运行中，请勿重复提交" : "回测进行中，请稍候", "warn");
      return;
    }
    if (isPaperOverview() || !paperFocusId || !paperBooks[paperFocusId]) {
      showToast("请先点选处于平仓中或已平仓的策略账本", "warn");
      return;
    }
    const status = paperHaltStatus(paperBooks[paperFocusId]);
    if (status === "active") {
      showToast("当前账本未处于平仓状态", "warn");
      return;
    }
    const label = STRATEGY_LABEL[paperFocusId] || paperFocusId;
    const statusLabel = PAPER_HALT_STATUS_LABEL[status] || status;
    const result = await confirmDialog(
      `将解除「${label}」的${statusLabel}状态，并按当前净值重置该账本回撤峰值，后续交易日可再买卖。是否继续？`,
      { requireReason: true, reasonPlaceholder: "必填，说明解除原因" },
    );
    if (!result?.ok) {
      return;
    }
    setControlReadonly(paperClearHaltBtn, true);
    try {
      const payload = await requestJson("/api/paper/halt/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: paperFocusId,
          reason: result.reason,
        }),
      });
      showToast(
        payload.changed ? `已解除 ${label} 的平仓状态` : `${label} 本来就不在平仓状态`,
        "ok",
      );
      await loadOrders();
    } catch (error) {
      showToast(error.message || "解除失败", "block");
    } finally {
      if (!backtestBusy && !paperBusy) {
        setControlReadonly(paperClearHaltBtn, false);
        syncPaperClearHaltBtn();
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

let lastPaperConfig = {
  initial_cash: 1000000,
  commission_per_myriad: 2.5,
  portfolio_drawdown_stop_pct: 12,
  strategy_drawdown_stop_pct: 12,
  drawdown_warn_pct: 8,
};

const PAPER_INITIAL_CASH_MIN = 10000;
const PAPER_INITIAL_CASH_MAX = 100000000;

function readPaperInitialCashInput() {
  const input = document.getElementById("paper-initial-cash");
  const cash = Number(input?.value);
  if (!Number.isFinite(cash) || cash < PAPER_INITIAL_CASH_MIN || cash > PAPER_INITIAL_CASH_MAX) {
    const message = `初始资金需在 ${formatMoney(PAPER_INITIAL_CASH_MIN)} 到 ${formatMoney(PAPER_INITIAL_CASH_MAX)} 之间`;
    if (input) {
      input.setCustomValidity(message);
      input.reportValidity();
      input.setCustomValidity("");
    }
    throw new Error(message);
  }
  return cash;
}

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
  const port = document.getElementById("paper-dd-portfolio");
  if (port && config.portfolio_drawdown_stop_pct != null) {
    port.value = String(config.portfolio_drawdown_stop_pct);
  }
  const strat = document.getElementById("paper-dd-strategy");
  if (strat && config.strategy_drawdown_stop_pct != null) {
    strat.value = String(config.strategy_drawdown_stop_pct);
  }
  const warn = document.getElementById("paper-dd-warn");
  if (warn && config.drawdown_warn_pct != null) {
    warn.value = String(config.drawdown_warn_pct);
  }
  setText(
    "paper-trading-hint",
    gate.enabled
      ? `模拟交易已开。本金 ${formatMoney(config.initial_cash)} 为组合资金：按本次参与跑模拟的策略数均分（只选 1 个则拿满），总览看组合净资产。佣金万分之 ${config.commission_per_myriad}；组合急停 ${config.portfolio_drawdown_stop_pct}%（相对组合峰值）/ 单策略平仓 ${config.strategy_drawdown_stop_pct}%（相对本账峰值）/ 单策略预警 ${config.drawdown_warn_pct}%。已有账本请先重置再跑。`
      : "开关为关时不能跑模拟。组合回撤达线才全局急停；单策略回撤只平仓该账本。",
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
          initial_cash: readPaperInitialCashInput(),
          commission_per_myriad: Number(document.getElementById("paper-commission-wan").value),
          portfolio_drawdown_stop_pct: Number(document.getElementById("paper-dd-portfolio").value),
          strategy_drawdown_stop_pct: Number(document.getElementById("paper-dd-strategy").value),
          drawdown_warn_pct: Number(document.getElementById("paper-dd-warn").value),
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
  const selected = getPaperSelectedStrategyIds();
  const ids = selected.length ? selected : Object.keys(STRATEGY_LABEL);
  const [mockRows, kill, paperGate, paperConfig, ...accounts] = await Promise.all([
    requestJson("/api/orders?limit=200"),
    requestJson("/api/ops/kill-switch"),
    requestJson("/api/ops/paper-trading"),
    requestJson("/api/ops/paper-config").catch(() => lastPaperConfig),
    ...ids.map((id) => requestJson(`/api/paper/account?strategy_id=${encodeURIComponent(id)}`)),
  ]);
  if (paperConfig && paperConfig.initial_cash != null) {
    lastPaperConfig = { ...lastPaperConfig, ...paperConfig };
  }
  paperKillState = kill;
  paperGateState = paperGate;
  const killSelect = document.getElementById("kill-engaged");
  if (killSelect) {
    killSelect.value = kill?.engaged ? "on" : "off";
    killSelect.dispatchEvent(new Event("change", { bubbles: true }));
  }
  paperBooks = {};
  for (const account of accounts) {
    if (account?.strategy_id) {
      paperBooks[account.strategy_id] = account;
    }
  }
  const bookIds = paperBookIds();
  if (bookIds.length <= 1) {
    paperFocusId = bookIds[0] || null;
  } else if (
    !paperFocusId
    || (paperFocusId !== PAPER_OVERVIEW_ID && !paperBooks[paperFocusId])
  ) {
    paperFocusId = PAPER_OVERVIEW_ID;
  }
  renderOrders(mockRows, "mock-order-body");
  await showPaperFocus();
}

const PAPER_OVERVIEW_ID = "__overview__";
let paperBooks = {};
let paperFocusId = null;
let paperKillState = null;
let paperGateState = null;

function paperBookIds() {
  return Object.keys(STRATEGY_LABEL).filter((id) => paperBooks[id]);
}

function isPaperOverview() {
  return paperFocusId === PAPER_OVERVIEW_ID;
}

function paperSessionStats(ids) {
  const sessions = ids.map((id) => Number(paperBooks[id]?.summary?.sessions || 0));
  const min = sessions.length ? Math.min(...sessions) : 0;
  const max = sessions.length ? Math.max(...sessions) : 0;
  return { sessions, min, max, aligned: sessions.length > 0 && min === max };
}

const PAPER_HALT_STATUS_LABEL = {
  active: "运行中",
  flatten_pending: "平仓中",
  halted: "已平仓",
};

/** Card / gate labels: run lifecycle + risk halt (halt wins). */
const PAPER_BOOK_STATUS_LABEL = {
  pending: "待运行",
  running: "运行中",
  done: "已完成",
  flatten_pending: "平仓中",
  halted: "已平仓",
};

function paperHaltStatus(accountOrSummary) {
  if (!accountOrSummary) {
    return "active";
  }
  const summary = accountOrSummary.summary || accountOrSummary;
  const state = accountOrSummary.state || {};
  const status = summary.halt_status || state.halt_status;
  if (status === "flatten_pending" || status === "halted" || status === "active") {
    return status;
  }
  if (summary.flatten_pending || state.flatten_pending) {
    return "flatten_pending";
  }
  if (summary.halted || state.halted) {
    return "halted";
  }
  return "active";
}

/** Display status for book cards: 待运行 / 运行中 / 已完成, or risk 平仓中 / 已平仓. */
function paperBookDisplayStatus(accountOrSummary, options = {}) {
  const halt = paperHaltStatus(accountOrSummary);
  if (halt === "flatten_pending" || halt === "halted") {
    return halt;
  }
  const busy = options.busy != null ? Boolean(options.busy) : paperBusy;
  if (busy) {
    return "running";
  }
  const summary = accountOrSummary?.summary || accountOrSummary || {};
  return Number(summary.sessions || 0) > 0 ? "done" : "pending";
}

function paperHaltCounts(ids) {
  let pending = 0;
  let halted = 0;
  for (const id of ids) {
    const status = paperHaltStatus(paperBooks[id]);
    if (status === "flatten_pending") {
      pending += 1;
    } else if (status === "halted") {
      halted += 1;
    }
  }
  return { pending, halted, active: Math.max(0, ids.length - pending - halted) };
}

function syncPaperClearHaltBtn() {
  const btn = document.getElementById("paper-clear-halt");
  if (!btn) {
    return;
  }
  const focused = !isPaperOverview() && paperFocusId && paperBooks[paperFocusId];
  const status = focused ? paperHaltStatus(paperBooks[paperFocusId]) : "active";
  const show = Boolean(focused && status !== "active");
  btn.hidden = !show;
  if (show && !paperBusy && !backtestBusy) {
    setControlReadonly(btn, false);
  }
}


function buildPaperOverviewAccount(ids) {
  const boards = ids.map((id) => paperBooks[id]?.summary || {});
  const stats = paperSessionStats(ids);
  const active = boards.filter((board) => Number(board.sessions || 0) > 0);
  const portfolioCash = Number(lastPaperConfig?.initial_cash);
  const deployedRaw = active.reduce((sum, board) => sum + Number(board.initial_cash || 0), 0);
  const endAssetRaw = active.reduce((sum, board) => sum + Number(board.end_asset || 0), 0);
  const cashRaw = active.reduce((sum, board) => sum + Number(board.cash || 0), 0);
  const marketValueRaw = active.reduce((sum, board) => sum + Number(board.market_value || 0), 0);
  const buyNotional = active.reduce((sum, board) => sum + Number(board.buy_notional || 0), 0);
  const sellNotional = active.reduce((sum, board) => sum + Number(board.sell_notional || 0), 0);
  const fees = active.reduce((sum, board) => sum + Number(board.fees || 0), 0);
  const filled = active.reduce((sum, board) => sum + Number(board.orders_filled || 0), 0);
  const rejected = active.reduce((sum, board) => sum + Number(board.orders_rejected || 0), 0);
  // 设置本金是组合上限。总览本金 = 当前所选/已跑账本的已部署本金；
  // 仅当实验室满仓导致合计 > 设置本金时，按比例缩到设置本金再算收益。
  // 切勿在只选 2/8 本（已部署 2.5 万）时仍用 10 万做分母，否则会出现假的 -76%。
  const settingCash = Number.isFinite(portfolioCash) && portfolioCash > 0
    ? portfolioCash
    : (deployedRaw > 0 ? deployedRaw : 0);
  const overfunded = deployedRaw > 0 && settingCash > 0 && deployedRaw > settingCash * 1.05;
  const underfunded = deployedRaw > 0 && settingCash > 0 && settingCash > deployedRaw * 2.5;
  const scale = overfunded ? settingCash / deployedRaw : 1;
  const deployed = deployedRaw * scale;
  const endAsset = endAssetRaw * scale;
  const cash = cashRaw * scale;
  const marketValue = marketValueRaw * scale;
  const initial = deployed > 0 ? deployed : settingCash;
  const returnBase = initial;
  const starts = active.map((board) => board.window_start).filter(Boolean).sort();
  const ends = active.map((board) => board.window_end).filter(Boolean).sort();
  const activeIds = ids.filter((id) => Number(paperBooks[id]?.summary?.sessions || 0) > 0);
  const timeline = mergePaperTimelines(activeIds, deployedRaw > 0 ? deployedRaw : returnBase);
  if (scale !== 1) {
    for (const row of timeline) {
      row.cash = Number(row.cash || 0) * scale;
      row.market_value = Number(row.market_value || 0) * scale;
      row.total_asset = Number(row.total_asset || 0) * scale;
      row.buy_notional = Number(row.buy_notional || 0) * scale;
      row.sell_notional = Number(row.sell_notional || 0) * scale;
      row.fees = Number(row.fees || 0) * scale;
      row.daily_pnl = Number(row.daily_pnl || 0) * scale;
    }
    // Recompute returns vs scaled principal (setting cash when overfunded).
    let prev = returnBase;
    let peak = returnBase;
    for (const row of timeline) {
      const asset = Number(row.total_asset || 0);
      row.daily_return = prev ? (asset - prev) / prev : 0;
      row.total_return = returnBase ? asset / returnBase - 1 : 0;
      peak = Math.max(peak, asset);
      row.drawdown = peak ? asset / peak - 1 : 0;
      prev = asset;
    }
  }
  const peakAsset = timeline.length
    ? timeline.reduce((peak, row) => Math.max(peak, Number(row.total_asset || 0)), Number(timeline[0].total_asset || 0))
    : active.reduce((sum, board) => sum + Number(board.peak_asset || 0), 0) * scale;
  const maxDd = timeline.length
    ? timeline.reduce((worst, row) => {
      const value = Number(row.drawdown);
      if (Number.isNaN(value)) {
        return worst;
      }
      return worst == null || value < worst ? value : worst;
    }, null)
    : active.reduce((worst, board) => {
      const value = Number(board.max_drawdown);
      if (Number.isNaN(value)) {
        return worst;
      }
      return worst == null || value < worst ? value : worst;
    }, null);
  const positions = [];
  const fills = [];
  for (const id of ids) {
    if (!Number(paperBooks[id]?.summary?.sessions || 0)) {
      continue;
    }
    for (const row of paperBooks[id]?.positions || []) {
      positions.push({
        ...row,
        strategy_id: id,
        market_value: Number(row.market_value || 0) * scale,
      });
    }
    for (const row of paperBooks[id]?.fills || []) {
      fills.push({ ...row, strategy_id: id });
    }
  }
  positions.sort((a, b) => Number(b.market_value || 0) - Number(a.market_value || 0));
  fills.sort((a, b) => String(b.trade_time || b.trade_date || "").localeCompare(String(a.trade_time || a.trade_date || "")));
  const haltCounts = paperHaltCounts(ids);
  const fundingComplete = active.length > 0
    && active.length === ids.length
    && !overfunded
    && !underfunded
    && Math.abs(deployedRaw - settingCash) <= Math.max(1, settingCash * 1e-6);
  const totalReturn = returnBase ? endAsset / returnBase - 1 : 0;
  const peakReturn = returnBase ? peakAsset / returnBase - 1 : 0;
  const summary = {
    window_start: starts[0] || null,
    window_end: ends[ends.length - 1] || null,
    sessions: stats.aligned ? stats.min : stats.max,
    sessions_min: stats.min,
    sessions_max: stats.max,
    sessions_aligned: stats.aligned,
    book_count: ids.length,
    active_book_count: active.length,
    halt_pending_count: haltCounts.pending,
    halt_flat_count: haltCounts.halted,
    halt_active_count: haltCounts.active,
    initial_cash: initial,
    setting_cash: settingCash,
    deployed_cash: deployedRaw,
    funding_scale: scale,
    funding_complete: fundingComplete,
    funding_underfunded: underfunded,
    funding_overfunded: overfunded,
    end_asset: endAsset,
    cash,
    market_value: marketValue,
    total_return: totalReturn,
    max_drawdown: maxDd == null ? 0 : maxDd,
    peak_asset: peakAsset,
    peak_return: peakReturn,
    position_count: positions.length,
    orders_filled: filled,
    orders_rejected: rejected,
    fills: fills.length,
    buy_notional: buyNotional,
    sell_notional: sellNotional,
    fees,
  };
  const activeReconciles = activeIds.map((id) => paperBooks[id]?.reconcile || {});
  const okCount = activeReconciles.filter((item) => item.ok).length;
  const buyQty = activeReconciles.reduce((sum, item) => sum + Number(item.buy_qty || 0), 0);
  const sellQty = activeReconciles.reduce((sum, item) => sum + Number(item.sell_qty || 0), 0);
  const expectedCashRaw = activeReconciles.reduce((sum, item) => sum + Number(item.expected_cash || 0), 0);
  const expectedCash = expectedCashRaw * scale;
  const actualCash = cash;
  const cashDiff = roundMoney(actualCash - expectedCash);
  const approx = (a, b, tol = 0.05) => Math.abs(Number(a) - Number(b)) <= tol;
  const approxRet = (a, b) => Math.abs(Number(a) - Number(b)) <= 1e-6;
  const expectedReturn = returnBase ? endAsset / returnBase - 1 : 0;
  const expectedPeakReturn = returnBase ? peakAsset / returnBase - 1 : 0;
  const reconcileChecks = [
    {
      name: "现金",
      expected: roundMoney(expectedCash),
      actual: roundMoney(actualCash),
      diff: cashDiff,
      ok: Math.abs(cashDiff) <= 0.05,
    },
    {
      name: "总资产",
      expected: roundMoney(expectedCash + marketValue),
      actual: roundMoney(endAsset),
      diff: roundMoney(endAsset - (expectedCash + marketValue)),
      ok: approx(endAsset, expectedCash + marketValue),
    },
    {
      name: "账户总览本金",
      expected: roundMoney(deployed),
      actual: roundMoney(initial),
      diff: roundMoney(initial - deployed),
      ok: approx(initial, deployed, 0.02)
        && !(settingCash > 0 && deployedRaw > 0 && deployedRaw < settingCash * 0.5 && approx(initial, settingCash, 1)),
    },
    {
      name: "账户总览累计收益",
      expected: expectedReturn,
      actual: totalReturn,
      diff: totalReturn - expectedReturn,
      ok: approxRet(totalReturn, expectedReturn),
    },
    {
      name: "账户总览峰值收益",
      expected: expectedPeakReturn,
      actual: peakReturn,
      diff: peakReturn - expectedPeakReturn,
      ok: approxRet(peakReturn, expectedPeakReturn) && peakAsset + 1e-9 >= endAsset,
    },
    {
      name: "通过账本数量",
      expected: activeReconciles.length,
      actual: okCount,
      diff: activeReconciles.length - okCount,
      ok: okCount === activeReconciles.length,
    },
  ];
  const reconcileOk = activeReconciles.length > 0
    && okCount === activeReconciles.length
    && reconcileChecks.every((row) => row.ok);
  const fundingNote = overfunded
    ? `实验室超配已按 ${scale.toFixed(4)} 缩至设置本金 ${formatMoney(settingCash)}；`
    : underfunded
      ? `仅含所选 ${active.length} 本已部署 ${formatMoney(deployed)}（设置本金 ${formatMoney(settingCash)}）；`
      : "";
  return {
    account_id: "paper:overview",
    strategy_id: PAPER_OVERVIEW_ID,
    summary,
    timeline,
    positions,
    fills,
    state: {
      cash: actualCash,
      initial_cash: initial,
      peak_asset: peakAsset,
    },
    reconcile: {
      ok: reconcileOk,
      asof: ends[ends.length - 1] || null,
      formula:
        `账户总览：净资产=所选已跑账本合计；本金=已部署本金 ${formatMoney(initial)}；`
        + fundingNote
        + `对账通过 ${okCount}/${activeReconciles.length}（已跑 ${active.length}/${ids.length}）。`
        + `累计收益 = 净资产 / 已部署本金 − 1。`,
      initial_cash: initial,
      buy_notional: roundMoney(buyNotional * scale),
      sell_notional: roundMoney(sellNotional * scale),
      fees: roundMoney(fees * scale),
      buy_qty: buyQty,
      sell_qty: sellQty,
      expected_cash: roundMoney(expectedCash),
      actual_cash: roundMoney(actualCash),
      cash_diff: cashDiff,
      market_value: roundMoney(marketValue),
      end_asset: roundMoney(endAsset),
      peak_asset: roundMoney(peakAsset),
      peak_return: summary.peak_return,
      checks: reconcileChecks,
      qty_mismatches: activeReconciles.flatMap((item) => item.qty_mismatches || []),
    },
  };
}

function roundMoney(value) {
  return Math.round((Number(value) || 0) * 10000) / 10000;
}

function mergePaperTimelines(ids, initialCash) {
  // Build per-book series, then on the union of dates use that day's asset or
  // carry-forward (idle initial before start / last asset after end). Avoids
  // fake portfolio jumps when lab solo-runs leave misaligned windows / cash.
  const series = [];
  for (const id of ids) {
    const rows = paperBooks[id]?.timeline || [];
    if (!rows.length) {
      continue;
    }
    const byDate = new Map(rows.map((row) => [row.trade_date, row]));
    const dates = rows.map((row) => row.trade_date);
    const initial = Number(paperBooks[id]?.summary?.initial_cash || 0);
    const firstAsset = Number(rows[0].total_asset || initial);
    const last = rows[rows.length - 1];
    series.push({
      id,
      byDate,
      start: dates[0],
      end: dates[dates.length - 1],
      initial,
      firstAsset,
      lastAsset: Number(last.total_asset || 0),
      lastCash: Number(last.cash || 0),
      lastMv: Number(last.market_value || 0),
    });
  }
  const allDates = [...new Set(series.flatMap((item) => [...item.byDate.keys()]))].sort((a, b) =>
    String(a).localeCompare(String(b)),
  );
  const timeline = allDates.map((day) => {
    const cur = {
      trade_date: day,
      cash: 0,
      market_value: 0,
      total_asset: 0,
      buys: 0,
      sells: 0,
      buy_notional: 0,
      sell_notional: 0,
      fees: 0,
      books: 0,
    };
    for (const book of series) {
      const row = book.byDate.get(day);
      if (row) {
        cur.cash += Number(row.cash || 0);
        cur.market_value += Number(row.market_value || 0);
        cur.total_asset += Number(row.total_asset || 0);
        cur.buys += Number(row.buys || 0);
        cur.sells += Number(row.sells || 0);
        cur.buy_notional += Number(row.buy_notional || 0);
        cur.sell_notional += Number(row.sell_notional || 0);
        cur.fees += Number(row.fees || 0);
        cur.books += 1;
      } else if (day < book.start) {
        // Funded but not yet in window: count idle book cash.
        cur.cash += book.initial;
        cur.total_asset += book.initial;
        cur.books += 1;
      } else if (day > book.end) {
        cur.cash += book.lastCash;
        cur.market_value += book.lastMv;
        cur.total_asset += book.lastAsset;
        cur.books += 1;
      }
    }
    return cur;
  });
  const base = Number(initialCash) > 0
    ? Number(initialCash)
    : (timeline[0] ? Number(timeline[0].total_asset) : 0);
  let prev = base;
  let peak = base;
  for (const row of timeline) {
    const asset = Number(row.total_asset || 0);
    row.daily_pnl = asset - prev;
    row.daily_return = prev ? row.daily_pnl / prev : 0;
    row.total_return = base ? asset / base - 1 : 0;
    peak = Math.max(peak, asset);
    row.drawdown = peak ? asset / peak - 1 : 0;
    prev = asset;
  }
  return timeline;
}

function paperSelectedStrategyLabel() {
  const ids = getPaperSelectedStrategyIds();
  const select = document.getElementById("paper-run-id");
  const allCount = select
    ? [...select.options].filter((option) => option.value && option.value !== "all").length
    : 0;
  if (!ids.length) {
    return "-";
  }
  if (allCount && ids.length === allCount) {
    return "全部";
  }
  return ids.map((id) => STRATEGY_LABEL[id] || id).join("、");
}

function renderPaperGates(kill, paperGate, account, multi) {
  const summary = document.getElementById("paper-summary");
  if (!summary) {
    return;
  }
  summary.innerHTML = "";
  summary.className = "paper-gates";
  const strategyLabel = paperSelectedStrategyLabel();
  const gates = [
    ["模拟交易", paperGate?.enabled ? "开" : "关"],
    ["急停", kill?.engaged ? "开" : "关"],
    ["策略", strategyLabel],
  ];
  if (isPaperOverview() && multi) {
    const stats = paperSessionStats(paperBookIds());
    const haltCounts = paperHaltCounts(paperBookIds());
    gates.push(["账本", `${paperBookIds().length} 本`]);
    gates.push([
      "交易日",
      stats.aligned ? `${stats.min} 日对齐` : `${stats.min}~${stats.max} 日未对齐`,
    ]);
    if (haltCounts.pending || haltCounts.halted) {
      gates.push(["风控", `平仓中 ${haltCounts.pending} · 已平仓 ${haltCounts.halted}`]);
    }
  } else if (account && account.strategy_id && account.strategy_id !== PAPER_OVERVIEW_ID) {
    const status = paperBookDisplayStatus(account);
    gates.push(["状态", PAPER_BOOK_STATUS_LABEL[status] || status]);
  }
  for (const [label, value] of gates) {
    const item = document.createElement("div");
    item.className = "paper-gate";
    const k = document.createElement("span");
    const v = document.createElement("strong");
    k.textContent = label;
    v.textContent = value;
    if (label === "策略") {
      v.title = value;
    }
    if (label === "交易日" && String(value).includes("未对齐")) {
      v.className = "warn";
    }
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
  const stats = paperSessionStats(ids);
  const haltCounts = paperHaltCounts(ids);
  const cards = [
    {
      id: PAPER_OVERVIEW_ID,
      title: "账户总览",
      subtitle: haltCounts.pending || haltCounts.halted
        ? `${ids.length} 本 · 平仓中 ${haltCounts.pending} · 已平仓 ${haltCounts.halted}`
        : `${ids.length} 本账本合计`,
      overview: true,
    },
    ...ids.map((id) => {
      const haltStatus = paperHaltStatus(paperBooks[id]);
      const displayStatus = paperBookDisplayStatus(paperBooks[id]);
      return {
        id,
        title: STRATEGY_LABEL[id] || id,
        subtitle: PAPER_BOOK_STATUS_LABEL[displayStatus] || "独立账本",
        overview: false,
        haltStatus,
        displayStatus,
      };
    }),
  ];
  for (const card of cards) {
    const rawBoard = card.overview
      ? buildPaperOverviewAccount(ids).summary
      : paperBooks[card.id]?.summary || {};
    const selected = getPaperSelectedStrategyIds();
    const board = card.overview
      ? rawBoard
      : paperDisplayBoard(card.id, rawBoard, selected.length ? selected : ids);
    const btn = document.createElement("button");
    const haltClass = card.haltStatus && card.haltStatus !== "active"
      ? ` is-${String(card.haltStatus).split("_").join("-")}`
      : card.displayStatus
        ? ` is-${String(card.displayStatus)}`
        : "";
    btn.type = "button";
    btn.className = `paper-book${paperFocusId === card.id ? " is-active" : ""}${card.overview ? " is-overview" : ""}${haltClass}`;
    const titleRow = document.createElement("span");
    titleRow.className = "paper-book-title-row";
    const title = document.createElement("strong");
    title.textContent = card.title;
    titleRow.appendChild(title);
    if (!card.overview && card.haltStatus && card.haltStatus !== "active") {
      const badge = document.createElement("span");
      badge.className = `paper-halt-badge is-${String(card.haltStatus).split("_").join("-")}`;
      badge.textContent = PAPER_HALT_STATUS_LABEL[card.haltStatus];
      titleRow.appendChild(badge);
    } else if (!card.overview && card.displayStatus === "running") {
      const badge = document.createElement("span");
      badge.className = "paper-halt-badge is-running";
      badge.textContent = PAPER_BOOK_STATUS_LABEL.running;
      titleRow.appendChild(badge);
    } else if (!card.overview && card.displayStatus === "done") {
      const badge = document.createElement("span");
      badge.className = "paper-halt-badge is-done";
      badge.textContent = PAPER_BOOK_STATUS_LABEL.done;
      titleRow.appendChild(badge);
    }
    if (card.overview && (haltCounts.pending || haltCounts.halted)) {
      const badge = document.createElement("span");
      badge.className = "paper-halt-badge is-overview";
      badge.textContent = haltCounts.pending
        ? `平仓中 ${haltCounts.pending}`
        : `已平仓 ${haltCounts.halted}`;
      titleRow.appendChild(badge);
    }
    const acc = document.createElement("span");
    acc.className = "paper-book-id";
    acc.textContent = card.subtitle;
    const meta = document.createElement("span");
    meta.className = "paper-book-meta";
    if (board.sessions) {
      const ret = document.createElement("em");
      ret.className = pnlClass(board.total_return);
      ret.textContent = formatPct(board.total_return);
      const peak = document.createElement("em");
      peak.className = pnlClass(board.peak_return);
      peak.textContent = formatPct(board.peak_return);
      const dayLabel = card.overview && !stats.aligned
        ? `${stats.min}~${stats.max} 日`
        : `${board.sessions} 日`;
      meta.append(
        document.createTextNode(`${dayLabel} · 资产 ${formatMoney(board.end_asset)} · 累计 `),
        ret,
        document.createTextNode(" · 峰值 "),
        peak,
      );
      if (!card.overview && !stats.aligned) {
        btn.classList.add("is-misaligned");
      }
    } else if (paperBusy) {
      meta.textContent = "回放中…等待快照";
    } else if (!card.overview) {
      meta.textContent = `计划本金 ${formatMoney(board.initial_cash)} · 还没有快照`;
    } else {
      meta.textContent = "还没有快照";
    }
    btn.append(titleRow, acc, meta);
    btn.addEventListener("click", () => {
      if (paperFocusId === card.id) {
        return;
      }
      paperFocusId = card.id;
      showPaperFocus().catch((error) => showToast(error.message || "切换账户失败", "block"));
    });
    host.appendChild(btn);
  }
}

async function showPaperFocus(options = {}) {
  const skipOrders = Boolean(options.skipOrders);
  const ids = paperBookIds();
  const multi = ids.length > 1;
  const account = isPaperOverview()
    ? buildPaperOverviewAccount(ids)
    : paperBooks[paperFocusId];
  renderPaperGates(paperKillState, paperGateState, account, multi);
  renderPaperBookSwitcher(ids);
  renderPaperCompare(ids);
  syncPaperClearHaltBtn();
  if (!account) {
    return;
  }
  await renderPaperAccount(account, paperKillState, paperGateState, multi);
  if (skipOrders) {
    return;
  }
  if (isPaperOverview()) {
    const orderLists = await Promise.all(
      ids.map((id) => requestJson(`/api/paper/orders?limit=500&strategy_id=${encodeURIComponent(id)}`)),
    );
    const merged = orderLists.flat().sort((a, b) =>
      String(b.created_at || b.trade_date || "").localeCompare(String(a.created_at || a.trade_date || "")),
    );
    renderOrders(merged.slice(0, 2000), "order-body");
  } else {
    const paperRows = await requestJson(
      `/api/paper/orders?limit=2000&strategy_id=${encodeURIComponent(paperFocusId)}`,
    );
    renderOrders(paperRows, "order-body");
  }
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
  const stats = paperSessionStats(ids);
  const span = title.querySelector("span");
  if (span) {
    span.textContent = stats.aligned
      ? `同一窗口 ${stats.min} 个交易日 · 各策略独立账本`
      : `交易日未对齐（${stats.min}~${stats.max}）· 并行模式会按日对齐`;
    span.className = stats.aligned ? "" : "warn";
  }
  for (const id of ids) {
    const account = paperBooks[id];
    const selected = getPaperSelectedStrategyIds();
    const board = paperDisplayBoard(id, account?.summary || {}, selected.length ? selected : ids);
    const reconcile = account?.reconcile || {};
    const tr = document.createElement("tr");
    if (!stats.aligned && board.sessions !== stats.max) {
      tr.classList.add("is-misaligned");
    }
    appendCell(tr, STRATEGY_LABEL[id] || id);
    appendCell(tr, board.sessions ? String(board.sessions) : "0", { className: "num" });
    appendCell(tr, board.end_asset == null ? "-" : formatMoney(board.end_asset), { className: "num" });
    appendCell(tr, formatPct(board.total_return), { className: pnlClass(board.total_return) });
    appendCell(tr, formatPct(board.peak_return), { className: pnlClass(board.peak_return) });
    appendCell(tr, formatPct(board.max_drawdown), { className: pnlClass(board.max_drawdown) });
    appendCell(tr, !board.sessions ? "尚无" : reconcile.ok ? "通过" : "不一致", {
      tone: !board.sessions ? "muted" : reconcile.ok ? "ok" : "block",
    });
    body.appendChild(tr);
  }
}

function paperHaltTriggerText(board) {
  const dd = board?.halt_dd;
  const stop = board?.halt_stop;
  if (dd == null || dd === "" || stop == null || stop === "") {
    return "";
  }
  return `触发时收盘盯市回撤 ${formatPct(dd)}，阈值 ${formatPct(stop)}。日终快照最大回撤可能略浅，因为平仓后净值会回一点。`;
}

async function renderPaperAccount(account, kill, paperGate, multi = false) {
  const body = document.getElementById("paper-curve-body");
  if (!body) {
    return;
  }
  const overview = account.strategy_id === PAPER_OVERVIEW_ID;
  const rawBoard = account.summary || {};
  const selected = getPaperSelectedStrategyIds();
  const board = overview
    ? rawBoard
    : paperDisplayBoard(
      account.strategy_id,
      rawBoard,
      selected.length ? selected : paperBookIds(),
    );
  const timeline = account.timeline || [];
  renderPaperBoard(board, overview);
  renderPaperReconcile(account.reconcile || {});
  let lab = null;
  if (!overview && account.strategy_id === "etf_ma_momentum_filter" && timeline.length) {
    try {
      lab = await requestJson(
        `/api/paper/lab/timeline?strategy_id=${encodeURIComponent(account.strategy_id)}`,
      );
    } catch (_err) {
      lab = null;
    }
  }
  renderPaperLabMetrics(lab, board);
  await loadPaperLabGrid(overview ? null : account.strategy_id);
  renderPaperChart(timeline, board, {
    strategyId: account.strategy_id,
    overview,
    lab,
  });
  paperDailyState.rows = timeline;
  paperDailyState.fillsByDate = groupFillsByDate(account.fills || []);
  paperDailyState.expanded = null;
  tradePages.daily = 1;
  tradePages.positions = 1;
  tradePages.fills = 1;
  tradePages.orders = 1;
  renderPaperDaily();
  const chartRows = filterPaperRowsByYear(timeline, paperChartYear);
  if (chartRows.length) {
    selectPaperDay(chartRows[chartRows.length - 1].trade_date, "table");
  }
  renderPaperPositions(account.positions || []);
  renderPaperFills(account.fills || []);
  const windowText = board.window_start && board.window_end
    ? `${board.window_start} ~ ${board.window_end}，共 ${board.sessions || 0} 个交易日`
    : "还没有模拟快照";
  const bookName = overview
    ? "账户总览"
    : STRATEGY_LABEL[account.strategy_id] || account.strategy_id || "当前账户";
  const cashText = formatMoney(board.initial_cash);
  if (!paperGate?.enabled) {
    setText("paper-account-hint", "设置页「模拟交易」为关，跑模拟不会成功。请先到设置打开开关。");
  } else if (kill?.engaged) {
    setText(
      "paper-account-hint",
      multi
        ? `急停已开，禁止新的模拟订单。点选总览或账户查看曲线。当前 ${bookName}：${windowText}。`
        : `急停已开，禁止新的模拟订单。当前窗口 ${windowText}。`,
    );
  } else if (overview) {
    const alignText = board.sessions_aligned
      ? `各账本 ${board.sessions || 0} 日已对齐`
      : `各账本交易日未对齐（${board.sessions_min}~${board.sessions_max}）；请用「并行模式」重跑以按日对齐`;
    const haltText = (board.halt_pending_count || board.halt_flat_count)
      ? `风控：平仓中 ${board.halt_pending_count || 0} 本、已平仓 ${board.halt_flat_count || 0} 本。`
      : "";
    const fundingText = board.funding_complete
      ? `组合本金 ${cashText}，净资产 ${formatMoney(board.end_asset)}。`
      : Number(board.deployed_cash) > Number(board.setting_cash ?? board.initial_cash) * 1.05
        ? `本金固定为设置值 ${formatMoney(board.setting_cash ?? board.initial_cash)}（不是各账相加）。当前各账合计部署 ${formatMoney(board.deployed_cash)}，总览已按比例缩放到本金；要账本真实均分请重置后用「全部/并行」重跑。`
        : `组合本金 ${cashText}；已部署 ${formatMoney(board.deployed_cash || 0)}（${board.active_book_count || 0}/${board.book_count || 0} 本已跑），净资产 ${formatMoney(board.end_asset)}。`;
    setText(
      "paper-account-hint",
      `${fundingText}${alignText}。${haltText}本金按设置页初始资金；总览合并各账并结转缺日。`,
    );
  }   else if (multi) {
    const status = paperHaltStatus({ summary: board, state: account.state });
    const haltText = status === "active"
      ? ""
      : status === "flatten_pending"
        ? "该账本处于平仓中：禁买，未卖出部分会在后续交易日继续强平。可用「解除单策略平仓」恢复交易。"
        : "该账本已平仓：禁买，仅现金记账。可用「解除单策略平仓」恢复交易。";
    setText(
      "paper-account-hint",
      `各账独立资金、互不占仓。当前查看 ${bookName}：${windowText}。收益相对该账本金 ${cashText}。${haltText}`,
    );
  } else {
    const status = paperHaltStatus({ summary: board, state: account.state });
    const trigger = paperHaltTriggerText(board);
    if (status === "flatten_pending") {
      setText(
        "paper-account-hint",
        `${windowText}。该账本平仓中：禁买，后续交易日继续强平。${trigger}可用「解除单策略平仓」恢复交易。`,
      );
    } else if (status === "halted") {
      setText(
        "paper-account-hint",
        `${windowText}。该账本已平仓：禁买。${trigger}可用「解除单策略平仓」恢复交易。`,
      );
    } else {
      setText("paper-account-hint", `${windowText}。收益相对本金 ${cashText}；折线与下表可对每日盈亏和成交。`);
    }
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
      ["峰值收益", formatPct(reconcile.peak_return), pnlClass(reconcile.peak_return)],
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
  const qtyName = (name) => /数量|账本/.test(String(name || ""));
  const returnName = (name) => /收益/.test(String(name || ""));
  const formatValue = (name, value) => {
    if (qtyName(name)) {
      return String(Math.round(Number(value) || 0));
    }
    if (returnName(name)) {
      return formatPct(value);
    }
    return formatMoney(value);
  };
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

function renderPaperBoard(board, overview = false) {
  const host = document.getElementById("paper-board");
  if (!host) {
    return;
  }
  host.innerHTML = "";
  if (!board.sessions) {
    const empty = document.createElement("p");
    empty.className = "hint";
    const planned = Number(board.initial_cash);
    empty.textContent = Number.isFinite(planned) && planned > 0
      ? `计划本金 ${formatMoney(planned)}。还没有模拟快照，跑完连续交易日后这里会给出区间收益、回撤和成交汇总。`
      : "还没有模拟快照，跑完连续交易日后这里会给出区间收益、回撤和成交汇总。";
    host.appendChild(empty);
    return;
  }
  const rangeLabel = overview && board.sessions_aligned === false
    ? `${board.window_start} ~ ${board.window_end}（${board.sessions_min}~${board.sessions_max} 日未对齐）`
    : `${board.window_start} ~ ${board.window_end}`;
  const cards = [
    ["区间", rangeLabel],
    ...(overview ? [["账本数", String(board.book_count || 0)]] : []),
    ...(overview
      ? [["组合本金", formatMoney(board.initial_cash)]]
      : [["本金", formatMoney(board.initial_cash)]]),
    ...(overview && board.deployed_cash != null && board.funding_complete === false
      ? [["已部署", formatMoney(board.deployed_cash)]]
      : []),
    [overview ? "净资产" : "期末总资产", formatMoney(board.end_asset)],
    ["区间收益", formatPct(board.total_return), pnlClass(board.total_return)],
    ["峰值收益", formatPct(board.peak_return), pnlClass(board.peak_return)],
    ["最大回撤", formatPct(board.max_drawdown), pnlClass(board.max_drawdown)],
    ["现金 / 市值", `${formatMoney(board.cash)} / ${formatMoney(board.market_value)}`],
    ["成交 / 拒单", `${board.orders_filled || 0} / ${board.orders_rejected || 0}`],
    ["买额 / 卖额", `${formatMoney(board.buy_notional)} / ${formatMoney(board.sell_notional)}`],
    ["费用", formatMoney(board.fees)],
    ["持仓只数", String(board.position_count || 0)],
  ];
  // Keep lifecycle / risk status after title block by injecting before money metrics.
  if (!overview) {
    const displayStatus = paperBookDisplayStatus(board);
    cards.splice(1, 0, ["状态", PAPER_BOOK_STATUS_LABEL[displayStatus] || displayStatus]);
  }
  if (overview && (board.halt_pending_count || board.halt_flat_count)) {
    cards.splice(2, 0, ["风控", `平仓中 ${board.halt_pending_count || 0} · 已平仓 ${board.halt_flat_count || 0}`]);
  }
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
    if (label === "区间" && overview && board.sessions_aligned === false) {
      v.className = "warn";
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

/** X-axis tick: include year when the series spans multiple years (YY-MM-DD). */
function axisDateLabel(date, { spanYears = false } = {}) {
  const parts = String(date || "").split("-");
  if (parts.length !== 3) {
    return date || "";
  }
  const [year, month, day] = parts;
  if (spanYears) {
    return `${year.slice(-2)}-${month}-${day}`;
  }
  return `${month}-${day}`;
}

function xAxisSpanYears(rows) {
  const years = new Set(
    (rows || [])
      .map((row) => String(row?.trade_date || "").slice(0, 4))
      .filter(Boolean),
  );
  return years.size > 1;
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
  if (paperChartView.mode === "stack") {
    const year = String(date).slice(0, 4);
    const index = (paperChartView.stats || []).findIndex((row) => row.year === year);
    if (index >= 0) {
      selectPaperStackYear(index, origin);
    }
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
  const yearBase = Number(paperChartView.yearNavBase);
  if (yearBase > 0) {
    const asset = Number(point.row.total_asset);
    const yearRet = Number.isFinite(asset) ? asset / yearBase - 1 : null;
    lines.push(["当年", formatPct(yearRet), pnlClass(yearRet)]);
  }
  lines.push(["净值率", formatPct(point.row.daily_return), pnlClass(point.row.daily_return)]);
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

function paperChartPrincipal(board, dataMin, dataMax) {
  // Overview: portfolio cash. Single book: that book's share. Never snap to series mid.
  const initial = Number(board?.initial_cash);
  const deployed = Number(board?.deployed_cash);
  if (Number.isFinite(initial) && initial > 0) {
    const dataMaxNum = Number(dataMax);
    // Stale oversized principal (e.g. default 1e6 vs ~1e5 NAV) must not become the baseline.
    if (Number.isFinite(dataMaxNum) && dataMaxNum > 0 && initial > dataMaxNum * 2.5) {
      if (Number.isFinite(deployed) && deployed > 0 && deployed <= dataMaxNum * 2.5) {
        return deployed;
      }
      return null;
    }
    return initial;
  }
  if (Number.isFinite(deployed) && deployed > 0) {
    return deployed;
  }
  return null;
}

function paperChartYDomain(assets, principal, { pinPrincipal = true } = {}) {
  const dataMin = Math.min(...assets);
  const dataMax = Math.max(...assets);
  const rawSpan = dataMax - dataMin;
  const span = rawSpan > 0 ? rawSpan : Math.max(Math.abs(dataMax) * 0.02, 1);
  const pad = Math.max(span * 0.12, Math.abs(dataMax) * 0.004, 1);
  let minY = dataMin - pad;
  let maxY = dataMax + pad;
  const hasPrincipal = Number.isFinite(principal) && principal > 0;
  if (hasPrincipal && pinPrincipal) {
    minY = Math.min(minY, principal - pad * 0.2);
    maxY = Math.max(maxY, principal + pad * 0.2);
  }
  if (maxY <= minY) {
    maxY = minY + 1;
  }
  return {
    minY,
    maxY,
    showPrincipal: Boolean(hasPrincipal && principal >= minY && principal <= maxY),
  };
}

function paperChartBookLabel(board, opts = {}) {
  const overview = Boolean(
    opts.overview
    || opts.strategyId === PAPER_OVERVIEW_ID
    || board?.strategy_id === PAPER_OVERVIEW_ID
    || paperFocusId === PAPER_OVERVIEW_ID,
  );
  if (overview) {
    return "账户总览";
  }
  const strategyId = opts.strategyId || board?.strategy_id || paperFocusId;
  return STRATEGY_LABEL[strategyId] || strategyId || "当前账户";
}

function renderPaperLabMetrics(lab, board) {
  const el = document.getElementById("paper-lab-metrics");
  if (!el) {
    return;
  }
  if (!lab || !lab.points?.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  const summary = lab.summary || board || {};
  el.hidden = false;
  el.innerHTML = [
    `<span>参数 <strong>${lab.parameter_set_id || "—"}</strong></span>`,
    `<span>累计收益 <strong class="${pnlClass(summary.total_return)}">${formatPct(summary.total_return)}</strong></span>`,
    `<span>最大回撤 <strong class="${pnlClass(summary.max_drawdown)}">${formatPct(summary.max_drawdown)}</strong></span>`,
    `<span>基准 <strong>${lab.benchmark_symbol || "510300.SH"}</strong></span>`,
    `<a href="#paper-lab-grid-panel" class="paper-lab-grid-link">实验对比 ↓</a>`,
  ].join("");
}

function renderPaperLabGrid(payload) {
  const panel = document.getElementById("paper-lab-grid-panel");
  const body = document.getElementById("paper-lab-grid-body");
  const meta = document.getElementById("paper-lab-grid-meta");
  if (!panel || !body) {
    return;
  }
  const rows = payload?.ok ? payload.rows || [] : [];
  if (!rows.length) {
    panel.hidden = true;
    body.innerHTML = "";
    return;
  }
  panel.hidden = false;
  if (meta) {
    const winner = payload.winner?.parameter_set_id || "—";
    meta.textContent = `batch ${payload.batch_id || "—"} · ${payload.days || "—"} 日 · 最优 ${winner}`;
  }
  body.innerHTML = "";
  const bestId = payload.winner?.parameter_set_id;
  for (const row of rows) {
    const tr = document.createElement("tr");
    if (row.parameter_set_id === bestId) {
      tr.classList.add("is-lab-winner");
    }
    appendCell(tr, row.parameter_set_id || "-");
    appendCell(tr, row.ma_window != null ? String(row.ma_window) : "-", { className: "num" });
    appendCell(tr, row.top_k != null ? String(row.top_k) : "-", { className: "num" });
    appendCell(tr, formatPct(row.total_return), { className: pnlClass(row.total_return) });
    appendCell(tr, formatPct(row.max_drawdown), { className: pnlClass(row.max_drawdown) });
    appendCell(tr, formatPct(row.regime_return_up), { className: pnlClass(row.regime_return_up) });
    appendCell(tr, formatPct(row.regime_return_range), { className: pnlClass(row.regime_return_range) });
    appendCell(tr, formatPct(row.regime_return_down), { className: pnlClass(row.regime_return_down) });
    appendCell(tr, row.fees == null ? "-" : formatMoney(row.fees), { className: "num" });
    body.appendChild(tr);
  }
}

async function loadPaperLabGrid(strategyId) {
  const panel = document.getElementById("paper-lab-grid-panel");
  if (!panel) {
    return;
  }
  if (strategyId !== "etf_ma_momentum_filter") {
    renderPaperLabGrid(null);
    return;
  }
  try {
    const payload = await requestJson("/api/paper/lab/grid");
    renderPaperLabGrid(payload);
  } catch (_err) {
    renderPaperLabGrid(null);
  }
}

let paperChartYear = "stack";
let paperChartSource = { rows: [], board: {}, opts: {} };
const PAPER_YEAR_METRICS = [
  { key: "ret", label: "收益", color: "#38bdf8" },
  { key: "peak", label: "峰值", color: "#f59e0b" },
  { key: "dd", label: "回撤", color: "#f87171" },
];

function formatAxisPct(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-";
  }
  const pct = number * 100;
  const digits = Math.abs(pct) >= 10 ? 0 : 1;
  return `${pct.toFixed(digits)}%`;
}

function paperTimelineYears(rows) {
  return [...new Set((rows || []).map((row) => String(row.trade_date || "").slice(0, 4)).filter((year) => year.length === 4))].sort();
}

function filterPaperRowsByYear(rows, year) {
  if (!year || year === "all" || year === "stack") {
    return rows || [];
  }
  return (rows || []).filter((row) => String(row.trade_date || "").startsWith(year));
}

function paperYearSummary(rows, board) {
  const list = rows || [];
  const years = paperTimelineYears(list);
  return years.map((year) => {
    const start = paperYearStartNav(list, year, board);
    const pts = filterPaperRowsByYear(list, year);
    let peakNav = start;
    let maxDd = 0;
    let hi = start;
    for (const row of pts) {
      const asset = Number(row.total_asset);
      hi = Math.max(hi, asset);
      peakNav = Math.max(peakNav, asset);
      if (peakNav > 0) {
        maxDd = Math.min(maxDd, asset / peakNav - 1);
      }
    }
    const end = Number(pts[pts.length - 1]?.total_asset);
    return {
      year,
      start,
      end,
      days: pts.length,
      from: pts[0]?.trade_date,
      to: pts[pts.length - 1]?.trade_date,
      ret: start > 0 && Number.isFinite(end) ? end / start - 1 : 0,
      peak: start > 0 ? hi / start - 1 : 0,
      dd: maxDd,
    };
  });
}

function paperYearStartNav(rows, year, board) {
  const initial = Number(board?.initial_cash);
  const list = rows || [];
  if (!year || year === "all" || year === "stack") {
    return Number.isFinite(initial) && initial > 0 ? initial : Number(list[0]?.total_asset);
  }
  const idx = list.findIndex((row) => String(row.trade_date || "").startsWith(year));
  if (idx > 0) {
    return Number(list[idx - 1].total_asset);
  }
  if (Number.isFinite(initial) && initial > 0) {
    return initial;
  }
  return Number(list[idx]?.total_asset);
}

function slicePaperLab(lab, rows) {
  if (!lab?.points?.length || !rows?.length) {
    return lab;
  }
  const dates = new Set(rows.map((row) => row.trade_date));
  const points = lab.points.filter((point) => dates.has(point.trade_date));
  if (!points.length) {
    return null;
  }
  const markers = (lab.markers || []).filter((mark) => dates.has(mark.trade_date));
  return {
    ...lab,
    points,
    markers,
    trough_date: dates.has(lab.trough_date) ? lab.trough_date : null,
  };
}

function syncPaperChartYears(years) {
  const host = document.getElementById("paper-chart-years");
  if (!host) {
    return;
  }
  host.innerHTML = "";
  if (years.length < 2) {
    host.hidden = true;
    if (paperChartYear === "stack") {
      paperChartYear = "all";
    }
    return;
  }
  host.hidden = false;
  if (paperChartYear !== "all" && paperChartYear !== "stack" && !years.includes(paperChartYear)) {
    paperChartYear = "stack";
  }
  for (const year of ["stack", "all", ...years]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "paper-chart-year";
    btn.dataset.paperYear = year;
    btn.textContent = year === "stack" ? "按年" : year === "all" ? "全部" : year;
    btn.classList.toggle("is-active", paperChartYear === year);
    host.appendChild(btn);
  }
}

function renderPaperStackChart(host, meta, bookEl, board, opts) {
  paperChartView = null;
  host.innerHTML = "";
  if (bookEl) {
    const label = paperChartBookLabel(board, opts);
    bookEl.textContent = label;
    bookEl.dataset.tone = label === "账户总览" ? "info" : "accent";
  }
  const stats = paperYearSummary(paperChartSource.rows, board);
  if (!stats.length) {
    if (meta) {
      meta.textContent = `相对本金 ${formatMoney(board.initial_cash ?? lastPaperConfig?.initial_cash ?? 0)}`;
    }
    host.textContent = "暂无净值曲线";
    return;
  }
  const values = stats.flatMap((row) => [row.ret, row.peak, row.dd]);
  values.push(0);
  const domain = paperChartYDomain(values, 0, { pinPrincipal: true });
  const minY = domain.minY;
  const maxY = domain.maxY;
  const spanY = maxY - minY || 1;
  const width = 720;
  const height = 248;
  const pad = { top: 22, right: 16, bottom: 28, left: 46 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const slotW = innerW / stats.length;
  const barW = Math.max(4, Math.min(14, (slotW - 10) / PAPER_YEAR_METRICS.length));
  const groupW = barW * PAPER_YEAR_METRICS.length + 2 * (PAPER_YEAR_METRICS.length - 1);
  const xMid = (index) => pad.left + (index + 0.5) * slotW;
  const yAt = (value) => pad.top + (1 - (value - minY) / spanY) * innerH;
  const zeroY = yAt(0);
  if (meta) {
    meta.textContent = `按年汇总 · X=年份 · 收益/峰值/回撤相对年初 · ${stats[0].year}–${stats[stats.length - 1].year}`;
  }
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "paper-chart-svg");
  const ticks = [maxY, 0, minY].filter((value, index, all) => all.findIndex((item) => Math.abs(item - value) < 1e-9) === index);
  ticks.forEach((value, tickIndex) => {
    const y = yAt(value);
    const isZero = Math.abs(value) < 1e-9;
    if (!isZero) {
      const grid = document.createElementNS(ns, "line");
      grid.setAttribute("x1", String(pad.left));
      grid.setAttribute("x2", String(width - pad.right));
      grid.setAttribute("y1", String(y));
      grid.setAttribute("y2", String(y));
      grid.setAttribute("class", "paper-chart-grid");
      svg.appendChild(grid);
    }
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", String(pad.left - 8));
    label.setAttribute("y", String(tickIndex === 0 ? y + 9 : tickIndex === ticks.length - 1 ? y - 2 : y + 3));
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", isZero ? "paper-chart-label is-principal" : "paper-chart-label");
    label.textContent = formatAxisPct(value);
    svg.appendChild(label);
  });
  const baseline = document.createElementNS(ns, "line");
  baseline.setAttribute("x1", String(pad.left));
  baseline.setAttribute("x2", String(width - pad.right));
  baseline.setAttribute("y1", String(zeroY));
  baseline.setAttribute("y2", String(zeroY));
  baseline.setAttribute("class", "paper-chart-baseline");
  svg.appendChild(baseline);
  PAPER_YEAR_METRICS.forEach((metric, index) => {
    const swatch = document.createElementNS(ns, "text");
    swatch.setAttribute("x", String(pad.left + index * 56));
    swatch.setAttribute("y", "12");
    swatch.setAttribute("class", "paper-chart-legend-swatch");
    swatch.setAttribute("fill", metric.color);
    swatch.textContent = metric.label;
    svg.appendChild(swatch);
  });
  stats.forEach((row, index) => {
    const left = xMid(index) - groupW / 2;
    PAPER_YEAR_METRICS.forEach((metric, m) => {
      const value = Number(row[metric.key]);
      const x = left + m * (barW + 2);
      const y1 = yAt(value);
      const y = Math.min(y1, zeroY);
      const h = Math.max(1.5, Math.abs(y1 - zeroY));
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", String(x));
      rect.setAttribute("y", String(y));
      rect.setAttribute("width", String(barW));
      rect.setAttribute("height", String(h));
      rect.setAttribute("rx", "1.5");
      rect.setAttribute("fill", metric.color);
      rect.setAttribute("class", "paper-chart-year-bar");
      svg.appendChild(rect);
    });
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", String(xMid(index)));
    text.setAttribute("y", String(height - 6));
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("class", "paper-chart-label paper-chart-x-label");
    text.textContent = row.year;
    svg.appendChild(text);
  });
  const cursor = document.createElementNS(ns, "rect");
  cursor.setAttribute("class", "paper-chart-year-cursor");
  cursor.setAttribute("y", String(pad.top));
  cursor.setAttribute("height", String(innerH));
  cursor.setAttribute("rx", "3");
  cursor.setAttribute("visibility", "hidden");
  svg.appendChild(cursor);
  const tooltip = document.createElement("div");
  tooltip.className = "paper-chart-tooltip";
  tooltip.hidden = true;
  stats.forEach((row, index) => {
    const hit = document.createElementNS(ns, "rect");
    hit.setAttribute("x", String(pad.left + index * slotW));
    hit.setAttribute("y", String(pad.top));
    hit.setAttribute("width", String(slotW));
    hit.setAttribute("height", String(innerH + 16));
    hit.setAttribute("class", "paper-chart-hit");
    hit.addEventListener("mouseenter", () => selectPaperStackYear(index, "hover"));
    hit.addEventListener("click", () => selectPaperStackYear(index, "chart"));
    svg.appendChild(hit);
  });
  host.appendChild(svg);
  host.appendChild(tooltip);
  paperChartView = {
    mode: "stack",
    stats,
    selected: null,
    cursor,
    tooltip,
    host,
    width,
    height,
    pad,
    slotW,
    xMid,
  };
}

function selectPaperStackYear(index, origin = "hover") {
  if (!paperChartView || paperChartView.mode !== "stack") {
    return;
  }
  const { stats, cursor, tooltip, host, width, pad, slotW } = paperChartView;
  const row = stats[index];
  if (!row) {
    return;
  }
  const x = pad.left + index * slotW;
  cursor.setAttribute("x", String(x + 2));
  cursor.setAttribute("width", String(Math.max(8, slotW - 4)));
  cursor.setAttribute("visibility", "visible");
  tooltip.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = `${row.year}${row.days < 200 ? "（未满年）" : ""}`;
  tooltip.appendChild(title);
  PAPER_YEAR_METRICS.forEach((metric) => {
    const p = document.createElement("p");
    p.style.color = metric.color;
    p.style.fontWeight = "650";
    p.textContent = `${metric.label} ${formatPct(row[metric.key])}`;
    tooltip.appendChild(p);
  });
  const navLine = document.createElement("p");
  navLine.textContent = `净值 ${formatMoney(row.start)} → ${formatMoney(row.end)}`;
  tooltip.appendChild(navLine);
  tooltip.hidden = false;
  const hostW = host.clientWidth || width;
  const scale = hostW / width;
  const tipW = tooltip.offsetWidth || 168;
  const left = Math.min(Math.max((x + slotW / 2) * scale - tipW / 2, 8), hostW - tipW - 8);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = "8px";
  paperChartView.selected = row.to;
  if (row.to) {
    document.querySelectorAll("#paper-curve-body tr[data-date]").forEach((tr) => {
      tr.classList.toggle("is-selected", tr.dataset.date === row.to);
    });
    if (origin === "chart") {
      const newestFirst = (paperDailyState.rows || []).slice().reverse();
      const idx = newestFirst.findIndex((item) => item.trade_date === row.to);
      if (idx >= 0) {
        const nextPage = Math.floor(idx / TRADE_PAGE_SIZE) + 1;
        if (nextPage !== tradePages.daily) {
          tradePages.daily = nextPage;
          renderPaperDaily();
          document.querySelectorAll("#paper-curve-body tr[data-date]").forEach((tr) => {
            tr.classList.toggle("is-selected", tr.dataset.date === row.to);
          });
        }
      }
    }
  }
}

function renderPaperChart(rows, board, opts = {}) {
  const host = document.getElementById("paper-equity-chart");
  const meta = document.getElementById("paper-chart-meta");
  const bookEl = document.getElementById("paper-chart-book");
  paperChartSource = { rows: rows || [], board: board || {}, opts: opts || {} };
  const years = paperTimelineYears(paperChartSource.rows);
  syncPaperChartYears(years);
  if (paperChartYear === "stack") {
    if (!host) {
      return;
    }
    renderPaperStackChart(host, meta, bookEl, board, opts);
    return;
  }
  const year = paperChartYear;
  const viewRows = filterPaperRowsByYear(paperChartSource.rows, year);
  const lab = slicePaperLab(opts.lab || null, viewRows);
  const yearStart = paperYearStartNav(paperChartSource.rows, year, board);
  const yearEnd = Number(viewRows[viewRows.length - 1]?.total_asset);
  const yearRet = yearStart > 0 && Number.isFinite(yearEnd) ? yearEnd / yearStart - 1 : null;
  const pinPrincipal = year === "all";
  const baseIsInitial = year === "all" || (Number(board?.initial_cash) > 0 && Math.abs(yearStart - Number(board.initial_cash)) < 1e-6);
  const baseLabel = baseIsInitial ? "本金" : "年初";
  paperChartView = null;
  if (!host) {
    return;
  }
  host.innerHTML = "";
  if (bookEl) {
    const label = paperChartBookLabel(board, opts);
    bookEl.textContent = label;
    bookEl.dataset.tone = label === "账户总览" ? "info" : "accent";
  }
  if (meta) {
    if (viewRows.length) {
      const winStart = viewRows[0].trade_date;
      const winEnd = viewRows[viewRows.length - 1].trade_date;
      const baseText = formatMoney(yearStart);
      meta.textContent = `${winStart} ~ ${winEnd} · ${baseLabel} ${baseText} · ${year === "all" ? "区间" : "当年"} ${formatPct(yearRet)}`;
    } else {
      meta.textContent = `相对本金 ${formatMoney(board.initial_cash ?? lastPaperConfig?.initial_cash ?? 0)}`;
    }
  }
  if (!viewRows.length) {
    host.textContent = "暂无净值曲线";
    return;
  }
  const width = 720;
  const height = 248;
  const pad = { top: 16, right: 44, bottom: 28, left: 58 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const assets = viewRows.map((row) => Number(row.total_asset));
  if (Number.isFinite(yearStart) && yearStart > 0) {
    assets.push(yearStart);
  }
  const bookPrincipal = paperChartPrincipal(board, Math.min(...assets), Math.max(...assets));
  const principal = pinPrincipal ? bookPrincipal : yearStart;
  // Include scaled benchmark so dashed line stays inside Y domain.
  if (pinPrincipal && lab?.points?.length === viewRows.length && principal != null && Number.isFinite(principal)) {
    for (const point of lab.points) {
      const nav = Number(point.benchmark_nav);
      if (Number.isFinite(nav)) {
        assets.push(nav * principal);
      }
    }
  }
  const dataMin = Math.min(...assets);
  const dataMax = Math.max(...assets);
  const domain = paperChartYDomain(assets, principal, { pinPrincipal });
  const minY = domain.minY;
  const maxY = domain.maxY;
  const spanY = maxY - minY || 1;
  const xAt = (index) => pad.left + (viewRows.length === 1 ? innerW / 2 : (index / (viewRows.length - 1)) * innerW);
  const yAt = (value) => pad.top + (1 - (value - minY) / spanY) * innerH;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "paper-chart-svg");

  // Regime bands (lab view) — behind everything else
  if (lab?.points?.length === viewRows.length) {
    let i = 0;
    while (i < lab.points.length) {
      const regime = lab.points[i].regime || "range";
      let j = i + 1;
      while (j < lab.points.length && (lab.points[j].regime || "range") === regime) {
        j += 1;
      }
      const x0 = xAt(i);
      const x1 = xAt(Math.max(i, j - 1));
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", String(x0));
      rect.setAttribute("y", String(pad.top));
      rect.setAttribute("width", String(Math.max(1, x1 - x0 + (viewRows.length === 1 ? 0 : innerW / (viewRows.length - 1)))));
      rect.setAttribute("height", String(innerH));
      rect.setAttribute(
        "class",
        regime === "trend_up"
          ? "paper-chart-regime-up"
          : regime === "trend_down"
            ? "paper-chart-regime-down"
            : "paper-chart-regime-range",
      );
      svg.appendChild(rect);
      i = j;
    }
  }

  const ticks = [];
  ticks.push(maxY);
  if (domain.showPrincipal && principal != null) {
    ticks.push(principal);
  }
  ticks.push(minY);
    ticks.forEach((value, tickIndex) => {
    const y = yAt(value);
    const isPrincipalTick = domain.showPrincipal && principal != null && Math.abs(value - principal) < 1e-6;
    if (!isPrincipalTick) {
      const grid = document.createElementNS(ns, "line");
      grid.setAttribute("x1", String(pad.left));
      grid.setAttribute("x2", String(width - pad.right));
      grid.setAttribute("y1", String(y));
      grid.setAttribute("y2", String(y));
      grid.setAttribute("class", "paper-chart-grid");
      svg.appendChild(grid);
    }
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", String(pad.left - 8));
    label.setAttribute(
      "y",
      String(tickIndex === 0 ? y + 9 : tickIndex === ticks.length - 1 ? y - 2 : y + 3),
    );
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", isPrincipalTick ? "paper-chart-label is-principal" : "paper-chart-label");
    label.textContent = formatAxisMoney(value);
    svg.appendChild(label);
  });
  // Ensure principal amount is always labeled on the left even when near the Y edge.
  if (domain.showPrincipal && principal != null) {
    const principalInTicks = ticks.some((value) => Math.abs(value - principal) < 1e-6);
    if (!principalInTicks) {
      const y = yAt(principal);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", String(pad.left - 8));
      label.setAttribute("y", String(y + 3));
      label.setAttribute("text-anchor", "end");
      label.setAttribute("class", "paper-chart-label is-principal");
      label.textContent = formatAxisMoney(principal);
      svg.appendChild(label);
    }
  }
  if (domain.showPrincipal && principal != null) {
    const baseY = yAt(principal);
    const baseline = document.createElementNS(ns, "line");
    baseline.setAttribute("x1", String(pad.left));
    baseline.setAttribute("x2", String(width - pad.right));
    baseline.setAttribute("y1", String(baseY));
    baseline.setAttribute("y2", String(baseY));
    baseline.setAttribute("class", "paper-chart-baseline");
    svg.appendChild(baseline);
    const baseLabelEl = document.createElementNS(ns, "text");
    baseLabelEl.setAttribute("x", String(width - pad.right + 4));
    baseLabelEl.setAttribute("y", String(baseY + 3));
    baseLabelEl.setAttribute("text-anchor", "start");
    baseLabelEl.setAttribute("class", "paper-chart-baseline-label");
    baseLabelEl.textContent = baseLabel;
    svg.appendChild(baseLabelEl);
  }
  const points = viewRows.map((row, index) => ({
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

  // Benchmark nav scaled to principal
  if (pinPrincipal && lab?.points?.length === viewRows.length && principal != null) {
    const benchPts = lab.points.map((p, index) => ({
      x: xAt(index),
      y: yAt(Number(p.benchmark_nav || 1) * principal),
    }));
    if (benchPts.length) {
      const bench = document.createElementNS(ns, "path");
      bench.setAttribute("d", smoothLinePath(benchPts));
      bench.setAttribute("class", "paper-chart-bench");
      svg.appendChild(bench);
    }
  }

  // Rebalance markers + drawdown trough
  if (lab?.markers?.length) {
    const byDate = new Map(points.map((p) => [p.date, p]));
    lab.markers.forEach((m) => {
      const pt = byDate.get(m.trade_date);
      if (!pt) {
        return;
      }
      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", String(pt.x));
      dot.setAttribute("cy", String(pt.y));
      dot.setAttribute("r", "2.6");
      dot.setAttribute("class", "paper-chart-rebalance");
      svg.appendChild(dot);
    });
  }
  if (lab?.trough_date) {
    const trough = points.find((p) => p.date === lab.trough_date);
    if (trough) {
      const mark = document.createElementNS(ns, "circle");
      mark.setAttribute("cx", String(trough.x));
      mark.setAttribute("cy", String(trough.y));
      mark.setAttribute("r", "4");
      mark.setAttribute("class", "paper-chart-dd-mark");
      svg.appendChild(mark);
    }
  }

  const tickIndexes = xTickIndexes(viewRows.length);
  const spanYears = xAxisSpanYears(viewRows);
  tickIndexes.forEach((index, order) => {
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", String(xAt(index)));
    text.setAttribute("y", String(height - 6));
    text.setAttribute(
      "text-anchor",
      order === 0 ? "start" : order === tickIndexes.length - 1 ? "end" : "middle",
    );
    text.setAttribute("class", "paper-chart-label paper-chart-x-label");
    text.textContent = axisDateLabel(viewRows[index].trade_date, { spanYears });
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
  const band = viewRows.length === 1 ? innerW : innerW / (viewRows.length - 1);
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
  paperChartView = {
    points,
    selected: null,
    cursor,
    hCursor,
    marker,
    axisDot,
    yAxisDot,
    yValueLabel,
    yValueBg,
    tooltip,
    host,
    width,
    height,
    pad,
    yearNavBase: year !== "all" && Number.isFinite(yearStart) && yearStart > 0 ? yearStart : null,
  };
}

document.getElementById("paper-chart-years")?.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-paper-year]");
  if (!btn) {
    return;
  }
  const year = btn.dataset.paperYear || "all";
  if (year === paperChartYear) {
    return;
  }
  paperChartYear = year;
  renderPaperChart(paperChartSource.rows, paperChartSource.board, paperChartSource.opts);
  if (paperChartYear === "stack") {
    return;
  }
  const chartRows = filterPaperRowsByYear(paperChartSource.rows, paperChartYear);
  if (chartRows.length) {
    selectPaperDay(chartRows[chartRows.length - 1].trade_date, "chart");
  }
});

bindTradePager("paper-daily", "daily", renderPaperDaily);
bindTradePager("paper-position", "positions", () => renderPaperPositions());
bindTradePager("paper-fill", "fills", () => renderPaperFills());
bindTradePager("paper-order", "orders", () => renderOrders(tradeLists.orders, "order-body"));
bindTradePager("mock-order", "mock", () => renderOrders(tradeLists.mock, "mock-order-body"));

/* ——— 1B: factors / selector / events / tags / overrides ——— */

let factorComputeTimer = 0;
let factorComputeBusy = false;

function setHint(id, message, show = true) {
  const el = document.getElementById(id);
  if (!el) {
    return;
  }
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = !show;
  el.textContent = message;
}

function factorProgressText(row) {
  if (!row) {
    return "因子计算中…";
  }
  const status = SYNC_STATUS_LABEL[row.status] || row.status || "进行中";
  const pct = row.progress_pct;
  const label = row.progress_label || "";
  if (pct != null && pct !== "") {
    return `因子计算 ${status} ${pct}%${label ? ` · ${label}` : ""}`;
  }
  return `因子计算 ${status}${label ? ` · ${label}` : ""}`;
}

function setFactorComputeBusy(busy) {
  factorComputeBusy = Boolean(busy);
  const btn = document.getElementById("factor-compute-submit");
  if (btn) {
    btn.disabled = factorComputeBusy;
    btn.setAttribute("aria-busy", factorComputeBusy ? "true" : "false");
  }
}

function finishFactorCompute(row) {
  window.clearInterval(factorComputeTimer);
  factorComputeTimer = 0;
  setFactorComputeBusy(false);
  if (!row) {
    return;
  }
  if (row.status === "success") {
    let detail = row.detail;
    if (typeof detail === "string") {
      try {
        detail = JSON.parse(detail);
      } catch (_err) {
        detail = null;
      }
    }
    const n = detail?.factor_rows ?? detail?.sqlite_rows ?? row.factor_rows;
    const strategies = Array.isArray(detail?.strategies) ? detail.strategies.length : 0;
    const parts = ["计算完成"];
    if (n != null) {
      parts.push(`${Number(n).toLocaleString("zh-CN")} 行信号`);
    }
    if (strategies > 0) {
      parts.push(`${strategies} 个策略`);
    }
    parts.push("可按下方条件查看");
    const resultEl = document.getElementById("factor-compute-result");
    setHint("factor-compute-result", parts.join(" · "));
    if (resultEl && row.run_id) {
      resultEl.title = `任务编号：${row.run_id}`;
    }
    setText("factor-compute-meta", "计算完成");
    showToast("因子计算完成", "ok");
    loadFactorSignals().catch(() => {});
  } else if (row.status === "failed") {
    setHint("factor-compute-result", `计算失败：${row.fail_reason || "unknown"}`);
    setText("factor-compute-meta", "计算失败");
    showToast(row.fail_reason || "因子计算失败", "block");
  }
}

function watchFactorCompute(runId) {
  window.clearInterval(factorComputeTimer);
  setFactorComputeBusy(true);
  const tick = () => {
    requestJsonOrMissing(`/api/factors/compute/${encodeURIComponent(runId)}`, undefined, "因子任务接口暂不可用")
      .then((row) => {
        if (!row) {
          finishFactorCompute(null);
          return;
        }
        setHint("factor-compute-result", factorProgressText(row));
        setText("factor-compute-meta", factorProgressText(row));
        if (row.status === "success" || row.status === "failed") {
          finishFactorCompute(row);
        }
      })
      .catch((error) => {
        finishFactorCompute(null);
        setHint("factor-compute-result", `轮询失败：${error.message}`);
        showToast(error.message, "block");
      });
  };
  tick();
  factorComputeTimer = window.setInterval(tick, 1000);
}

async function resumeActiveFactorCompute() {
  const payload = await requestJsonOrMissing("/api/factors/compute/active", undefined, "因子任务接口暂不可用");
  if (!payload) {
    return;
  }
  const active = payload.active;
  if (active && (active.inflight || active.status === "queued" || active.status === "running")) {
    setHint("factor-compute-result", factorProgressText(active));
    watchFactorCompute(active.run_id);
  }
}

const FACTOR_PAGE_SIZE = 10;
const factorViewState = {
  page: 1,
  pages: 1,
  total: 0,
  seq: 0,
};

function renderFactorSignals(payload) {
  const body = document.getElementById("factor-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
      ? payload.items
      : [];
  const total = Array.isArray(payload) ? list.length : Number(payload?.total) || 0;
  const page = Array.isArray(payload) ? 1 : Number(payload?.page) || 1;
  const pages = Array.isArray(payload) ? 1 : Number(payload?.pages) || 1;
  const size = Array.isArray(payload) ? list.length || FACTOR_PAGE_SIZE : Number(payload?.page_size) || FACTOR_PAGE_SIZE;
  factorViewState.page = page;
  factorViewState.pages = pages;
  factorViewState.total = total;
  if (!list.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty-hint";
    td.textContent = "暂无因子信号。可先触发计算，或换日期 / 关键词查看。";
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    for (const row of list) {
      const tr = document.createElement("tr");
      appendCell(tr, row.trade_date || "-");
      const symbol = row.symbol || "-";
      const instName = row.instrument_name || row.name || "";
      appendCell(tr, instName ? `${instName} · ${symbol}` : symbol, {
        title: instName ? `代码 ${symbol}` : symbol,
      });
      const factorId = row.factor_name || "";
      const factorLabel = FACTOR_NAME_LABEL[factorId] || factorId || "-";
      appendCell(tr, factorId && FACTOR_NAME_LABEL[factorId] ? `${factorLabel} · ${factorId}` : factorLabel, {
        title: factorId || undefined,
      });
      const value = row.value;
      appendCell(tr, value == null || value === "" ? "-" : Number(value).toFixed(6), { className: "num" });
      const hash = row.params_hash ? String(row.params_hash).slice(0, 8) : "-";
      appendCell(tr, hash, { title: row.params_hash ? `参数指纹完整值：${row.params_hash}` : "无参数指纹" });
      body.appendChild(tr);
    }
  }
  setText("factor-page-label", `共 ${total} 条 · ${page} / ${pages} · 每页 ${size}`);
  const prev = document.getElementById("factor-prev");
  const next = document.getElementById("factor-next");
  if (prev) {
    prev.disabled = page <= 1 || total === 0;
  }
  if (next) {
    next.disabled = page >= pages || total === 0;
  }
  const date = document.getElementById("factor-view-date")?.value;
  setText(
    "factor-compute-meta",
    total
      ? date
        ? `${date} · 共 ${total} 行 · 第 ${page}/${pages} 页`
        : `共 ${total} 行 · 第 ${page}/${pages} 页`
      : "暂无匹配",
  );
}

function factorViewQuery(page = factorViewState.page) {
  const params = new URLSearchParams();
  const date = document.getElementById("factor-view-date")?.value;
  const name = document.getElementById("factor-view-name")?.value?.trim();
  const code = document.getElementById("factor-view-symbol")?.value?.trim();
  if (date) {
    params.set("trade_date", date);
  }
  if (name) {
    params.set("factor_name", name);
  }
  if (code) {
    // Align with overview market Top50: code or instrument name.
    params.set("code", code);
  }
  params.set("page", String(Math.max(1, Number(page) || 1)));
  params.set("page_size", String(FACTOR_PAGE_SIZE));
  return params;
}

async function loadFactorSignals(page = factorViewState.page) {
  const seq = ++factorViewState.seq;
  const prev = document.getElementById("factor-prev");
  const next = document.getElementById("factor-next");
  if (prev) {
    prev.disabled = true;
  }
  if (next) {
    next.disabled = true;
  }
  const qs = factorViewQuery(page).toString();
  const payload = await requestJsonOrMissing(`/api/factors?${qs}`, undefined, "因子查询接口暂不可用");
  if (seq !== factorViewState.seq) {
    return;
  }
  if (payload == null) {
    renderFactorSignals({ items: [], total: 0, page: 1, pages: 1, page_size: FACTOR_PAGE_SIZE });
    setText("factor-compute-meta", "接口暂不可用");
    return;
  }
  renderFactorSignals(payload);
}

async function loadFactorsPage() {
  await resumeActiveFactorCompute().catch(() => {});
  factorViewState.page = 1;
  await loadFactorSignals(1);
  renderSelectorPreview(null);
}

function renderSelectorPreview(payload) {
  const body = document.getElementById("selector-preview-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const weights = payload?.weights && typeof payload.weights === "object" ? payload.weights : {};
  const entries = Object.entries(weights).sort((a, b) => Number(b[1]) - Number(a[1]));
  const meta = document.getElementById("selector-preview-meta");
  if (meta) {
    if (payload) {
      meta.hidden = false;
      meta.textContent = `${STRATEGY_LABEL[payload.strategy_id] || payload.strategy_id} · 截至 ${payload.asof} · ${payload.n ?? entries.length} 只 · gross ${formatPct(payload.gross)}`;
    } else {
      meta.hidden = true;
      meta.textContent = "";
    }
  }
  if (!payload) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.className = "empty-hint";
    td.textContent = "暂无选股预览。选择策略与截至日后点「预览权重」。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  if (!entries.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.className = "empty-hint";
    td.textContent = "暂无选股结果（该日无信号或数据不足）。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  entries.forEach(([symbol, weight], index) => {
    const tr = document.createElement("tr");
    appendCell(tr, String(index + 1), { className: "num" });
    appendCell(tr, symbol);
    appendCell(tr, formatPct(weight), { className: "num" });
    body.appendChild(tr);
  });
}

document.getElementById("factor-compute-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (factorComputeBusy) {
    showToast("因子计算进行中，请稍候", "warn");
    return;
  }
  const strategyId = document.getElementById("factor-compute-strategy")?.value || "all";
  setHint("factor-compute-result", "入队中…");
  setFactorComputeBusy(true);
  try {
    const payload = await requestJsonOrMissing(
      "/api/factors/compute",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: strategyId }),
      },
      "因子计算接口暂不可用",
    );
    if (!payload) {
      setFactorComputeBusy(false);
      return;
    }
    setHint("factor-compute-result", factorProgressText(payload));
    if (payload.run_id) {
      watchFactorCompute(payload.run_id);
    } else {
      setFactorComputeBusy(false);
    }
  } catch (error) {
    setFactorComputeBusy(false);
    setHint("factor-compute-result", `失败：${error.message}`);
    showToast(error.message, "block");
  }
});

document.getElementById("factor-view-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  factorViewState.page = 1;
  loadFactorSignals(1).catch((error) => showToast(error.message, "block"));
});

let factorCodeTimer = 0;
document.getElementById("factor-view-symbol")?.addEventListener("input", () => {
  window.clearTimeout(factorCodeTimer);
  factorCodeTimer = window.setTimeout(() => {
    factorViewState.page = 1;
    loadFactorSignals(1).catch((error) => showToast(error.message, "block"));
  }, 280);
});

document.getElementById("factor-prev")?.addEventListener("click", () => {
  if (factorViewState.page <= 1) {
    return;
  }
  loadFactorSignals(factorViewState.page - 1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("factor-next")?.addEventListener("click", () => {
  if (factorViewState.page >= factorViewState.pages) {
    return;
  }
  loadFactorSignals(factorViewState.page + 1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("selector-preview-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const strategyId = document.getElementById("selector-preview-strategy")?.value;
  const asof = document.getElementById("selector-preview-asof")?.value;
  if (!strategyId || !asof) {
    showToast("请选择策略并填写截至日", "warn");
    return;
  }
  try {
    const payload = await requestJsonOrMissing(
      "/api/selectors/preview",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: strategyId, asof }),
      },
      "选股预览接口暂不可用",
    );
    if (!payload) {
      renderSelectorPreview(null);
      return;
    }
    renderSelectorPreview(payload);
  } catch (error) {
    showToast(error.message, "block");
  }
});

const EVENTS_PAGE_SIZE = 10;
const EVENT_TYPE_LABEL = {
  holder_increase: "增持",
  holder_decrease: "减持",
};

function eventTypeLabel(type) {
  const key = String(type || "").trim();
  if (!key) {
    return "-";
  }
  return EVENT_TYPE_LABEL[key] || key;
}

const eventsViewState = {
  page: 1,
  pages: 1,
  total: 0,
  seq: 0,
};

function renderEvents(payload) {
  const body = document.getElementById("events-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
      ? payload.items
      : [];
  const total = Array.isArray(payload) ? list.length : Number(payload?.total) || 0;
  const page = Array.isArray(payload) ? 1 : Number(payload?.page) || 1;
  const pages = Array.isArray(payload) ? 1 : Number(payload?.pages) || 1;
  const size = Array.isArray(payload)
    ? list.length || EVENTS_PAGE_SIZE
    : Number(payload?.page_size) || EVENTS_PAGE_SIZE;
  eventsViewState.page = page;
  eventsViewState.pages = pages;
  eventsViewState.total = total;
  if (!list.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "empty-hint";
    td.textContent = "暂无事件。可导入 fixture，或配置 Tushare token 后拉取。";
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    for (const row of list) {
      const tr = document.createElement("tr");
      appendCell(tr, row.event_date || "-");
      appendCell(tr, row.asof_date || "-");
      appendCell(tr, eventTypeLabel(row.event_type), { tone: "info", title: row.event_type || "" });
      appendCell(tr, row.symbol || "-");
      const actor = row.actor || "-";
      appendCell(tr, actor, { className: "col-actor", title: actor });
      const value = row.value;
      appendCell(tr, value == null || value === "" ? "-" : formatEventValue(value), { className: "num" });
      appendCell(tr, row.source || "-");
      body.appendChild(tr);
    }
  }
  setText("events-page-label", `共 ${total} 条 · ${page} / ${pages} · 每页 ${size}`);
  const prev = document.getElementById("events-prev");
  const next = document.getElementById("events-next");
  if (prev) {
    prev.disabled = page <= 1 || total === 0;
  }
  if (next) {
    next.disabled = page >= pages || total === 0;
  }
  setText("events-page-meta", total ? `共 ${total} 条 · 第 ${page}/${pages} 页` : "暂无匹配");
}

async function loadEventTypes() {
  const select = document.getElementById("events-type");
  if (!select) {
    return;
  }
  const types = await requestJsonOrMissing("/api/events/types", undefined, "事件类型接口暂不可用");
  if (!types) {
    return;
  }
  const current = select.value;
  const keep = new Set(["", ...(Array.isArray(types) ? types : [])]);
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "全部";
  select.appendChild(all);
  for (const type of Array.isArray(types) ? types : []) {
    const opt = document.createElement("option");
    opt.value = type;
    opt.textContent = eventTypeLabel(type);
    select.appendChild(opt);
  }
  if (keep.has(current)) {
    select.value = current;
  }
  select.dispatchEvent(new Event("change"));
}

function eventsQuery(page = eventsViewState.page) {
  const params = new URLSearchParams();
  const type = document.getElementById("events-type")?.value;
  const symbol = document.getElementById("events-symbol")?.value?.trim();
  const start = document.getElementById("events-start")?.value;
  const end = document.getElementById("events-end")?.value;
  if (type) {
    params.set("event_type", type);
  }
  if (symbol) {
    params.set("symbol", symbol);
  }
  if (start) {
    params.set("start", start);
  }
  if (end) {
    params.set("end", end);
  }
  params.set("page", String(Math.max(1, Number(page) || 1)));
  params.set("page_size", String(EVENTS_PAGE_SIZE));
  return params;
}

async function loadEventsPage(page = eventsViewState.page) {
  const seq = ++eventsViewState.seq;
  await loadEventTypes().catch(() => {});
  const prev = document.getElementById("events-prev");
  const next = document.getElementById("events-next");
  if (prev) {
    prev.disabled = true;
  }
  if (next) {
    next.disabled = true;
  }
  const payload = await requestJsonOrMissing(
    `/api/events?${eventsQuery(page).toString()}`,
    undefined,
    "事件列表接口暂不可用",
  );
  if (seq !== eventsViewState.seq) {
    return;
  }
  if (payload == null) {
    renderEvents({ items: [], total: 0, page: 1, pages: 1, page_size: EVENTS_PAGE_SIZE });
    setText("events-page-meta", "接口暂不可用");
    return;
  }
  renderEvents(payload);
}

document.getElementById("events-filters")?.addEventListener("submit", (event) => {
  event.preventDefault();
  eventsViewState.page = 1;
  loadEventsPage(1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("events-reset")?.addEventListener("click", () => {
  const type = document.getElementById("events-type");
  if (type) {
    type.value = "";
    type.dispatchEvent(new Event("change", { bubbles: true }));
  }
  const symbol = document.getElementById("events-symbol");
  if (symbol) {
    symbol.value = "";
  }
  const start = document.getElementById("events-start");
  if (start) {
    start.value = "";
  }
  const end = document.getElementById("events-end");
  if (end) {
    end.value = "";
  }
  eventsViewState.page = 1;
  loadEventsPage(1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("events-prev")?.addEventListener("click", () => {
  if (eventsViewState.page <= 1) {
    return;
  }
  loadEventsPage(eventsViewState.page - 1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("events-next")?.addEventListener("click", () => {
  if (eventsViewState.page >= eventsViewState.pages) {
    return;
  }
  loadEventsPage(eventsViewState.page + 1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("events-import")?.addEventListener("click", async () => {
  setHint("events-action-hint", "导入中…");
  try {
    const payload = await requestJsonOrMissing(
      "/api/events/import",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      "事件导入接口暂不可用",
    );
    if (!payload) {
      setHint("events-action-hint", "");
      return;
    }
    const n = payload.imported ?? payload.upserted ?? payload.n ?? payload.rows ?? payload.count;
    setHint("events-action-hint", `已导入${n != null ? ` ${n} 条` : ""}${payload.source_path ? ` · ${payload.source_path}` : ""}`);
    showToast("事件 fixture 已导入", "ok");
    eventsViewState.page = 1;
    await loadEventsPage(1);
  } catch (error) {
    setHint("events-action-hint", `导入失败：${error.message}`);
    showToast(error.message, "block");
  }
});

let eventsPullTimer = 0;
let eventsPullBusy = false;

function setEventsPullBusy(busy) {
  eventsPullBusy = Boolean(busy);
  const btn = document.getElementById("events-pull");
  if (btn) {
    btn.disabled = eventsPullBusy;
    btn.setAttribute("aria-busy", eventsPullBusy ? "true" : "false");
    btn.textContent = eventsPullBusy ? "拉取中…" : "拉取增减持";
  }
}

function eventsPullProgressText(row) {
  if (!row) {
    return "拉取中…";
  }
  const status = row.status || "进行中";
  const label = row.progress_label || "";
  const pct = row.progress_pct;
  if (pct != null && pct !== "") {
    return `增减持拉取 ${status} ${pct}%${label ? ` · ${label}` : ""}`;
  }
  return `增减持拉取 ${status}${label ? ` · ${label}` : ""}`;
}

function formatEventsPullResult(payload) {
  if (!payload || typeof payload !== "object") {
    return "拉取完成（已写入 SQLite + parquet）";
  }
  const written = payload.upserted ?? payload.n ?? payload.rows ?? payload.count;
  const fetched = payload.fetched;
  const unique = payload.unique_in_batch;
  const stored = payload.stored_total;
  const deduped = payload.deduped_in_batch;
  const requests = payload.requests ?? payload.chunks;
  const parts = ["拉取完成"];
  if (payload.range_start && payload.range_end) {
    parts.push(`${payload.range_start}~${payload.range_end}`);
  }
  if (payload.default_lookback_days != null && !payload.range_start) {
    parts.push(`默认近 ${payload.default_lookback_days} 天`);
  }
  if (requests != null) {
    parts.push(`${requests} 次请求`);
  }
  if (fetched != null) {
    parts.push(`抓取 ${fetched}`);
  }
  if (written != null) {
    parts.push(`规范化 ${written}`);
  }
  if (unique != null) {
    parts.push(`去重后 ${unique}`);
  }
  if (deduped != null && Number(deduped) > 0) {
    parts.push(`批次内重复 ${deduped}`);
  }
  if (stored != null) {
    parts.push(`库内共 ${stored}`);
  }
  const dayHits = Array.isArray(payload.day_hits_limit) ? payload.day_hits_limit : [];
  if (dayHits.length) {
    parts.push(`仍触顶 ${dayHits.length} 日`);
  }
  parts.push("已写入 SQLite + parquet");
  return `${parts.join(" · ")}（按月分片，满 3000 再按日；列表走库内分页）`;
}

function finishEventsPull(row) {
  window.clearInterval(eventsPullTimer);
  eventsPullTimer = 0;
  setEventsPullBusy(false);
  if (!row) {
    return;
  }
  if (row.status === "success") {
    const payload = row.result && typeof row.result === "object" ? row.result : null;
    const dayHits = Array.isArray(payload?.day_hits_limit) ? payload.day_hits_limit : [];
    setHint("events-action-hint", formatEventsPullResult(payload));
    showToast(dayHits.length ? "增减持已拉取（部分日期仍触顶）" : "股东增减持已拉取", dayHits.length ? "warn" : "ok");
    eventsViewState.page = 1;
    loadEventsPage(1).catch((error) => showToast(error.message, "block"));
  } else if (row.status === "failed") {
    const msg = row.fail_reason || "unknown";
    const noToken = /token|TUSHARE|未配置|missing/i.test(msg);
    setHint(
      "events-action-hint",
      noToken
        ? `拉取失败：未配置 Tushare token（${msg}）。可先「导入 fixture」离线验证。`
        : `拉取失败：${msg}`,
    );
    showToast(noToken ? "未配置 Tushare token，请先导入 fixture 或配置 token" : msg, "warn");
  }
}

function watchEventsPull(runId) {
  window.clearInterval(eventsPullTimer);
  setEventsPullBusy(true);
  const tick = () => {
    requestJsonOrMissing(`/api/events/pull/${encodeURIComponent(runId)}`, undefined, "事件拉取任务接口暂不可用")
      .then((row) => {
        if (!row) {
          finishEventsPull(null);
          return;
        }
        setHint("events-action-hint", eventsPullProgressText(row));
        if (row.status === "success" || row.status === "failed") {
          finishEventsPull(row);
        }
      })
      .catch((error) => {
        finishEventsPull(null);
        setHint("events-action-hint", `轮询失败：${error.message}`);
        showToast(error.message, "block");
      });
  };
  tick();
  eventsPullTimer = window.setInterval(tick, 1000);
}

async function resumeActiveEventsPull() {
  const payload = await requestJsonOrMissing("/api/events/pull/active", undefined, "事件拉取任务接口暂不可用");
  if (!payload) {
    return;
  }
  const active = payload.active;
  if (active && (active.inflight || active.status === "queued" || active.status === "running")) {
    setHint("events-action-hint", eventsPullProgressText(active));
    watchEventsPull(active.run_id);
  }
}

document.getElementById("events-pull")?.addEventListener("click", async () => {
  if (eventsPullBusy) {
    showToast("增减持拉取进行中，请勿重复点击", "warn");
    return;
  }
  setEventsPullBusy(true);
  setHint("events-action-hint", "排队中…");
  const start = document.getElementById("events-start")?.value || null;
  const end = document.getElementById("events-end")?.value || null;
  try {
    const payload = await requestJsonOrMissing(
      "/api/events/pull",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "tushare", start, end }),
      },
      "事件拉取接口暂不可用",
    );
    if (!payload) {
      setEventsPullBusy(false);
      setHint("events-action-hint", "");
      return;
    }
    if (payload.run_id) {
      watchEventsPull(payload.run_id);
      return;
    }
    // sync fallback (should not happen with async jobs)
    setEventsPullBusy(false);
    setHint("events-action-hint", formatEventsPullResult(payload));
    eventsViewState.page = 1;
    await loadEventsPage(1);
  } catch (error) {
    setEventsPullBusy(false);
    const msg = error.message || "";
    const busy = error.status === 409 || /进行中|busy/i.test(msg);
    const noToken = /token|TUSHARE|未配置|missing/i.test(msg);
    setHint(
      "events-action-hint",
      busy
        ? `拉取进行中：${msg}`
        : noToken
          ? `拉取失败：未配置 Tushare token（${msg}）。可先「导入 fixture」离线验证。`
          : `拉取失败：${msg}`,
    );
    showToast(
      busy ? "已有拉取任务进行中" : noToken ? "未配置 Tushare token，请先导入 fixture 或配置 token" : msg,
      "warn",
    );
    if (busy) {
      resumeActiveEventsPull().catch(() => {});
    }
  }
});

const TAGS_PAGE_SIZE = 10;
const tagsViewState = {
  page: 1,
  pages: 1,
  total: 0,
  seq: 0,
};

function renderTags(payload) {
  const body = document.getElementById("tags-body");
  const summary = document.getElementById("tags-summary");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (summary) {
    summary.innerHTML = "";
  }
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
      ? payload.items
      : [];
  const total = Array.isArray(payload) ? list.length : Number(payload?.total) || 0;
  const page = Array.isArray(payload) ? 1 : Number(payload?.page) || 1;
  const pages = Array.isArray(payload) ? 1 : Number(payload?.pages) || 1;
  const size = Array.isArray(payload) ? list.length || TAGS_PAGE_SIZE : Number(payload?.page_size) || TAGS_PAGE_SIZE;
  tagsViewState.page = page;
  tagsViewState.pages = pages;
  tagsViewState.total = total;
  const summaryRows = Array.isArray(payload?.summary)
    ? payload.summary
    : [];
  if (summary) {
    if (!summaryRows.length && !list.length) {
      const item = document.createElement("div");
      item.className = "kv-item";
      item.innerHTML = "<span>池</span><strong>暂无标签</strong>";
      summary.appendChild(item);
    } else {
      for (const row of summaryRows) {
        const tag = row.tag || "-";
        const count = Number(row.count) || 0;
        const item = document.createElement("div");
        item.className = "kv-item";
        const k = document.createElement("button");
        k.type = "button";
        k.className = "linkish";
        k.textContent = tag;
        k.title = `查看池 ${tag}`;
        k.addEventListener("click", () => {
          const input = document.getElementById("tags-filter-tag");
          if (input) {
            input.value = tag;
          }
          tagsViewState.page = 1;
          loadTagsList(1).catch((error) => showToast(error.message, "block"));
        });
        const v = document.createElement("strong");
        v.textContent = `${count} 只`;
        item.append(k, v);
        summary.appendChild(item);
      }
    }
  }
  if (!list.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty-hint";
    td.textContent = "暂无标签。宇宙同步或手工写入后会显示。";
    tr.appendChild(td);
    body.appendChild(tr);
  } else {
    for (const row of list) {
      const tr = document.createElement("tr");
      appendCell(tr, row.tag || "-");
      appendCell(tr, row.symbol || "-");
      appendCell(tr, row.source || "-");
      appendCell(tr, row.note || "-");
      appendCell(tr, formatDateTime(row.updated_at, false));
      body.appendChild(tr);
    }
  }
  setText("tags-page-label", `共 ${total} 条 · ${page} / ${pages} · 每页 ${size}`);
  const prev = document.getElementById("tags-prev");
  const next = document.getElementById("tags-next");
  if (prev) {
    prev.disabled = page <= 1 || total === 0;
  }
  if (next) {
    next.disabled = page >= pages || total === 0;
  }
  const tagFilter = document.getElementById("tags-filter-tag")?.value?.trim();
  setText(
    "tags-page-meta",
    total
      ? tagFilter
        ? `池 ${tagFilter} · 共 ${total} 只 · 第 ${page}/${pages} 页`
        : `共 ${total} 条 · 第 ${page}/${pages} 页`
      : "暂无匹配",
  );
}

function tagsViewQuery(page = tagsViewState.page) {
  const params = new URLSearchParams();
  const tag = document.getElementById("tags-filter-tag")?.value?.trim();
  const symbol = document.getElementById("tags-filter-symbol")?.value?.trim();
  if (tag) {
    params.set("tag", tag);
  }
  if (symbol) {
    params.set("symbol", symbol);
  }
  params.set("page", String(Math.max(1, Number(page) || 1)));
  params.set("page_size", String(TAGS_PAGE_SIZE));
  return params;
}

async function loadTagsList(page = tagsViewState.page) {
  const seq = ++tagsViewState.seq;
  const prev = document.getElementById("tags-prev");
  const next = document.getElementById("tags-next");
  if (prev) {
    prev.disabled = true;
  }
  if (next) {
    next.disabled = true;
  }
  const payload = await requestJsonOrMissing(
    `/api/tags?${tagsViewQuery(page).toString()}`,
    undefined,
    "标签接口暂不可用",
  );
  if (seq !== tagsViewState.seq) {
    return;
  }
  if (payload == null) {
    renderTags({ items: [], total: 0, page: 1, pages: 1, page_size: TAGS_PAGE_SIZE, summary: [] });
    setText("tags-page-meta", "接口暂不可用");
    return;
  }
  renderTags(payload);
}

async function loadTagsPage() {
  tagsViewState.page = 1;
  await loadTagsList(1);
}

document.getElementById("tags-filters")?.addEventListener("submit", (event) => {
  event.preventDefault();
  tagsViewState.page = 1;
  loadTagsList(1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("tags-prev")?.addEventListener("click", () => {
  if (tagsViewState.page <= 1) {
    return;
  }
  loadTagsList(tagsViewState.page - 1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("tags-next")?.addEventListener("click", () => {
  if (tagsViewState.page >= tagsViewState.pages) {
    return;
  }
  loadTagsList(tagsViewState.page + 1).catch((error) => showToast(error.message, "block"));
});

document.getElementById("tags-upsert-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const tag = document.getElementById("tags-upsert-tag")?.value?.trim();
  const symbol = document.getElementById("tags-upsert-symbol")?.value?.trim();
  const note = document.getElementById("tags-upsert-note")?.value?.trim() || null;
  if (!tag || !symbol) {
    showToast("请填写标签与代码", "warn");
    return;
  }
  try {
    const payload = await requestJsonOrMissing(
      "/api/tags",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: [{ tag, symbol, source: "manual", note }], actor: "operator" }),
      },
      "标签写入接口暂不可用",
    );
    if (!payload) {
      return;
    }
    setHint("tags-action-hint", `已写入 ${tag} / ${symbol}`);
    showToast("标签已写入", "ok");
    document.getElementById("tags-upsert-form")?.reset();
    await loadTagsPage();
  } catch (error) {
    setHint("tags-action-hint", `写入失败：${error.message}`);
    showToast(error.message, "block");
  }
});

function renderOverrides(rows) {
  const body = document.getElementById("override-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.className = "empty-hint";
    td.textContent = "暂无覆盖。可为策略添加强制纳入 / 剔除 / 权重上限。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of list) {
    const tr = document.createElement("tr");
    appendCell(tr, STRATEGY_LABEL[row.strategy_id] || row.strategy_id || "-");
    appendCell(tr, row.symbol || "-");
    appendCell(tr, OVERRIDE_ACTION_LABEL[row.action] || row.action || "-", {
      tone: row.action === "force_out" ? "block" : row.action === "force_in" ? "ok" : "accent",
    });
    appendCell(tr, row.weight == null || row.weight === "" ? "-" : formatPct(row.weight), { className: "num" });
    appendCell(tr, row.reason || "-");
    appendCell(tr, row.actor || "-");
    appendCell(tr, formatDateTime(row.updated_at, false));
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary";
    btn.textContent = "删除";
    btn.addEventListener("click", async () => {
      const ok = await confirmDialog(`删除覆盖 ${row.symbol}？`);
      if (!ok) {
        return;
      }
      try {
        const params = new URLSearchParams({
          strategy_id: row.strategy_id,
          symbol: row.symbol,
          actor: "operator",
        });
        const result = await requestJsonOrMissing(
          `/api/paper/overrides?${params.toString()}`,
          { method: "DELETE" },
          "覆盖接口暂不可用",
        );
        if (result == null) {
          return;
        }
        showToast("已删除覆盖", "ok");
        await loadOverridesPage();
      } catch (error) {
        showToast(error.message, "block");
      }
    });
    td.appendChild(btn);
    tr.appendChild(td);
    body.appendChild(tr);
  }
}

async function loadOverridesPage() {
  const params = new URLSearchParams();
  const strategyId = document.getElementById("override-strategy")?.value;
  if (strategyId) {
    params.set("strategy_id", strategyId);
  }
  const qs = params.toString();
  const rows = await requestJsonOrMissing(
    `/api/paper/overrides${qs ? `?${qs}` : ""}`,
    undefined,
    "覆盖接口暂不可用",
  );
  if (rows == null) {
    renderOverrides([]);
    setText("override-page-meta", "接口暂不可用");
    return;
  }
  renderOverrides(rows);
  setText("override-page-meta", `${rows.length} 条`);
}

document.getElementById("override-refresh")?.addEventListener("click", () => {
  loadOverridesPage().catch((error) => showToast(error.message, "block"));
});

document.getElementById("override-strategy")?.addEventListener("change", () => {
  loadOverridesPage().catch((error) => showToast(error.message, "block"));
});

document.getElementById("override-action")?.addEventListener("change", () => {
  const action = document.getElementById("override-action")?.value;
  const weight = document.getElementById("override-weight");
  if (!weight) {
    return;
  }
  weight.required = action === "force_in" || action === "cap";
  weight.disabled = action === "force_out";
  if (action === "force_out") {
    weight.value = "";
  }
});
document.getElementById("override-action")?.dispatchEvent(new Event("change"));

document.getElementById("override-upsert-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const strategyId = document.getElementById("override-strategy")?.value;
  const symbol = document.getElementById("override-symbol")?.value?.trim();
  const action = document.getElementById("override-action")?.value;
  const reason = document.getElementById("override-reason")?.value?.trim() || null;
  const weightRaw = document.getElementById("override-weight")?.value;
  if (!strategyId) {
    showToast("保存覆盖请先选择具体策略（不能是「全部」）", "warn");
    return;
  }
  if (!symbol || !action) {
    showToast("请填写代码与动作", "warn");
    return;
  }
  const body = {
    strategy_id: strategyId,
    symbol,
    action,
    reason,
    actor: "operator",
  };
  if (action === "force_in" || action === "cap") {
    if (weightRaw === "" || weightRaw == null) {
      showToast(`${OVERRIDE_ACTION_LABEL[action] || action} 需要权重`, "warn");
      return;
    }
    body.weight = Number(weightRaw);
  }
  try {
    const payload = await requestJsonOrMissing(
      "/api/paper/overrides",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      "覆盖接口暂不可用",
    );
    if (!payload) {
      return;
    }
    setHint("override-action-hint", `已保存 ${symbol} · ${OVERRIDE_ACTION_LABEL[action] || action}`);
    showToast("覆盖已保存", "ok");
    document.getElementById("override-symbol").value = "";
    document.getElementById("override-reason").value = "";
    document.getElementById("override-weight").value = "";
    await loadOverridesPage();
  } catch (error) {
    setHint("override-action-hint", `保存失败：${error.message}`);
    showToast(error.message, "block");
  }
});

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
applyLookup(localStorage.getItem("asqt-lookup") !== "0");
applyTasks(localStorage.getItem("asqt-tasks") === "1");
initSettingsCollapsiblePanels();
showPage(currentPage());
containPageWidth();
window.addEventListener("resize", containPageWidth);
refresh().catch((error) => {
  setText("runtime", `加载失败：${error.message}`);
  showActionError(`加载失败：${error.message}`);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopOverviewTasks();
    return;
  }
  if (currentPage() === "overview") {
    watchOverviewTasks();
  }
});
resumeActiveSync();
resumeActiveBacktest();
resumeActivePaperRun();
