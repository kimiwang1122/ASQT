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

## cron 示例

日 K 追加 + 质检 + 滚动对账（交易日 16:30）：

```cron
30 16 * * 1-5 cd /Users/kimi/Documents/ChatGPT/ASQT && .venv/bin/asqt sync-daily >> data/logs/sync-daily.cron.log 2>&1
```

只追加行情（已有 parquet，从最大交易日重叠 1 天拉到今天）：

```bash
.venv/bin/asqt pull-daily --universe --append
```

跨源鉴定（每周日 02:00）：

```cron
0 2 * * 0 cd /Users/kimi/Documents/ChatGPT/ASQT && .venv/bin/asqt reconcile --universe --lookback-days 14 --peer auto >> data/logs/reconcile.cron.log 2>&1
```

机器上的路径按部署目录修改。P3 调度器接入前，用系统 cron 即可。`sync-daily` 在本地还没有日 K 时会跳过，需先跑一次带 `--start/--end` 的历史 `pull-daily`。
