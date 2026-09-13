# ASQT 词汇表

状态：**现行参考件**（解释本仓库口径，不是交易所国家标准）  
修订：2026-09-13  
进度：[progress.md](progress.md)  
冻结：[p0/README.md](p0/README.md)

聊天里问过的词优先收录；之后遇到新术语在本表追加，避免口头口径和代码分叉。检查类型中文对照仍以 [console_fixes.md](console_fixes.md) 为准。

## 怎么追加

1. 先检索本表，已有条目只改释义，不新开同义行（可在「亦称」里加别名）。
2. 新词按主题插入对应节；码/英文用 `` `code` ``。
3. 改冻结口径仍改 `docs/p0/`，本表只解释「我们怎么用这个词」。

---

## 阶段与未决问题

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| Pre-P0 / P0–P4 | 实施阶段 | 工程基座 → 方案冻结 → 数据质检 → 回测 → 本地模拟 → 接券商。P0 是「先写文件不写业务」，不是 PRD 里的「一期必做」。 |
| Q1–Q7 | 未决问题 | 见 [p0/open_questions.md](p0/open_questions.md)。Q2=券商模拟盘权限；Q3=策略方向（已关）；Q4=告警通道（已关为飞书）；Q6=历史成分时点（已降级）。 |
| POC | 最小可运行样本 | 固定约 56 股 + 6 ETF，用来跑通拉数/质检/模拟，不是全市场产品。 |
| X3 | 策略验证后数据 | 分钟 K、财务、预告、股东人数、两融、北向；接口可在 Tushare，尚未入库。 |
| X4 | 一期不做 | Tick、Level2、期货、港美股、北交所。 |

## 数据与质检

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| 日 K | `market_daily` | 每个交易日一根 OHLC、量额、复权因子。主源 BaoStock。 |
| 未复权 / 复权 | OHLC vs 可比价 | **口径勿混**：表里 OHLC 是成交价（未复权）；研究收益/因子用 `close * adj_factor`（后复权可比价）。**Paper 撮合与下单股数只用未复权价。** 禁止用复权价算仓位股数。 |
| `adj_factor` | 后复权因子 | 当日有效。缺失则该行不得进可交易版本。研究场景默认依赖该因子；展示 K 线若需前复权须另算，不得回写 OHLC。 |
| `adj_conflict` | 复权冲突 | 质检：因子跳变且无已核实送转分红解释。 |
| `estimated_from_preclose` | 前收估算 | 涨跌停价来源：前收 × 板块幅度（主板约 10%，创业/科创约 20%），不是交易所公布价。 |
| 官方日历 / 官方涨跌停 | D7 未做的重口径 | 上交所/深交所全表日更；现在用主源开市日 + 估算限价。 |
| 时点池 | 历史成分 | 回测某日只用**当时**指数成分。现在是筛选日固定名单，有前视偏差风险。 |
| `point_in_time` | 时点错误 | 质检：上市前或退市后仍有行情。 |
| PIT / `asqt.pit` | 时点窗口 | 统一 `asof`：只见 `date <= asof`；backtest 丢无日期字段；见 [adoption_priority_plan.md](adoption_priority_plan.md) GATE-A1。 |
| `REVIEW` / `asqt.decision` | 决策哨兵 | 五档/三档评级；解析失败为 `REVIEW`，禁止静默变 Hold。 |
| `risk_gate` | 终审闸门 | `evaluate(purpose=orders|admit)` 唯一出口；稳定 `reason_code`（如 `quality_block` / `kill_switch` / `stale_data`）。 |
| `decision_log` | 决策日志 | SQLite pending→resolved；`thesis_json`/`outcome_json` 主存（禁 markdown）；`GET /api/decisions?asof=` PIT 过滤。目标仓/订单可挂 `decision_id`。 |
| `missing` / `range` / `cross_source` | 质检类型 | 缺数；OHLC/量额非法；主备源对不上（`warn`，不单独停交易）。 |
| `stale_asof` | 行情过旧 | 最新日 K 相对 asof 落后超过 N 个**交易日**（默认 5，`ASQT_STALE_MAX_SESSIONS`）。严重级别 `ASQT_STALE_SEVERITY=warn|block`；block 时 paper 拒单 `stale_data`。 |
| `block` / `warn` | 严重级别 | `block` 开放则 `trade_allowed=false`，禁新订单；`warn` 不翻转闸门。 |
| 闸门 | `trade_allowed` | 质量门禁：有开放 block 就不能下新单（mock 与 Paper 一致）。 |
| 主源 / 备源 / peer | BaoStock / AkShare / Tushare | 交易主路径只用主源；备源和对账源不驱动下单。 |
| 积分 / VIP | Tushare 权限 | Token 能调接口不等于能拉分钟/财务 VIP；档位不够会拒。 |
| 公司行为 | 送转分红配股 | 完整事件主数据未做；少量 CSV 只抑制 `adj_conflict` 误报。 |
| 北向 | 沪深股通 | 陆股通资金/持股；X3，未入库。 |
| 两融 | 融资融券 | 汇总/明细/标的；X3，未入库。 |
| Record | `records` / schema | 注册表驱动的标准数据：`RECORD_SCHEMAS` → parquet `data/standard_data/{schema}.parquet`；`upsert_records` 按 PK 幂等合并，`query_records` 过滤查询。首期 `market_daily`、`market_event`。 |
| `market_event` | 市场事件 | 统一事件行：`event_id/type/symbol/event_date/asof_date/…`。可 fixture 导入或 Tushare `stk_holdertrade` 拉取；查询/策略只看 `event_date <= asof`。 |
| `holder_increase` / `holder_decrease` | 股东增减持 | 已落地的事件类型；净增持窗口见 `events.holder_net_in_window`。 |

## 行情粒度与成交摩擦

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| Tick | 逐笔成交 | 每一笔成交一条记录。一期不做。 |
| Level2 | 十档盘口 | 买卖各十档量价。一期不做。 |
| 分钟 K | `stk_mins` 等 | 1/5/15/30/60 分钟线。X3，未入库。 |
| 滑点 | slippage | 成交价相对理想价（次日开盘）的偏差。模拟里一次性加在开盘价上。 |
| 5bp | 5 个基点 | 0.05% = `SLIPPAGE = 0.0005`。买往上、卖往下。 |
| T+1 | 信号日 vs 成交日 | T 日收盘定目标仓，T+1 开盘撮合；当日买入当日不能卖。 |
| 理想价 | 次日开盘 | Paper 默认撮合价，再叠加 5bp。 |

## 策略与研究

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| 动量 | `stock_momentum_topk` | 近约 20 日涨得多的股票里选 TopK（默认 5）。 |
| ETF 均线轮动 | `etf_ma_rotate` | ETF 相对 20 日均线轮动，规则策略。 |
| ETF 动量 TopK | `etf_momentum_topk` | ETF 池内近窗动量取 TopK；独立 `parameter_set_id`。 |
| 股票短反转 TopK | `stock_short_reversal_topk` | 股票池内近窗收益取负（`factors.reversal`）取 TopK；现行 `k2.l10`（短窗高换手 `k5.l5` 已弃用）；可选 `rebalance_every_n` 降频。 |
| 股东增持跟随 | `stock_holder_increase_follow` | 近 N 日股东净增持命中 + 可选动量过滤，经 Selector 出权；默认 `draft`，不自动准入 paper。参数组 `k5.e20.l20`。 |
| Factor pipeline | 因子三段式 | `build_data_frame` → `compute_factor_frame` → `select_targets`（result）。可全窗预计算后再按日取靶；`factor_signal` 带 `params_hash` 避免同名不同窗互盖。 |
| Selector | TargetSelector / `selectors` | 按 top_k / filter / clip 规则从因子行选出当日权重；对齐 `STRATEGY_SPECS`；`POST /api/selectors/preview` 不写 paper。 |
| 目标仓 | target position | 策略输出权重/数量，不直接报券商单。写库前可经 `paper_override` 改写。 |
| 生命周期 | draft→…→paper | 仅 `paper` 可生成可下单目标仓。`candidate` 还不能下单。 |
| 前视 / 未来函数 | look-ahead | 用后来才知道的信息回测昨天。时点池、公告日、`event_date <= asof` 就是为了防这个。 |
| `symbol_tag` | 标签 / 池 | `(tag, symbol)` 可查询标签；宇宙 CSV 的 `pool` 同步为 `source=universe_csv`。策略 params 可选 `pool_tags`。 |
| `paper_override` | 人工覆盖 | 按 `(strategy_id, symbol)`：`force_in` / `force_out` / `cap` 改写目标仓；`reason` 标 `override:*`；写 `operation_audit`。 |
| IS / OOS | 样本内 / 外 | 按时间切开（约前 70% / 后 30%）；信号日只看 `trade_date <= asof`。样本内用来定规则，样本外检验是否还能赚。 |
| 复盘 | `#review` / 归因 | 把回测收益拆到标的，并对照 Paper 净值。接口 `GET /api/research/attribution`；决策表 `GET /api/decisions`。加强展示：样本天数、贡献占比、OOS Top/拖累、参数组、样本区间、Paper vs 回测表。 |
| 净值 / 复利收益 | `nav` / `total_return` | 每日组合收益连乘；复利收益 = 净值 − 1。不含滑点费用。 |
| 累加贡献 | `additive_return` | 各日「权重 × 复权收益」加总。一般略不等于复利（连乘交叉项）。 |
| 持有日 / 平均权重 | `days` / `avg_weight` | 该标的在目标仓中的天数与这些天的平均仓位。 |
| 模拟偏差 | `max_abs_nav_gap` | Paper 净值相对同一信号回测净值的最大相对偏离。 |
| R9 / Qlib bin | `data/qlib_data/` | 预留把日 K 转成 Qlib 二进制；业务层禁止 `import qlib`。未接线。 |
| QMT stub | `qmt_broker` | 预留执行适配器，`available=false`；等 Q2 权限，禁止标成已接。 |

## 订单、模拟与资金

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| paper | 模拟盘 / 状态 | ① 策略已准入本地模拟；② `PaperBroker` 本地撮合，不是券商。 |
| `idem_key` | 幂等键 | 策略 + 交易日 + 标的 + 方向。重试不得生成第二张有效单。 |
| 子订单 / 拆单 | child orders | 实盘或算法把一笔委托拆成多笔。P3 不把一张 `standard_order` 拆成 N 张业务单；多笔成交应落 `execution_fill`。 |
| `partial_filled` | 部分成交 | 订单状态机有；Paper 现为 1 单 1 次开盘全成。 |
| 成交额 / 数量 | notional / qty | 额 = 数量 × 价；财务对账：现金不含浮盈。 |
| 财务对账 | cash reconcile | 期末现金 = 本金 − 买入额 + 卖出额 − 费用；持仓数量 = 买 − 卖。认成交当时 `fee`，不用设置页现值重算。 |
| 佣金 / 印花税 / 过户费 | 费用三件 | 佣金可配置（默认万分之 2.5，最低 5 元）；卖出印花税 0.05%；沪市过户费。写入该笔 `fee`。 |
| 本金 / 净值 / 峰值回撤 | initial / NAV / DD | 收益相对该账本金；急停 −12% 是相对**净值峰值**，不是相对本金、也不是单笔单。 |
| 急停 | kill switch | 全局禁止新订单，必须写原因。回撤 −12% 自动打开；−8% 先告警。 |
| `name_cap` / `gross_limit` | 仓位拒绝 | 单票超上限（股 10% / ETF 20%）或总仓超 95%。 |
| Mock 订单 | 质检演示 | 走同一质量闸门，不代替 Paper 撮合。 |

## 调度与告警

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| 进程内自动 | `ASQT_SYNC_AUTO` | uvicorn 活着时，工作日 16:30 等主源当日 K，18:00 起强制重试。 |
| 进程外 / cron 兜底 | `scripts/crontab.example` | 工作日 20:05 再跑 CLI，防控制台没开。与自动任务错开。 |
| Busy | 同步占用 | `data_sync_lock`：同时只允许一路同步。 |
| `success` / `skipped` / `quality_failed` | 同步结果 | 成功；已是最新；质检未过。当天任一次成功/跳过则进程内不再拉。 |
| `paper-daily` | 日终一轮 | 只给已准入且该日无快照的策略补 T+1；已有快照则 `already_current`。 |
| `paper-run` | 连续回放 | 手工跑 N 个交易日；空账本不会被 cron 自动回放 240 天。 |
| 飞书关键词 | 自定义机器人安全 | 正文须含关键词之一。现设 `ASQT`；发出去带 `【ASQT告警】`。 |
| high / critical / info | 告警级别 | 仅 high/critical 推飞书；打开模拟开关等 info 只写本地 jsonl。 |

## 执行与通道

| 词 | 亦称 | 本仓库含义 |
|---|---|---|
| ExecutionAdapter | 执行端口 | 可替换：现在 Paper；QMT 预留且 `available=false`。 |
| QMT / XtQuant | MiniQMT | 券商端执行；等 Q2 权限，业务层禁止 import `xtquant`。 |
| MCP | Model Context Protocol | 例如 Tushare MCP 点查接口；不等于已写入 ASQT 标准表。 |

---

## 曾单独问过的七个词（速查）

| 词 | 一句话 |
|---|---|
| `estimated_from_preclose` | 涨跌停价用前收×板块幅度估算。 |
| `adj_conflict` | 复权因子跳变且无核实公司行为。 |
| paper | 本地模拟状态 / PaperBroker。 |
| 动量 | 近 20 日强势股 TopK。 |
| 5bp | 0.05% 模拟滑点。 |
| Tick / Level2 | 逐笔与十档，一期不做。 |
| 滑点 | 成交价相对次日开盘的不利偏差。 |
