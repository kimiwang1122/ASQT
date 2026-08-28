# ASQT

A-share quantitative trading system baseline.

This repository currently provides the pre-P0 technical base:

- Python backend with FastAPI
- SQLite for metadata, state, audit, order, ledger, and task records
- Parquet under `standard_data` for time-series market data
- Runtime layout: `raw_data`, `standard_data`, `qlib_data`, `experiment`, `logs`
- Adapter / Service protocol boundaries in `asqt/ports.py`
- Static frontend console with overview / data / placeholder pages / settings
- Contract-field and API smoke acceptance tests

It does not implement trading strategy rules or wired adapters yet.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/asqt init-db
.venv/bin/asqt seed-demo
.venv/bin/uvicorn asqt.api:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## Acceptance

```bash
.venv/bin/pytest
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/status
curl -s http://127.0.0.1:8000/api/layout
curl -s http://127.0.0.1:8000/api/ports
curl -s 'http://127.0.0.1:8000/api/market/daily?symbol=510300.SH'
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
