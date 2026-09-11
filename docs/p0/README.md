# P0 方案冻结

状态：**已确认**（Kimi.wang / 2026-09-03）  
范围：只冻结边界和契约，不实现拉数、回测、下单。  
P0 → P1：书面冻结已齐；未决项见 [open_questions.md](open_questions.md)，均不挡进入 P1。  
实施与验收进度（完成 / 未完成 / 理由）：[../progress.md](../progress.md)。

| 文件 | 冻结什么 | 确认结论 |
|---|---|---|
| [scope.md](scope.md) | 做什么、不做什么 | 一期仅 A 股股票 + 境内指数型 ETF；不含期货/港美股/Level2/实盘 |
| [priority.md](priority.md) | PRD 功能映射到实施阶段 | 本周不开发策略；数据与质检是 P1 第一批代码 |
| [data_contracts.md](data_contracts.md) | 字段、主键、单位、口径 | 按草案执行 |
| [order_state_machine.md](order_state_machine.md) | 策略生命周期 + 订单状态机 | 按草案执行 |
| [adapters.md](adapters.md) | 可替换边界与依赖禁令 | 厂商 SDK 只允许在 adapters / engine |
| [risk_defaults.md](risk_defaults.md) | 账户/持仓/停机默认值 | 回撤 8%/12%，股票 10%，ETF 20%，总仓 95% |
| [universe_policy.md](universe_policy.md) | POC 标的池原则 | ≥50 股 + ≥5 ETF；名单见 CSV，筛选日 2026-09-03 |
| [data_budget.md](data_budget.md) | 主备数据源与费用 | 主源 baostock、备源 AkShare；付费暂缓 |
| [open_questions.md](open_questions.md) | 未决与暂缓 | Q3/Q4 已关闭；Q1/Q2 暂缓；Q5/Q6 已关闭；Q7 排除北交所 |
| [corporate_actions.md](corporate_actions.md) | 已核实送转除权 | 抑制 adj 误报；不改价格 |
| [reconcile.md](reconcile.md) | 跨源鉴定 | CLI + cron；不替代完整事件主数据 |

讲解图（非正式冻结件）：[../archify/README.md](../archify/README.md)  
口头/聊天用语：[../glossary.md](../glossary.md)

变更规则：改冻结口径必须先改对应文件并更新确认日期，再改代码。
