# ASQT 可参考吸收：完整优先级实施方案

状态：**草案 / 待确认后开工**（本文为唯一实施主干）  
修订：2026-09-14  
来源：
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) → 详见 [tradingagents_next.md](tradingagents_next.md)
- [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) → 详见 [tradingagents_cn_next.md](tradingagents_cn_next.md)

本地克隆：`/Users/kimi/Documents/ChatGPT/TradingAgents`、`…/TradingAgents-CN`  
进度跟踪：确认后写入 [progress.md](progress.md)。

---

## 0. 总原则

| 原则 | 含义 |
|---|---|
| 主航道不变 | 规则可复现研究 → 质量闸门 → 模拟盘运营；P4 券商仍暂缓 |
| 上游贡献纪律 | PIT、陈旧守卫、结构化决策、`REVIEW`、规则终审、decision log、快照 |
| CN 贡献 A 股增量 | 符号边界、多源降级、复权声明、`ann_date`、选股 DSL、paper checklist |
| 只抄思想与契约 | 落点一律 ASQT 自研；不引入 LangGraph / 多 LLM 写仓 |
| 版权红线 | **禁止复制** TradingAgents-CN 的 `app/`、`frontend/`；不换 Mongo+Redis 主栈 |

**分工一句话**：上游解决「研究真不真、决策能不能审计」；CN 解决「A 股数据与规则边角」；两者嵌进同一条阶段线，不双轨。

---

## 1. 优先级总表（按开工顺序）

| 优先级 | ID | 项 | 主要来源 | ASQT 落点 | 粗估 | 依赖 |
|---|---|---|---|---|---|---|
| **P0** | A1 | 统一 Point-in-Time（`pit.py`） | 上游 `date_window` | `asqt/pit.py`；事件/因子/records | 3–5d | — |
| **P0** | A2 | 无数据 / 陈旧行情守卫（交易日） | 上游 stale + CN 完整性 | 适配器异常；`quality.stale_asof`；paper 拒用过旧价 | 4–7d | A1 宜并行 |
| **P0** | A3 | A 股符号边界（含 BJ / 6 位互转） | CN providers / validator | `asqt/symbols.py` + 适配器入口单测 | 1–2d | — |
| **P0** | A4 | 复权口径显式声明 | CN adj/qfq 文档 | glossary + 契约/API 注释（研究复权 vs 下单未复权） | 1d | — |
| **P1** | B1 | 决策枚举 + `REVIEW` 哨兵 | 上游 rating/schemas | `contracts`；解析失败不下单 | 3–5d | — |
| **P1** | B2 | 规则化 `risk_gate` 终审 | 上游 PM 思想 | `asqt/risk_gate.py` → admit / `build_orders` | 4–6d | B1 |
| **P1** | B3 | Paper 微观结构回归清单 | CN paper 设计文档 | 对照 T+1/涨跌停/手数/停牌补 `test_p3_paper` | 1–3d | B2 可并行 |
| **P1** | C1 | Decision log（pending→结算） | 上游 memory（降级） | SQLite `decision_log`；paper 日终 | 5–8d | B1 |
| **P1** | D1 | 确定性市场快照 API | 上游 market_data_validator | `GET /api/market/snapshot?asof=` | 2–3d | A1/A2 |
| **P1** | D2 | Provider registry 降级链 | 上游 R7 + CN DataSourceManager | `provider_registry`：priority / optional | 3–5d | — |
| **P2** | D3 | Selectors 条件 DSL | CN 筛选设计（**自研**，不抄 `app/`） | 扩 `selectors.py`：AND/OR、交叉等 | 4–7d | D1 更佳 |
| **P2** | D4 | 实验产物目录树 | 上游 reporting | 回测/paper 统一落盘约定 | 1–2d | — |
| **P2** | D5 | 长任务 run signature | 上游 checkpoint 模式 | event/factor/paper jobs 防配置漂移续跑 | 2–4d | — |
| **P2** | E1 | 财务 schema：`ann_date` PIT | CN 财务文档 | 契约预留；全量拉数后置（X3） | schema 1d / 全量 5–10d | A1 |
| **P3** | E2 | Draft LLM 只读助手 | 两项目外壳（严格降级） | lifecycle=draft；禁止写仓 | 大 | B1+D1 |
| **P3** | E3 | 新闻过滤 / 多周期 K | CN 周边 | 暂缓；非主航道 | 大 | — |

合计近程（P0+P1，不含 E）：约 **4–6 周**一人满负荷；可按阶段拆 PR。

---

## 2. 分阶段实施（唯一时间线）

### 阶段 A — 数据真（约 1–1.5 周）｜P0

**目标**：回测/事件/因子/模拟不再偷看未来，也不静默用过期行情。

| 交付 | 验收 |
|---|---|
| `asqt/pit.py`：半开窗口；live vs backtest 对无日期字段策略 | 未来 `event_date`/因子日/行情日单测必失败 |
| 适配器 `NoMarketData` / `StaleData`；质检 `stale_asof`（N 个**交易日**，可配，建议 5–10） | 过旧 bar → warn/block；paper 不静默撮合 |
| 符号矩阵：6 位、`.SH/.SZ/.BJ`、非法后缀 | 单测覆盖；错码拒收 |
| glossary/契约写清复权场景 | 研究用复权收益、下单用未复权价 |

**切入文件**：`events.py`、`factor_pipeline.py`、`quality.py`、`symbols.py`、`adapters/*`

---

### 阶段 B — 下单稳（约 1–1.5 周）｜P1

**目标**：admit/下单唯一闸门；失败可审计，不伪装成 Hold。

| 交付 | 验收 |
|---|---|
| 五档/三档枚举 + `REVIEW` | 解析失败 → `REVIEW`，**不下单** |
| `risk_gate.evaluate(...)` 汇聚：质检 block、kill、回撤、lifecycle、override 冲突 | 稳定 `reason_code`；控制台/飞书可读 |
| Paper checklist 回归 | T+1 可卖、涨跌停拒单、手数、停牌有断言 |

**切入文件**：`contracts.py`、新建 `risk_gate.py`、`paper.py`、`ops.py`、`overrides.py`、前端交易/复盘提示

---

### 阶段 C — 复盘清（约 1 周）｜P1

**目标**：「为何选 → 持有后怎样」可查。

| 交付 | 验收 |
|---|---|
| 表 `decision_log`（pending → resolved） | paper-run 后可查决策日→结果日收益/急停 |
| 日终写结构化 outcome（模板反思，无 LLM） | 历史 asof 看不到未结算 lesson |
| 订单/目标仓可挂 `decision_id` | 与 `#review` 对齐 |

**切入文件**：`db.py`、`paper_jobs.py`、复盘前端

---

### 阶段 D — 扩展面（约 1–2 周）｜P1–P2

**目标**：预览与交易同真相；扩源/选股不改核心。

| 交付 | 验收 |
|---|---|
| `/api/market/snapshot?asof=` | 同 asof + data_version 两次一致 |
| `provider_registry` priority/optional | 新 schema 扩源只改声明表 |
| `selectors` DSL（自研） | 控制台预览可用；**零** CN `app/` 代码 |
| （可选）报告目录树、job signature | 产物可找；改配置不能瞎续跑 |

---

### 阶段 E — 后置｜P2–P3

| 项 | 条件 |
|---|---|
| 财务全量 + `ann_date` PIT | X3 解冻后；先 schema 后拉数 |
| Draft LLM 助手 | 仅只读；lifecycle=draft；永不 `emit` 仓位 |
| 新闻/多周期 | 有明确产品需求再开 |

---

## 3. 价值对照（为何是这个顺序）

| 阶段 | 解决的问题 | 不先做的后果 |
|---|---|---|
| A 数据真 | 前视偏差、过期行情假运行 | 后面闸门/日志都建立在假世界上 |
| B 下单稳 | 风控分散、失败变 Hold | 模拟盘「看起来在交易」实则越权 |
| C 复盘清 | 只有净值没有因果 | 无法迭代策略与运营 |
| D 扩展面 | 预览不一致、扩源痛苦 | 能跑但不便扩展 |
| E 后置 | 财务/LLM 好看 | 易膨胀、破坏可复现 |

---

## 4. 明确不做（合并边界）

1. LangGraph 多 Agent / Bull-Bear / 三角风控辩论写仓  
2. 多 LLM 厂商矩阵进主依赖；yfinance/AlphaVantage/Reddit/Polymarket/加密主路径  
3. 复制 TradingAgents-CN 的 `app/`、`frontend/`  
4. MongoDB+Redis 替换 SQLite+Parquet  
5. 完整用户权限 / 模型市场 / 批量 LLM 分析 SaaS  
6. Markdown 文件当决策主存储  
7. LLM 结果绕过质检 / 急停 / lifecycle  
8. 并行两套「上游轨 / CN 轨」路线图  
9. 提前做 P4 券商、时点成分池、财务全量（除非单独解冻）

---

## 5. 建议 PR 切片

| PR | 内容 | 预估 |
|---|---|---|
| PR-A1 | `pit.py` + events/factors 单测 | 小–中 |
| PR-A2 | stale_asof + 适配器异常 + paper 守卫 | 中 |
| PR-A3 | symbols BJ/6 位矩阵 + 复权 glossary | 小 |
| PR-B1 | 决策枚举 + `REVIEW` | 小–中 |
| PR-B2 | `risk_gate` + 接入 paper + UI 原因码 | 中 |
| PR-B3 | paper checklist 测试补齐 | 小 |
| PR-C1 | `decision_log` + 日终结算 + 复盘展示 | 中 |
| PR-D1 | market snapshot API | 小 |
| PR-D2 | provider_registry 降级 | 中 |
| PR-D3 | selectors DSL（可选） | 中 |

---

## 6. 确认清单

- [ ] 同意本文为**唯一**吸收实施主干（两份 next 文档降为附录）  
- [ ] 同意阶段 A → B → C → D，E 默认不做  
- [ ] 陈旧阈值按交易日，默认区间可配  
- [ ] `REVIEW` = 不下单 + 可告警  
- [ ] 不复制 CN 专有目录、不换存储栈、不上 LLM 写仓  
- [ ] 确认后写入 `progress.md` 再改代码  

确认后从 **PR-A1（`pit.py`）** 开工。
