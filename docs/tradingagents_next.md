# TradingAgents 可参考点 → ASQT 下一步实施方案

状态：**草案 / 待确认后开工**  
修订：2026-09-14  
**统一实施主干**（两项目合并优先级）：[adoption_priority_plan.md](adoption_priority_plan.md)  
来源仓库：`/Users/kimi/Documents/ChatGPT/TradingAgents`（[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)）  
A 股增强对照：[tradingagents_cn_next.md](tradingagents_cn_next.md)（TradingAgents-CN；与本文合并为一条实施路线）  
进度跟踪：仍以 [progress.md](progress.md) 为准；本文件只定义「从 TradingAgents 吸收什么、怎么落地」。

---

## 1. 结论（先读这段）

TradingAgents 是 **多 Agent LLM 美股研究框架**（LangGraph：分析师 → 多空辩论 → 交易员 → 风控三角辩论 → 组合经理终审），不是 A 股可复现量化交易系统。

对 ASQT **真正值得抄的是工程纪律，不是外壳**：

| 要吸收 | 不要吸收 |
|---|---|
| Point-in-time / 防前瞻日期窗口 | LangGraph 多 Agent 主链路 |
| 无数据 / 陈旧数据显式拒绝 | yfinance / Alpha Vantage / Reddit / Polymarket |
| 结构化决策枚举 + `REVIEW` 哨兵 | 多 LLM 厂商矩阵 |
| 决策日志 pending→结算（SQLite） | Markdown 决策记忆当主库 |
| 规则化「终审闸门」思想 | LLM Bull/Bear/Risk 辩论写仓 |

ASQT 主航道不变：**规则可复现研究 → 质量闸门 → 模拟盘运营**。LLM 若做，只能 `draft` 只读助手，禁止自动 `emit` 目标仓。

---

## 2. TradingAgents 模块地图（对照用）

| 层 | 路径 | 一句话 |
|---|---|---|
| 编排 | `tradingagents/graph/trading_graph.py` · `TradingAgentsGraph` | 跑图、checkpoint、memory、抽信号 |
| 拓扑 | `graph/setup.py` · `GraphSetup` | Analyst → Bull/Bear → RM → Trader → Risk×3 → PM |
| 契约 | `agents/schemas.py` · `rating.py` | 五档评级 / 三档动作；解析失败 → `REVIEW` |
| PIT | `dataflows/date_window.py` | 半开窗口；无日期条目仅 live 保留 |
| 数据路由 | `dataflows/interface.py` · `errors.py` | vendor 链 + 错误分类 + `NO_DATA` |
| 陈旧守卫 | `dataflows/stockstats_utils.py` | 截断未来 bar；过旧 OHLCV 拒绝 |
| 数值接地 | `dataflows/market_data_validator.py` | 确定性 asof 快照，防幻觉 |
| 记忆 | `agents/utils/memory.py` · `graph/reflection.py` | pending 决策 → 持有期后反思 |
| 报告 | `reporting.py` | 分节 markdown 树 |

---

## 3. 可参考能力筛选（优先级）

### P0 — 立即吸收

#### R1. 统一 Point-in-Time 规则
- **抄什么**：`date_window.in_window` / `withhold_live_profile` 的纪律（半开上界、无日期/无 vintage 在历史 asof 下拒绝）。
- **ASQT 落点**：新建 `asqt/pit.py`；`events` / `factor_pipeline` / `records` / 回测共用。
- **验收**：
  - `asof` 之后的 `event_date` / 因子日 / 行情日一律不可见；
  - 「无日期字段」在 backtest 模式失败或降级，live 可放行；
  - 单测风格对齐 `tests/test_*_lookahead.py`（不必字面移植）。
- **工作量**：3–5 人日。

#### R2. 无数据 / 陈旧数据守卫
- **抄什么**：`VendorError` 分类、`NO_DATA_AVAILABLE` 哨兵、`MAX_OHLCV_STALE_DAYS` 思想。
- **ASQT 落点**：适配器统一异常；质检加 `stale_asof`（按**交易日**而非自然日）；paper 撮合不得静默用过旧价。
- **验收**：故意把最新 bar 推到 asof 前超 N 个交易日 → warn/block 可配置且可复现。
- **工作量**：4–7 人日。

### P1 — 主航道增强

#### R3. 结构化决策契约 + `REVIEW`
- **抄什么**：`PortfolioRating` 五档、`TraderAction` 三档、`extract_rating` 失败不静默变 Hold（#1170）。
- **ASQT 落点**：`contracts` 增枚举；表 `research_decision` / 或扩现有审计；控制台复盘展示。
- **验收**：解析失败 → `REVIEW`，不会当成 Hold 下单；规则策略也可映射到五档（无 LLM）。
- **工作量**：3–5 人日。

#### R4. 规则化 Risk / PM 闸门
- **抄什么**：终审「approve / reject / review + 理由」；**实现用规则**，不抄 LLM 辩论。
- **ASQT 落点**：`asqt/risk_gate.py`，汇聚质检 `block`、kill switch、回撤 halt、lifecycle、override 冲突。
- **验收**：`build_orders` / admit 前唯一出口；稳定 `reason_code`；与飞书告警字段对齐。
- **工作量**：4–6 人日。

#### R5. Decision log（降级版）
- **抄什么**：pending → 持有期结算 → 结构化 outcome；`as_of` 过滤未结算 lesson。
- **ASQT 落点**：SQLite `decision_log`（禁止 markdown 主存）；`paper_jobs` 日终写 outcome。
- **验收**：paper-run 后可查「决策日→结果日」收益/是否急停；历史 asof 看不到未 resolved 条目。
- **工作量**：5–8 人日。

#### R6. 确定性市场快照 API
- **抄什么**：`build_verified_market_snapshot`。
- **ASQT 落点**：`GET /api/market/snapshot?asof=`；因子/选股预览共用。
- **验收**：同 asof 两次调用字节级一致（同 data_version）。
- **工作量**：2–3 人日。

### P2 — 可选 / 后置

| ID | 内容 | 说明 |
|---|---|---|
| R7 | Provider 路由增强 | 扩 `provider_registry`：priority / optional；事件与财务扩源时用 |
| R8 | 实验产物目录树 | 对齐 `write_report_tree` 思想，回测/paper 统一落盘约定 |
| R9 | 长任务 signature | 借鉴 checkpoint 图签名，防配置漂移续跑（不引入 LangGraph） |
| R10 | Draft LLM 研究助手 | 只读 parquet；输出进 `research_decision`；lifecycle=draft；**禁止写仓** |

---

## 4. 明确不做（边界）

1. 不引入 yfinance / Alpha Vantage 作为 A 股主路径。  
2. 不把 `llm_clients/` 多厂商矩阵拉进 ASQT 主依赖。  
3. 不接 Polymarket / Reddit / StockTwits / 加密管线。  
4. 不用 LangGraph 重写 FastAPI + SQLite jobs + cron。  
5. 不允许 LLM 辩论结果绕过质检 / 急停 / lifecycle 写目标仓。  
6. 不用 markdown 文件当决策日志主存储。  
7. 不做完整 Aggressive/Conservative/Neutral LLM 三角辩论。  
8. 不把美股 SPY alpha 反思基准硬塞进 paper 归因（若做基准用沪深300/中证500，且后置）。  
9. P4 券商、X3 财务全量、时点成分池等原边界不变。

---

## 5. 分阶段落地（建议开工顺序）

### 阶段 A — PIT + 数据守卫（约 1–1.5 周）
- 交付：`asqt/pit.py`、适配器异常统一、质检 `stale_asof`、回归单测。  
- 切入：`market_event` / `holder_net_in_window`、`factor_pipeline.series_asof`。  
- 完成定义：见 R1+R2 验收。

### 阶段 B — 决策契约 + Risk Gate（约 1–1.5 周）
- 交付：枚举 + `REVIEW`、`risk_gate.evaluate`、控制台展示拒绝原因。  
- 切入：`paper.generate_target_positions` / `build_orders`、`ops` kill switch、`overrides`。  
- 完成定义：见 R3+R4 验收。

### 阶段 C — Decision log 闭环（约 1 周）
- 交付：`decision_log` 表、paper 日终结算、复盘页可查。  
- 切入：`paper_jobs` + `#review`。  
- 完成定义：见 R5 验收；反思文案先规则模板，不做 LLM。

### 阶段 D — 路由 / 快照 / 可选助手（约 1–2 周）
- 交付：R6+R7+R8；R10 仅在明确需要时开。  
- 完成定义：快照可复现；新 schema 扩源不改路由核心；LLM 助手若开则无法写仓。

---

## 6. 三个最自然的切入点（开工优先序）

1. **事件 asof 硬化**（`asqt/events.py` + `event_jobs`）← `date_window`  
2. **因子/选股 asof + 快照**（`factor_pipeline` / `selectors`）← stale 守卫 + verified snapshot  
3. **模拟盘终审闸门 + 决策 ID**（`paper` / `ops` / `overrides`）← PM 思想规则化 + decision log  

---

## 7. 确认清单（开工前勾选）

- [ ] 同意「只抄工程纪律，不抄多 Agent LLM 主链路」  
- [ ] 同意阶段 A 先于任何 LLM 相关实验  
- [ ] 确认陈旧行情按交易日阈值（建议默认 5–10 个交易日，可配置）  
- [ ] 确认 `REVIEW` 在 paper 路径的行为：不下单 / 告警 / 人工处理  
- [ ] 确认本文件纳入 progress 后，再改代码  

确认后：先开阶段 A PR（`pit.py` + 事件/因子单测），再开阶段 B。
