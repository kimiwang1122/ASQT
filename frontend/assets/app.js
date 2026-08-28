const PAGE_TITLES = {
  overview: "系统总览",
  data: "数据",
  strategy: "策略",
  orders: "交易",
  review: "复盘",
  settings: "设置",
};

async function requestJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function currentPage() {
  const hash = (location.hash || "#overview").replace("#", "");
  return PAGE_TITLES[hash] ? hash : "overview";
}

function showPage(page) {
  document.querySelectorAll(".page").forEach((section) => {
    section.classList.toggle("hidden", section.id !== `page-${page}`);
  });
  document.querySelectorAll("#nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === page);
  });
  setText("page-title", PAGE_TITLES[page]);
}

function renderMarket(records) {
  const body = document.getElementById("market-body");
  body.innerHTML = "";
  if (!records.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.textContent = "暂无行情。请先初始化演示数据。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of records) {
    const tr = document.createElement("tr");
    for (const key of ["trade_date", "symbol", "open", "high", "low", "close", "volume", "source"]) {
      const td = document.createElement("td");
      td.textContent = row[key];
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
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
    const right = document.createElement("span");
    left.textContent = `${task.task_name} ${task.started_at}`;
    right.textContent = task.status;
    right.className = task.status === "success" ? "success" : "";
    li.append(left, right);
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
    for (const key of ["source_id", "name", "auth_status", "quota", "cost", "owner", "health_status"]) {
      const td = document.createElement("td");
      td.textContent = row[key] ?? "-";
      tr.appendChild(td);
    }
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
    right.textContent = "未接入";
    right.className = "muted";
    li.append(left, right);
    list.appendChild(li);
  }
}

async function refresh() {
  const [health, status, market, sources, ports] = await Promise.all([
    requestJson("/api/health"),
    requestJson("/api/status"),
    requestJson("/api/market/daily"),
    requestJson("/api/data-sources"),
    requestJson("/api/ports"),
  ]);

  setText("runtime", health.status === "ok" ? "运行正常 · 业务模块未接线" : "运行异常");
  setText("source-count", status.data_sources);
  setText("instrument-count", status.instruments);
  setText("quality-count", status.open_quality_issues);
  setText("alert-count", status.open_alerts);
  setText(
    "market-file",
    status.market_files[0] ? `${status.market_files[0].row_count} 行` : "无行情文件",
  );
  renderMarket(market);
  renderTasks(status.recent_tasks || []);
  renderSources(sources);
  renderPorts(ports);
  renderKv("data-summary", [
    ["交易日历行数", status.trade_calendar_rows],
    ["涨跌停/停牌行数", status.limit_suspension_rows],
    ["因子信号行数", status.factor_signal_rows],
    ["开放质量问题", status.open_quality_issues],
  ]);
  renderKv(
    "layout-grid",
    Object.entries(status.layout || health.layout || {}).map(([k, v]) => [k, v]),
  );
}

function applyTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  localStorage.setItem("asqt-theme", mode);
  document.getElementById("theme-dark").classList.toggle("active", mode === "dark");
  document.getElementById("theme-light").classList.toggle("active", mode === "light");
}

document.getElementById("bootstrap").addEventListener("click", async () => {
  await requestJson("/api/admin/bootstrap", { method: "POST" });
  await refresh();
});

document.getElementById("theme-light").addEventListener("click", () => applyTheme("light"));
document.getElementById("theme-dark").addEventListener("click", () => applyTheme("dark"));

window.addEventListener("hashchange", () => showPage(currentPage()));

applyTheme(localStorage.getItem("asqt-theme") || "dark");
showPage(currentPage());
refresh().catch((error) => {
  setText("runtime", `加载失败：${error.message}`);
});
