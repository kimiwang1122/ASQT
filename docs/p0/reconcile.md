# 跨源日 K 鉴定

完整公司行为主数据放到后续阶段收录；本任务不把静默分红/小转增写入 `corporate_actions.csv`。

P1 用第二行情源核对**已落盘日 K**，并扫描未达 1.5 倍闸门的因子跳变是否与未复权价方向一致。

## 命令

全量鉴定（POC 池，与当前 parquet 区间对齐）：

```bash
.venv/bin/asqt reconcile --universe --start 2023-01-01 --end 2026-09-03 --peer auto
```

`--peer auto`：parquet 里来源是 baostock 的标的用 AkShare 核对；来源是 akshare 的用 BaoStock 核对（只比较两边都有的日期）。有 Tushare token 时可用独立第三源：

```bash
.venv/bin/asqt reconcile --universe --lookback-days 14 --peer tushare
```

Token 只放环境变量 `TUSHARE_TOKEN` 或 `data/.tushare_token`，不要写入仓库。5000 分档适配器默认间隔 0.2 秒（约 300 次/分钟）。

全历史第三源（POC 池，与 parquet 对齐）：

```bash
.venv/bin/asqt reconcile --universe --start 2023-01-03 --end 2026-09-07 --peer tushare
```

滚动窗口（定时用）：

```bash
.venv/bin/asqt reconcile --universe --lookback-days 14 --peer auto
```

报告：`data/logs/reconcile_*.json`；差异写入 `quality_issue.dataset=market_daily_reconcile`（`warn`，不改 `check-quality` 的交易阻断）。

复权因子：对照源与主源常有恒定基准差。对账时按标的用 `median(stored/peer)` 对齐后再比；对齐后落入阈值的不记差异，报告里记 `adj_baselines`（因子基准已对齐）。收盘价仍按未复权直接比。不改写 parquet。

## cron 示例

日 K 追加 + 质检（交易日 16:30 进程内；20:05 cron 兜底）：

```cron
5 20 * * 1-5 /path/to/ASQT/scripts/asqt-cron-fallback.sh >> /path/to/ASQT/data/logs/cron-fallback.log 2>&1
```

跨源对账（交易日 **19:15**，与同步/20:05 错开；进程内 `ASQT_RECONCILE_AUTO=1` 也会跑；`auto` peer 优先 Tushare）：

```cron
15 19 * * 1-5 /path/to/ASQT/.venv/bin/asqt reconcile --universe --lookback-days 14 --peer auto >> /path/to/ASQT/data/logs/reconcile.cron.log 2>&1
```

超时：`ASQT_RECONCILE_TIMEOUT_S`（整任务，默认 900）与 `ASQT_RECONCILE_PEER_TIMEOUT_S`（单 peer 拉取，默认 600）；超时记失败任务并飞书「跨源对账失败」。
