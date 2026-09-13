# TradingAgents-CN 可参考点 → ASQT 下一步实施方案

状态：**草案 / 待确认后开工**  
修订：2026-09-14  
**统一实施主干**（两项目合并优先级）：[adoption_priority_plan.md](adoption_priority_plan.md)  
来源仓库：`/Users/kimi/Documents/ChatGPT/TradingAgents-CN`（[hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)）  
上游对照：[tradingagents_next.md](tradingagents_next.md)（TauricResearch/TradingAgents）  
进度跟踪：仍以 [progress.md](progress.md) 为准。

---

## 1. 结论（先读这段）

TradingAgents-CN = **上游多 Agent LLM 框架** + **A 股数据/本地化增强（开源）** + **FastAPI/Vue SaaS 壳（专有）**。

对 ASQT：

| 态度 | 内容 |
|---|---|
| **主干仍用上游方案** | PIT、陈旧守卫、`REVIEW`、`risk_gate`、decision_log、快照（见 [tradingagents_next.md](tradingagents_next.md)） |
| **CN 的增量价值** | A 股代码规范、多源降级配置、财务 `ann_date` PIT、选股 DSL 思想、模拟盘规则 checklist |
| **明确不抄** | `app/`、`frontend/` 专有代码；MongoDB+Redis 主栈；完整 LLM 分析 SaaS |

**版权硬约束**（`LICENSING.md` / README）：

- **可参考**：`tradingagents/`、`cli/`、`docs/`、`examples/`、`web/`（Streamlit）、`tests/` 等 Apache 2.0 部分的**设计与接口形状**。
- **禁止复制进 ASQT**：`app/`（FastAPI 后端）、`frontend/`（Vue 前端）专有实现。
- 落点一律 **ASQT 自研**；专有能力只作产品对照，不碰代码。

**统一路线**：不另开「CN 专项轨」。CN 增量嵌进上游阶段 A–D，避免两套并行。

---

## 2. 模块地图（开源 vs 专有）

| 区域 | 路径 | 许可 | ASQT 态度 |
|---|---|---|---|
| Agent / LangGraph | `tradingagents/graph/`、`agents/` | Apache | 只读对照；不引入主链路 |
| A 股数据 Provider | `tradingagents/dataflows/providers/china/` | Apache | 参考接口形状；自研落点 |
| 数据源管理 | `dataflows/data_source_manager.py` | Apache | 参考 priority/降级思想 |
| 完整性检查 | `dataflows/data_completeness_checker.py` | Apache | 强化质检 / stale |
| 设计文档 | `docs/design/`、`docs/guides/`、`docs/development/architecture/` | 文档 | **优先吸收思想** |
| Streamlit 旧 Web | `web/` | Apache | 可参考报告导出形态 |
| FastAPI + Vue | `app/`、`frontend/` | **专有** | **禁止复制** |

相对上游：CN **代码里几乎没有**等价的 `date_window` / `REVIEW` / decision log PIT；这些仍以上游方案为准。CN 强在 **A 股数据与产品设计文档**。

---

## 3. CN 增量可参考清单（相对上游）

### 值得写入统一路线的增量

#### C1. 多源降级 = 配置化优先级（非再写三套业务）
- **是什么**：`DataSourceManager` + `providers/china/{tushare,akshare,baostock}`；按可用性/市场选源。
- **对 ASQT 价值**：三源已有，但 `provider_registry` 偏薄；扩事件/财务时需要「主源失败 → 备源」可观测降级。
- **落点**：扩 `provider_registry.py`（priority / optional / schema）；**不要**引入 Mongo 当最高优先级缓存。
- **优先级**：P1（并入上游 R7）  
- **工作量**：3–5 人日  
- **与 next 关系**：强化 R7，不是新轨。

#### C2. A 股代码规范化边界（含北交所）
- **是什么**：6 位码 ↔ `XXXXXX.SH|SZ|BJ` ↔ BaoStock `sh./sz.`；`stock_validator` / Provider 内 normalize。
- **对 ASQT 价值**：主口径已是带后缀；可补 **BJ**、纯 6 位输入、错误后缀的拒绝矩阵，减少拉数/事件静默错码。
- **落点**：`asqt/symbols.py` + 适配器入口单测矩阵。
- **优先级**：P1  
- **工作量**：1–2 人日  
- **与 next 关系**：**不重复**（上游无 A 股问题）。

#### C3. 数据完整性 / 「是否含最新交易日」
- **是什么**：`DataCompletenessChecker`（区间空洞、最新交易日是否到位）。
- **对 ASQT 价值**：与质检同源；直接强化「asof 前行情是否过旧」。
- **落点**：并入 `quality` + 上游 R2 `stale_asof`（按**交易日**）。
- **优先级**：P0–P1（并入阶段 A）  
- **工作量**：+1–2 人日（挂在 R2 上）  
- **与 next 关系**：强化 R2。

#### C4. 复权口径显式声明（qfq / hfq / none）
- **是什么**：Provider 与筛选文档里显式 `adj` / `adjustflag`。
- **对 ASQT 价值**：研究用 `close*adj_factor`、展示/下单用未复权——需在契约与 glossary 钉死，避免混用。
- **落点**：`contracts` / [glossary.md](glossary.md) + 拉取/预览 API 参数说明。
- **优先级**：P1  
- **工作量**：1–2 人日  
- **与 next 关系**：不重复。

#### C5. 财务 / 事件必须以 `ann_date` 做 PIT
- **是什么**：财务模型与 `fundamentals_snapshot`；文档强调公告日字段。
- **对 ASQT 价值**：A 股特有；未来 X3 财务入库时，**可知日 = ann_date**，不是仅报告期。与现有 `market_event.asof_date` 同构。
- **落点**：财务/公告 schema 预留 `ann_date` + `report_period`；先 PIT 规则，后全量拉数。
- **优先级**：P2（X3 后置，但 schema 可先定）  
- **工作量**：schema 1 人日；全量 5–10 人日  
- **与 next 关系**：补上游美股框架不会强调的空白。

#### C6. 选股 DSL（条件树 + 字段白名单）
- **是什么**：设计见 `docs/development/architecture/screening_a_shares_daily_p0.md`；实现多在 **`app/services/screening*`（专有，勿抄）**。
- **对 ASQT 价值**：`selectors.py` 可演进为 AND/OR、交叉上穿等规则 DSL，服务因子预览与策略参数，无需 Mongo。
- **落点**：**自研**扩展 `selectors`；禁止复制专有筛选服务。
- **优先级**：P1–P2  
- **工作量**：4–7 人日  
- **与 next 关系**：不重复。

#### C7. 模拟盘 A 股微观结构 checklist
- **是什么**：`docs/design/paper_trading_multi_market_design.md`（T+1、涨跌停、手数、停牌等）。
- **对 ASQT 价值**：P3 paper **大多已实现**；用文档当差距清单与回归用例，避免漏测。
- **落点**：`tests/test_p3_paper.py` 对照清单补断言；缺口再补逻辑。
- **优先级**：P1  
- **工作量**：1–3 人日  
- **与 next 关系**：与 R4 risk_gate 互补。

### 低优先 / 仅产品启发（不进近程）

| ID | 内容 | 说明 |
|---|---|---|
| C8 | `china_market_analyst` Prompt | 未进默认图拓扑；只抽规则检查项进 quality/risk_gate，不做 Agent |
| C9 | 新闻中文过滤 | 非主航道；事件要文本源时再自研 |
| C10 | 多周期日/周/月 | 主航道日频；暂缓 |
| C11 | SSE / 批量 LLM / 自选股 / 权限 | 专有产品能力；ASQT 轻量控制台已够用或自研极简进度 |
| C12 | 报告 MD/DOCX/PDF | 对齐上游 R8；可选 |

---

## 4. 明确不要做

1. **禁止复制** `app/`、`frontend/` 任何实现（screening、paper、SSE、auth、worker 等）。  
2. **禁止**用 MongoDB + Redis 替换 SQLite + Parquet。  
3. **禁止**引入完整 LLM 分析 SaaS（用户体系、模型市场、批量 Agent 流水线）。  
4. **禁止** LangGraph 多 Agent 写仓（同上游方案）。  
5. **禁止**把「面向 LLM 的长字符串行情」当 ASQT 标准契约（保持结构化行/parquet）。  
6. **不要**并行维护「上游纪律轨」与「CN 产品轨」——只保留本文 + `tradingagents_next.md` 合并后的一条线。  
7. 商业使用以 CN 仓库 LICENSE/README 为准；ASQT **以自研实现为主**最稳妥，开源目录也优先「思想 + 重写」而非大段搬迁。

---

## 5. 合并后的分阶段路线（唯一主干）

| 阶段 | 上游主干 | 嵌入的 CN 增量 | 完成定义 |
|---|---|---|---|
| **A** PIT + 数据守卫 | R1 `pit.py` + R2 stale | C3 完整性；C4 复权声明；C2 符号/BJ 边界 | asof 不可见未来；陈旧按交易日；符号单测 |
| **B** 决策契约 + Risk Gate | R3 `REVIEW` + R4 `risk_gate` | C7 paper 规则差距清单 | 下单唯一闸门；稳定 `reason_code` |
| **C** Decision log | R5 | （无 CN 必选项） | pending→结算可查 |
| **D** 快照 / 路由 / 产物 | R6–R8 | C1 registry 降级；C6 selectors DSL（自研） | 快照可复现；筛选不依赖 Mongo |
| **E 后置** | — | C5 财务 `ann_date`；新闻；多周期；draft LLM | 不挡主航道 |

开工顺序：**A → B → C → D**；确认清单见下节。

---

## 6. 三个最自然的切入点

1. **事件/因子 asof 硬化（阶段 A）** — 上游 `date_window` 纪律 + CN「最新交易日/完整性」思想。  
2. **`provider_registry` 降级 + 符号边界（阶段 A/D）** — 对照 `DataSourceManager`，配置留在 ASQT。  
3. **paper 闸门回归 + selectors DSL（阶段 B/D）** — checklist 补测；选股条件树自研。

---

## 7. 相对「只学上游」多出来的 5 条（务必保留）

1. **A 股代码三套互转边界**（6 位 / 交易所后缀 / BaoStock 前缀，含 BJ）。  
2. **多源降级是配置化优先级**，不是再写三套业务；缓存仍用现有栈。  
3. **财务/公告 PIT 用 `ann_date`（可知日）**，不能只用报告期。  
4. **选股 DSL 与 `selectors`/因子规则同构**（条件树 + 白名单 + 复权参数）；实现自研。  
5. **模拟盘微观结构用 CN 设计文档当 checklist**，对照 ASQT 已实现项做回归，不重做 Mongo paper。

---

## 8. 确认清单（开工前勾选）

- [ ] 同意以上游 [tradingagents_next.md](tradingagents_next.md) 为工程纪律主干  
- [ ] 同意 CN 只追加 A 股数据契约 / DSL / checklist，不另开产品轨  
- [ ] 确认 **不复制** `app/`、`frontend/`  
- [ ] 确认不引入 MongoDB/Redis 替换主存储  
- [ ] 确认阶段 A 先于任何 LLM / 财务全量  
- [ ] 确认本文件与上游方案一并纳入 progress 后再改代码  

确认后：先开阶段 A（`pit.py` + stale + 符号边界），再开阶段 B。
