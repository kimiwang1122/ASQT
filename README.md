# ASQT

A-share quantitative trading system baseline.

This repository currently provides the pre-P0 technical base plus the P1 data foundation:

- Python backend with FastAPI
- SQLite for metadata, state, audit, order, ledger, and task records
- Parquet under `standard_data` for time-series market data
- POC universe CSVs (≥50 stocks + ≥5 ETFs) loaded into `instrument_master`
- BaoStock primary + AkShare backup daily adapters behind `asqt/adapters/`
- QualityChecker minimum rules: missing, OHLC/range, adj-factor jump, point-in-time
- Adapter / Service protocol boundaries in `asqt/ports.py`
- Static frontend console with overview / data / placeholder pages / settings
- Contract-field, API smoke, and P1 data-gate tests

P2 research is wired (`etf_ma_rotate` + `stock_momentum_topk` + `etf_momentum_topk`) behind `LocalResearchEngine`. Execution stays on PaperBroker; QMT stub and Qlib bin remain reserved (`available=false` / no business `import qlib`).

实施与验收进度（完成 / 未完成 / 理由）：[`docs/progress.md`](docs/progress.md)。  
控制台细节修复（去重分类、可追加）：[`docs/console_fixes.md`](docs/console_fixes.md)。  
专业词汇（本仓库口径）：[`docs/glossary.md`](docs/glossary.md)。

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,data]"
.venv/bin/asqt init-db
.venv/bin/asqt seed-demo
.venv/bin/asqt universe-load
.venv/bin/asqt pull-daily --universe --source baostock --start 2023-01-01 --end 2026-09-01
.venv/bin/asqt pull-daily --universe --append
.venv/bin/asqt sync-daily
.venv/bin/asqt check-quality
.venv/bin/asqt reconcile --universe --lookback-days 14
.venv/bin/asqt research-backtest --strategy all
.venv/bin/uvicorn asqt.api:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

A-share close is ~15:00 CST. While the API process is running, weekdays it waits from 16:30 for the primary vendor to publish that day's bars before append+quality; from 18:00 it retries like before until success/skipped. Use the console **追加行情** button for a manual async run, or:

```bash
.venv/bin/asqt sync-daily
```

Disable in-process auto sync with `ASQT_SYNC_AUTO=0`.

High/critical alerts POST to a Feishu custom bot. Override with `ASQT_FEISHU_WEBHOOK`; set empty to disable. Rehearse the full chain without touching the live paper book:

```bash
.venv/bin/asqt alert-demo
.venv/bin/asqt alert-demo --dry-run
```

Process-out fallback (weekdays **20:05** Asia/Shanghai), after in-process 16:30 / 18:00. Same SQLite lock; a daytime success/skipped sync stops further auto retries. Install:

```bash
chmod +x scripts/asqt-cron-fallback.sh
crontab scripts/crontab.example
```
## Acceptance

```bash
.venv/bin/pytest
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/status
curl -s http://127.0.0.1:8000/api/layout
curl -s http://127.0.0.1:8000/api/ports
curl -s http://127.0.0.1:8000/api/quality/issues
curl -s http://127.0.0.1:8000/api/quality/check
```

## Data Layout

By default, runtime files are written to `./data`.

- `data/asqt.sqlite3`: SQLite database
- `data/raw_data/`: external provider raw payloads
- `data/standard_data/market_daily.parquet`: standardized daily bars
- `data/qlib_data/`: reserved for Qlib bin conversion
- `data/experiment/`: reserved for MLflow / review artifacts
- `data/logs/`: reserved for scheduler and service logs

Override with:

```bash
export ASQT_DATA_DIR=/path/to/asqt-data
```

## Baseline Hardening Checklist

1. Contract tables include `trade_calendar`, `limit_suspension`, `factor_signal`
2. `data_source` stores `quota`, `cost`, `owner`
3. Runtime directories match the technical design layout
4. `asqt/ports.py` defines replaceable Adapter / Service protocols
5. Frontend pages show explicit “未接入” empty states plus a settings layout view
6. Tests cover contract columns and API smoke paths
