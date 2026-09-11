# ASQT 实施与验收进度

状态：**现行跟踪件**（代码完成度以本文件为准）  
修订：2026-09-11  
阶段定义： [p0/priority.md](p0/priority.md)  
冻结口径： [p0/README.md](p0/README.md)  
未决问题： [p0/open_questions.md](p0/open_questions.md)  
细节台账： [console_fixes.md](console_fixes.md)  
词汇表： [glossary.md](glossary.md)

改阶段结论时先改本文件（状态、未完成理由、验收证据），再改代码或其它文档。

## 状态约定

| 状态 | 含义 |
|---|---|
| 完成 | 本阶段交付已落地，且有可复现验收 |
| 部分完成 | 主路径可用，但验收项或接线未齐 |
| 未开始 | 尚未做 |
| 暂缓 | 有明确理由，不挡当前阶段 |

## 总览

| 阶段 | 目标 | 状态 | 说明 |
|---|---|---|---|
| Pre-P0 | 工程基座 | 完成 | FastAPI / SQLite / Parquet / 契约表 / ports / 控制台壳 |
| P0 | 方案冻结（不写业务代码） | 完成 | 2026-09-03 确认；Q3 于 2026-09-07 关闭 |
| P1 | 数据中心 + 质量闸门 | 完成 | 日 K、标准化、质检、对账、mock 拒单已验收；模拟撮合属 P3 |
| P2 | 研究回测 + 策略版本 | 完成 | 两策略引擎、策略页、回测归因已验收；模拟偏差随 P3 成交 |
| P3 | 模拟交易 + 运营 | 完成 | PaperBroker、账本、20 日模拟、急停、本地+文件告警、生命周期准入 |
| P4 | 实接券商通道 | 暂缓 | Q2 未具备；预留 `QmtExecutionAdapter` 恒为不可用，见 [p4/README.md](p4/README.md) |

当前可对外说的进度：**P1 完成，P2 回测可复现，P3 本地模拟盘可连续运行（未接券商）。**

---

## Pre-P0 工程基座

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| B1 | FastAPI + SQLite + Parquet 运行时 | 完成 | `pytest`；`GET /api/health` | — |
| B2 | 契约表与 `ports.py` | 完成 | `tests/test_baseline.py` | — |
| B3 | 控制台壳（总览/数据/空态/设置） | 完成 | 浏览器打开 `http://127.0.0.1:8000` | 交易页仍是 mock；完整订单属 P3 |

---

## P0 方案冻结

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| F1 | 范围、契约、订单状态机、风控默认、适配器边界 | 完成 | [p0/README.md](p0/README.md) 全表已确认 | — |
| F2 | 未决问题登记 | 完成 | [p0/open_questions.md](p0/open_questions.md) | Q1/Q2 仍暂缓；Q4 已关闭为飞书 |

---

## P1 数据与质量

验收入口：`tests/test_p1_data.py`、`tests/test_p1_universe.py`、`asqt pull-daily` / `check-quality` / `reconcile`。

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| D1 | POC 宇宙 CSV → `instrument_master` | 完成 | `universe-load`；56 股 + 6 ETF | Q6：固定名单，不是历史成分时点池 |
| D2 | BaoStock 主源日 K 适配器 | 完成 | `pull-daily --source baostock` | — |
| D3 | AkShare 备源适配器 | 完成 | `asqt/adapters/akshare_source.py` | 对账用，不作交易主源 |
| D3b | Tushare 第三源 | 完成 | `asqt/adapters/tushare_source.py`；`--peer tushare`；5000 分档节流 0.2s | 不作默认主源 |
| D4 | raw JSON → StandardNormalizer → Parquet | 完成 | `data/standard_data/market_daily.parquet` | — |
| D5 | QualityChecker 最小规则 | 完成 | `check-quality`；`block` 时 `trade_allowed=false` | 规则覆盖缺数/OHLC/复权跳变/时点；非完整公司行为主数据 |
| D6 | 质量失败阻断**新订单** | 完成 | `POST /api/orders/mock`；开放 `block` → `rejected` | PaperBroker 撮合属 P3，不挡本项 |
| D7 | 交易日历 / 停牌 / 涨跌停 | 完成 | 随 `pull-daily` 写入；回测停牌不进新权重 | P1 口径见下节，不做独立全市场日更产品 |
| D8 | 已核实公司行为 CSV | 完成 | [p0/corporate_actions.md](p0/corporate_actions.md) | 只抑制 `adj_conflict`，不改 OHLC；完整事件主数据不做 |
| D9 | 跨源 reconcile | 完成 | `reconcile --universe --peer tushare` 全历史 | 收盘价对齐；因子基准不同只写 `warn`，不翻转闸门 |
| D10 | 控制台行情不全量加载 | 完成 | `/api/market/daily` 默认 limit | — |
| D11 | 质量问题分页列表 | 完成 | `/api/quality/issues`；代码/市场拆列；检查类型中文；序号 | 见 [console_fixes.md](console_fixes.md) C3/C5/C6/C8 |

已知数据口径：POC 约 55,304 根日 K（2023-01-03–2026-09-07）；2026-09-07 四只 ETF 的 BaoStock 占位 `adj_factor=1.0` 已按前日因子补回；`trade_allowed` 现为 true。

### D7 在做什么（避免再读成「没做完」）

日历、停牌、涨跌停**已经有表、已经随日 K 写入、研究闸门会用**。先前写「部分完成」不是没数据，而是还想过一种**更重的做法**，P1 明确不做：

| | P1 已落地（本项按此验收） | P1 不做（以后若要另开项） |
|---|---|---|
| 交易日历 | 每次 `pull-daily` 向主源要该窗口的开市日，写入 `trade_calendar`；质检用它查「开市日有没有 K」 | 不另起一个每天全市场官方日历任务（上交所/深交所全表独立日更） |
| 停牌 | 日 K 上的交易状态写入 `limit_suspension.is_suspended`；回测当天停牌不进新权重 | 不另拉交易所停牌专表覆盖全部 A 股 |
| 涨跌停价 | 用前收 × 板块幅度估算（主板约 10%，创业/科创约 20%），`reason=estimated_from_preclose` | 不另拉交易所公布的当日涨跌停价 |

够研究和质量闸门；不是交易所官方涨跌停/停牌主数据。

---

---

## P2 研究回测

验收入口：[p2/README.md](p2/README.md)、`tests/test_p2_research.py`、`asqt research-backtest --strategy all`。

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| R1 | `etf_ma_rotate`（规则，ETF 20 日均线） | 完成 | 回测报告 + 实验 JSON | — |
| R2 | `stock_momentum_topk`（TopK=5，20 日动量） | 完成 | 同上 | — |
| R2b | `etf_momentum_topk`（TopK=3，40 日动量） | 完成 | 第三套规则策略；新 `parameter_set_id` | 已 paper 参数组不可改 |
| R3 | 同策略 + 同 `data_version` 可复现 | 完成 | P2 测试 | — |
| R4 | IS/OOS 时间切开，无未来函数 | 完成 | `asof` 只看 `trade_date <= asof` | — |
| R5 | 质量 `block` → 策略 `failed` | 完成 | P2 测试 | — |
| R6 | 仅 `paper` 可写可下单目标仓 | 完成 | `LocalStrategyService.generate_target_positions`；P3 消费目标仓 | — |
| R7 | 控制台策略 / 实验页 | 完成 | `#strategy` 列出版本与 latest 实验；重跑回测异步 + 进度 | — |
| R8 | 收益归因 / 回测 vs 模拟偏差 | 完成 | `#review`；IS/OOS 天数与占比、OOS Top/拖累、参数与样本区间、Paper 对比表 | — |
| R9 | Qlib bin / 业务层 qlib | 暂缓 | 目录 `data/qlib_data/` 预留 | 本期用 `LocalResearchEngine`，禁止业务层 import qlib |

---

## P3 模拟交易与运营

验收入口：[p3/README.md](p3/README.md)、`tests/test_p3_paper.py`、`asqt paper-admit` / `paper-run --days 20`。

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| T1 | `OrderService`：目标仓 → 标准订单 + 风控 | 完成 | `PaperOrderService.build_orders`；差额、幂等、仓位/停牌/涨跌停/手数 | — |
| T2 | PaperBroker 模拟撮合与账本 | 完成 | 次日开盘+5bp；佣金/印花税/过户费；`execution_fill` + `account_snapshot` | — |
| T3 | 20 个交易日连续模拟运行 | 完成 | `paper-run --days 20`；快照天数达标 | 控制台跑模拟改为后台任务 + 进度；急停导致未满窗会回中文 `detail` |
| T4 | 急停 / kill switch 可操作 | 完成 | `POST /api/ops/kill-switch` 必须写原因；回撤 −12% 自动急停 | — |
| T5 | 调度（CLI/cron → 任务表） | 完成 | `LocalScheduler`；同步成功后幂等 `paper-daily`；工作日 20:05 cron 兜底 | 仍为进程内 + cron，无 Redis；同步页提示 cron 是否安装 / 热加载收尸 |
| T6 | 告警通道（本地 + 一种远程） | 完成 | `alert` 表 + `alerts.jsonl` + 飞书 webhook；投递元数据写入 `alerts_remote.jsonl` | 仅 `high`/`critical` 推飞书；`info` 只落本地 |
| T7 | 质检 `block` 禁止新订单 | 完成 | mock 与 Paper 路径均拒绝 | — |

---

## P4 及更后

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| X1 | QMT / XtQuant 执行适配 | 暂缓 | [p4/README.md](p4/README.md)；`tests/test_p4_qmt_stub.py` | Q2：券商模拟盘权限未具备；预留适配器 `available=false` |
| X2 | 付费数据源 | 暂缓 | — | Q1：见 [p0/data_budget.md](p0/data_budget.md) |
| X3 | 分钟 K / 财务 / 两融 / 北向 | 暂缓 | — | 策略验证后再申请，非 P1 必做 |
| X4 | Tick / Level2 / 期货 / 港美股 / 北交所 | 暂缓 | — | 一期范围排除，见 [p0/scope.md](p0/scope.md) |

---

## 控制台（跨阶段）

目标在 [p0/priority.md](p0/priority.md) 排 **P3–P4**，壳在 Pre-P0。

| ID | 项 | 状态 | 验收 | 未完成理由 |
|---|---|---|---|---|
| U1 | 总览行情 Top50 + 筛选 | 完成 | 下拉/折叠/模糊搜索/量能排序/序号/同比环比说明 | — |
| U2 | 质量问题分页 | 完成 | 筛选/排序/中文枚举/拆市场/序号/行悬停 | 细节追加走 [console_fixes.md](console_fixes.md) |
| U5 | 数据同步页 | 完成 | 追加行情按钮、toast、`#sync` 记录 | 状态列显示进行中百分比；热加载会中断后台任务并收尸 |
| U3 | 策略 / 交易 / 复盘页 | 完成 | 策略生命周期；交易页账户/订单/急停；复盘含模拟偏差 | — |
| U4 | 端口边界显示真实接线 | 完成 | `/api/ports` 按 WIRED_PORTS 显示；Execution/Alert 已接线 | — |

---

## 下次开工建议

1. **P4 实接**：等 Q2（MiniQMT 权限）再按 [p4/README.md](p4/README.md)「Q2 具备后才开的验收」接线；禁止把预留适配器标成完成。Qlib bin（R9）同理：目录预留，业务层零 `import qlib`。  
2. **日终闭环**：交易日同步成功后会自动 `paper-daily`；空账本不会自动回放 240 日，需先手工「跑模拟」（现为后台任务，可看进度）。进程外兜底见 `scripts/crontab.example`（20:05）；同步页会提示当前用户 crontab 是否已装。  
3. **第三套策略准入**：`etf_momentum_topk` 需 `research-backtest` → 生命周期到 paper → 单独「跑模拟」。勿改已 paper 的参数组。  
4. **Q1**：付费数据源仍暂缓。

修订：2026-09-11
