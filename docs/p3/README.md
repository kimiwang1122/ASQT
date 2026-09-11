# P3 模拟交易与运营

状态：**代码已落地；以 pytest 为准**  
修订：2026-09-09  
整体进度：[../progress.md](../progress.md)

本阶段交付 PaperBroker、账本、生命周期准入、急停、本地告警、连续模拟，以及回测 vs 模拟偏差。不接 QMT，不做策略 CRUD。

## 验收

```bash
.venv/bin/pytest tests/test_p3_paper.py tests/test_mock_orders.py tests/test_p2_research.py tests/test_baseline.py tests/test_p1_data.py
.venv/bin/asqt paper-admit --strategy all --reason "p3 admit"
.venv/bin/asqt paper-run --strategy all --days 20
.venv/bin/asqt paper-daily
.venv/bin/asqt paper-reset --strategy all
```

必须同时成立：

1. `candidate` 可准入 `paper`；必须能指出数据版本、参数组、实验、风控配置；`draft` / `backtest` / `candidate` 仍不能下单
2. `paper` 状态禁止重跑回测改写版本；参数组禁止原地修改（变更只能退役后新版本，本期不提供改参入口）
3. `OrderService.build_orders` 按目标仓与持仓差额下单；`idem_key` = 策略 + 交易日 + 标的 + 方向，重复不生成第二张有效单
4. 质量 `block`、急停、停牌、涨停买/跌停卖、非 100 整数倍、超单票/总仓、现金不足 → `rejected`，Paper 路径与 mock 闸门一致
5. PaperBroker 以次日开盘价撮合，滑点 5bp；佣金万分之 2.5（最低 5 元）、卖出印花税 0.05%、沪市过户费；成交写入 `execution_fill`，日终 `account_snapshot`
6. T+1：当日买入不可当日卖出
7. `paper-run --days 20` 连续 20 个交易日有快照；`task_run` 留下 `paper-run`
8. 急停可开可关，必须写原因；回撤 −12% 自动急停；恢复必须写原因
9. 告警写入 `alert` 表；本地 `logs/alerts.jsonl`；远程飞书自定义机器人（`high`/`critical`）；投递结果写入 `alerts_remote.jsonl`。可用 `ASQT_FEISHU_WEBHOOK` 覆盖 webhook，空字符串关闭推送。
10. 有模拟快照后 `paper_vs_backtest.available=true`，给出同窗口回测收益与最大净值偏离
11. `ExecutionAdapter` / `AlertService` 端口为 `wired`；控制台交易页能看账户、订单、成交
12. 交易页日表/持仓/成交/模拟订单/Mock 订单均分页，每页 10 条；财务对账按成交回推现金与持仓数量，与账本比对（容差 0.05 元）；费用认成交当时 `fee`（当时佣金 + 代码印花税/过户费），不用设置页现值重算
13. 日 K 同步 `success` / `skipped` 后触发幂等 `paper-daily`：仅对已准入且当日无快照的策略补一轮 T+1；开关关 / 急停 / 质检阻断 / 未准入 → `skipped` 并写 `task_run`
14. `LocalScheduler` 可 `list_tasks` / `run_task(paper-daily|sync-daily)`；CLI `asqt paper-daily`；`POST /api/paper/daily`

```bash
.venv/bin/pytest tests/test_p3_paper.py tests/test_p3_scheduler.py tests/test_p4_qmt_stub.py
.venv/bin/asqt paper-daily
```

## 口径

- 账户本金默认 1,000,000，可在设置页改；账户 id `paper:{strategy_id}`
- 佣金默认万分之 2.5（最低 5 元），可在设置页改；卖出另计印花税 0.05%、沪市过户费
- 信号日收盘定目标仓，下一交易日开盘撮合，收盘计价
- 股票单票 ≤10%，ETF ≤20%，总仓 ≤95%；止盈 +20% / 止损 −8% 相对开仓成本
