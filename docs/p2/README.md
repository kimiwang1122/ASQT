# P2 研究回测

状态：**回测与归因已实现；模拟偏差见 P3**  
修订：2026-09-11  
整体进度：[../progress.md](../progress.md)（本文件只覆盖 P2 回测口径）。

Q3 组合：**规则择时（ETF 均线轮动）+ A 股动量 TopK + ETF 动量 TopK**；P2.3 另增 **股票低波动量**、**ETF 均线动量过滤**、**股票短反转 TopK**；P2.4 另增 **股票动量量能确认**、**股票跳月动量**。引擎是 `LocalResearchEngine`（实现 `ResearchEngine`），不在业务层 import `qlib`。

## 验收

```bash
.venv/bin/pytest tests/test_p2_research.py tests/test_factors_tune.py
.venv/bin/asqt research-backtest --strategy all
.venv/bin/asqt tune --strategy stock_short_reversal_topk
```

控制台：`#strategy` 看版本与实验，`#review` 看按标的贡献。接口：`GET /api/strategies`、`GET /api/research/experiments`、`GET /api/research/attribution`。控制台重跑回测是异步：`POST /api/research/backtest` 立刻返回 `run_id`，再 `GET /api/research/backtest/{run_id}` 看进度。CLI `research-backtest` 仍同步跑完。调参仅 CLI：`asqt tune`（IS 网格 → 固定 OOS 报告），**不自动改**已 paper 的 `parameter_set_id`。

必须同时成立：

1. 八个策略都产出报告：`etf_ma_rotate`、`stock_momentum_topk`、`etf_momentum_topk`、`stock_lowvol_momentum`、`etf_ma_momentum_filter`、`stock_short_reversal_topk`、`stock_momentum_volume_confirm`、`stock_momentum_skip_month`
2. 同一 `data_version` + 参数组再跑，指标与期末权重一致
3. 样本内 / 样本外按时间切开，OOS 日数 ≥ 1；信号日只看 `trade_date <= asof`
4. 质量闸门 `block` 时策略进入 `failed`，不得标 `candidate`
5. `draft` / `backtest` / `candidate` 不能写可下单目标仓；仅 `paper` 可 `generate_target_positions`
6. 回测写 `factor_signal` 与 `data/experiment/`
7. 回测归因按 T+1 权重 × 复权日收益累加到标的；净值与引擎一致；无模拟快照时 `paper_vs_backtest.available=false`；复盘页展示 IS/OOS 天数、占比与 OOS Top/拖累
8. `asqt tune` 写出 `data/experiment/tune_*.json`，含网格与 `suggested_parameter_set_id`；不得改写 paper/paused/retired 参数组

## 口径

- 收益用相邻日 `close * adj_factor`，T+1：T 日收盘信号，T+1 收盘计盈亏
- 股票单票 ≤ 10%，ETF ≤ 20%，总仓 ≤ 95%（[risk_defaults.md](../p0/risk_defaults.md)）
- 停牌标的不进入当日新权重
- 已 paper 的参数组禁止改写；新策略必须新 `parameter_set_id`
- 因子库：[`asqt/factors.py`](../../asqt/factors.py)（动量、均线偏离、波动率、短反转、成交量 z）；策略实现见 [`asqt/strategies.py`](../../asqt/strategies.py)
- 调参：[`asqt/tune.py`](../../asqt/tune.py)；默认网格 ≤ 24 组；IS 按总收益→回撤浅→换手低排序，再报 OOS 指标
