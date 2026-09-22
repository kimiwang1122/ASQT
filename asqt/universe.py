"""POC universe CSV loader. Lists live in docs/p0, not vendor SDKs."""

from __future__ import annotations

import csv
from pathlib import Path

from asqt.config import Settings, get_settings
from asqt.db import execute, executemany, initialize_database
from asqt.symbols import infer_board, infer_instrument_type
from asqt.tags import sync_universe_tags

COLUMNS = (
    "symbol",
    "name",
    "instrument_type",
    "exchange",
    "board",
    "pool",
    "index_name",
    "reason",
    "asof_date",
)

STOCK_MIN = 50
STOCK_MAX = 300  # lab: fill remaining HS300
ETF_MIN = 5
ETF_MAX = 200  # lab: unique-index equity ETFs
CHINEXT_STAR_MAX_SHARE = 0.40


class UniverseError(ValueError):
    pass


def universe_paths(settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or get_settings()
    root = settings.project_root / "docs" / "p0"
    return root / "universe_stock.csv", root / "universe_etf.csv"


def read_universe_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise UniverseError(f"missing universe file: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise UniverseError(f"{path} missing columns: {missing}")
        rows = []
        for raw in reader:
            row = {key: (raw.get(key) or "").strip() for key in COLUMNS}
            if not row["symbol"]:
                continue
            rows.append(row)
    return rows


def load_poc_universe(settings: Settings | None = None) -> dict[str, list[dict[str, str]]]:
    stock_path, etf_path = universe_paths(settings)
    stocks = read_universe_csv(stock_path)
    etfs = read_universe_csv(etf_path)
    validate_universe(stocks, etfs)
    return {"stocks": stocks, "etfs": etfs}


def poc_symbols(settings: Settings | None = None) -> list[str]:
    payload = load_poc_universe(settings)
    return [row["symbol"] for row in payload["stocks"] + payload["etfs"]]


def validate_universe(
    stocks: list[dict[str, str]],
    etfs: list[dict[str, str]],
    *,
    min_stock: int = STOCK_MIN,
    min_etf: int = ETF_MIN,
) -> None:
    errors: list[str] = []
    if not (min_stock <= len(stocks) <= STOCK_MAX):
        errors.append(f"stock count {len(stocks)} not in [{min_stock}, {STOCK_MAX}]")
    if not (min_etf <= len(etfs) <= ETF_MAX):
        errors.append(f"etf count {len(etfs)} not in [{min_etf}, {ETF_MAX}]")

    symbols = [row["symbol"] for row in stocks + etfs]
    if len(symbols) != len(set(symbols)):
        errors.append("duplicate symbol in universe")

    for row in stocks:
        _check_row(row, expect_type="stock", errors=errors)
        if row["exchange"] not in {"SH", "SZ"}:
            errors.append(f"{row['symbol']} exchange must be SH/SZ")
        if row["board"] == "bse" or row["symbol"].endswith(".BJ"):
            errors.append(f"{row['symbol']} BSE is excluded")
        if row["pool"] not in {"hs300", "csi500", "csi800_fill"}:
            errors.append(f"{row['symbol']} invalid stock pool {row['pool']}")

    chinext_star = sum(1 for row in stocks if row["board"] in {"chinext", "star"})
    if stocks and chinext_star / len(stocks) > CHINEXT_STAR_MAX_SHARE:
        errors.append("chinext+star share exceeds 40%")

    index_seen: dict[str, str] = {}
    for row in etfs:
        _check_row(row, expect_type="etf", errors=errors)
        if row["board"] not in {"broad_index", "sector"}:
            errors.append(f"{row['symbol']} etf board must be broad_index/sector")
        if row["pool"] not in {"etf_broad", "etf_sector_fallback"}:
            errors.append(f"{row['symbol']} invalid etf pool {row['pool']}")
        if row["pool"] == "etf_broad" and row["board"] != "broad_index":
            errors.append(f"{row['symbol']} core etf must be broad_index")
        index_name = row["index_name"]
        if index_name in index_seen:
            errors.append(f"duplicate etf index {index_name}: {index_seen[index_name]} vs {row['symbol']}")
        else:
            index_seen[index_name] = row["symbol"]

    if errors:
        raise UniverseError("; ".join(errors))


def _check_row(row: dict[str, str], *, expect_type: str, errors: list[str]) -> None:
    symbol = row["symbol"]
    if infer_instrument_type(symbol) != expect_type:
        errors.append(f"{symbol} inferred type != {expect_type}")
    if row["instrument_type"] != expect_type:
        errors.append(f"{symbol} instrument_type != {expect_type}")
    # ETF board is policy (broad_index vs sector); infer_board always returns broad_index.
    if expect_type != "etf" and infer_board(symbol) != row["board"]:
        errors.append(f"{symbol} board {row['board']} != inferred {infer_board(symbol)}")
    if not row["name"] or not row["reason"] or not row["asof_date"]:
        errors.append(f"{symbol} missing name/reason/asof_date")
    if len(row["asof_date"]) != 10:
        errors.append(f"{symbol} asof_date must be YYYY-MM-DD")


def apply_universe(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    initialize_database(settings)
    payload = load_poc_universe(settings)
    rows = payload["stocks"] + payload["etfs"]
    execute("DELETE FROM instrument_master", settings=settings)
    executemany(
        """
        INSERT INTO instrument_master
            (symbol, name, instrument_type, exchange, board, list_date, delist_date, status, is_st, updated_at)
        VALUES (?, ?, ?, ?, ?, NULL, NULL, 'listed', 0, CURRENT_TIMESTAMP)
        """,
        [
            (
                row["symbol"],
                row["name"],
                row["instrument_type"],
                row["exchange"],
                row["board"],
            )
            for row in rows
        ],
        settings=settings,
    )
    tag_count = sync_universe_tags(rows, settings=settings)
    return {"stocks": len(payload["stocks"]), "etfs": len(payload["etfs"]), "tags": tag_count}
