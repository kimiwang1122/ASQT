#!/usr/bin/env python3
"""Expand POC universe CSVs toward policy caps (≤100 stocks, ≤50 ETFs).

Uses AkShare CSI index constituents. Liquidity hard filters that need daily bars
are deferred to post-pull quality; this script prefers HS300 → CSI500 order and
keeps existing rows.

Usage:
  arch -arm64 .venv/bin/python scripts/build_universe.py
  arch -arm64 .venv/bin/python scripts/build_universe.py --apply
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOCK_PATH = ROOT / "docs" / "p0" / "universe_stock.csv"
ETF_PATH = ROOT / "docs" / "p0" / "universe_etf.csv"

STOCK_TARGET = 100
ETF_TARGET = 50
CHINEXT_STAR_MAX_SHARE = 0.40
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

# Lab extras (unique index_name). CSV is authoritative; this list backfills dry-runs.
EXTRA_ETFS = [
    {"symbol": "159901.SZ", "name": "深证100ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "深证100", "reason": "深市大盘宽基"},
    {"symbol": "510180.SH", "name": "上证180ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "上证180", "reason": "沪市大盘宽基"},
    {"symbol": "159949.SZ", "name": "华安创业板50ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "创业板50", "reason": "创业成长宽基补足"},
    {"symbol": "563300.SH", "name": "华泰柏瑞中证A500ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "中证A500", "reason": "A500宽基"},
    {"symbol": "510210.SH", "name": "上证综指ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "上证综指", "reason": "沪市综合宽基"},
    {"symbol": "159628.SZ", "name": "国证2000ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "国证2000", "reason": "小微盘宽基"},
    {"symbol": "563000.SH", "name": "中证2000ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "中证2000", "reason": "小微盘宽基补足"},
    {"symbol": "510880.SH", "name": "华泰柏瑞红利ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "上证红利", "reason": "红利宽基"},
    {"symbol": "515180.SH", "name": "易方达中证红利ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "中证红利", "reason": "红利宽基补足"},
    {"symbol": "512890.SH", "name": "红利低波ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "红利低波", "reason": "红利低波风格"},
    {"symbol": "588050.SH", "name": "科创成长ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "科创成长", "reason": "科创成长风格"},
    {"symbol": "159682.SZ", "name": "双创ETF", "board": "broad_index", "pool": "etf_broad", "index_name": "双创50", "reason": "双创宽基"},
    {"symbol": "512690.SH", "name": "酒ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证白酒", "reason": "sector_lab"},
    {"symbol": "512480.SH", "name": "半导体ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证全指半导体", "reason": "sector_lab"},
    {"symbol": "159995.SZ", "name": "芯片ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "国证芯片", "reason": "sector_lab"},
    {"symbol": "512660.SH", "name": "军工ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证军工", "reason": "sector_lab"},
    {"symbol": "512800.SH", "name": "银行ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证银行", "reason": "sector_lab"},
    {"symbol": "512000.SH", "name": "券商ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "证券公司", "reason": "sector_lab"},
    {"symbol": "512880.SH", "name": "证券ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证全指证券公司", "reason": "sector_lab"},
    {"symbol": "515790.SH", "name": "光伏ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证光伏产业", "reason": "sector_lab"},
    {"symbol": "159869.SZ", "name": "新能源车ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "新能源车", "reason": "sector_lab"},
    {"symbol": "512010.SH", "name": "医药ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "沪深300医药", "reason": "sector_lab"},
    {"symbol": "159992.SZ", "name": "创新药ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证创新药", "reason": "sector_lab"},
    {"symbol": "512170.SH", "name": "医疗ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证医疗", "reason": "sector_lab"},
    {"symbol": "159928.SZ", "name": "消费ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证主要消费", "reason": "sector_lab"},
    {"symbol": "159996.SZ", "name": "家电ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证全指家电", "reason": "sector_lab"},
    {"symbol": "512400.SH", "name": "有色ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证有色金属", "reason": "sector_lab"},
    {"symbol": "515220.SH", "name": "煤炭ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证煤炭", "reason": "sector_lab"},
    {"symbol": "159825.SZ", "name": "农业ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证农业主题", "reason": "sector_lab"},
    {"symbol": "512200.SH", "name": "房地产ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证全指房地产", "reason": "sector_lab"},
    {"symbol": "515050.SH", "name": "5GETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "5G通信", "reason": "sector_lab"},
    {"symbol": "515980.SH", "name": "人工智能ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "人工智能主题", "reason": "sector_lab"},
    {"symbol": "159819.SZ", "name": "人工智能ETF南方", "board": "sector", "pool": "etf_sector_fallback", "index_name": "CS人工智能", "reason": "sector_lab"},
    {"symbol": "512980.SH", "name": "传媒ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证传媒", "reason": "sector_lab"},
    {"symbol": "512580.SH", "name": "环保ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证环保", "reason": "sector_lab"},
    {"symbol": "516160.SH", "name": "新能源ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证新能源", "reason": "sector_lab"},
    {"symbol": "515700.SH", "name": "新能车ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证新能源汽车", "reason": "sector_lab"},
    {"symbol": "159736.SZ", "name": "食品饮料ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "食品饮料", "reason": "sector_lab"},
    {"symbol": "159766.SZ", "name": "旅游ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证旅游主题", "reason": "sector_lab"},
    {"symbol": "512960.SH", "name": "央企改革ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "央企改革", "reason": "sector_lab"},
    {"symbol": "512760.SH", "name": "芯片易方达ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中华半导体芯片", "reason": "sector_lab"},
    {"symbol": "515000.SH", "name": "科技ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "科技龙头", "reason": "sector_lab"},
    {"symbol": "512670.SH", "name": "国防ETF", "board": "sector", "pool": "etf_sector_fallback", "index_name": "中证国防", "reason": "sector_lab"},
    {"symbol": "159841.SZ", "name": "证券ETF深市", "board": "sector", "pool": "etf_sector_fallback", "index_name": "证券公司深市", "reason": "sector_lab"},
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [{k: (row.get(k) or "").strip() for k in COLUMNS} for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in COLUMNS})


def _exchange_board(code6: str) -> tuple[str, str, str]:
    """Return symbol, exchange, board from 6-digit code."""
    if code6.startswith("6"):
        return f"{code6}.SH", "SH", "main" if not code6.startswith("688") else "star"
    if code6.startswith("688"):
        return f"{code6}.SH", "SH", "star"
    if code6.startswith("300") or code6.startswith("301"):
        return f"{code6}.SZ", "SZ", "chinext"
    if code6.startswith(("000", "001", "002", "003")):
        return f"{code6}.SZ", "SZ", "main"
    raise ValueError(f"unsupported code {code6}")


def _is_st(name: str) -> bool:
    return bool(re.search(r"ST|退", name, re.I))


def _fetch_csindex(symbol: str) -> list[tuple[str, str]]:
    import akshare as ak

    df = ak.index_stock_cons_csindex(symbol=symbol)
    code_col = "成分券代码"
    name_col = "成分券名称"
    out: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        code = str(row[code_col]).zfill(6)
        name = str(row[name_col]).strip()
        out.append((code, name))
    return out


def expand_stocks(existing: list[dict[str, str]], asof: str) -> list[dict[str, str]]:
    have = {row["symbol"] for row in existing}
    rows = list(existing)
    asof_date = asof or (existing[0]["asof_date"] if existing else "")

    sources = [
        ("000300", "hs300", "沪深300"),
        ("000905", "csi500", "中证500"),
        ("000906", "csi800_fill", "中证800"),
    ]
    for index_code, pool, index_name in sources:
        if len(rows) >= STOCK_TARGET:
            break
        try:
            members = _fetch_csindex(index_code)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {index_code}: {exc}")
            continue
        for code6, name in members:
            if len(rows) >= STOCK_TARGET:
                break
            if _is_st(name):
                continue
            try:
                symbol, exchange, board = _exchange_board(code6)
            except ValueError:
                continue
            if symbol in have:
                continue
            chinext_star = sum(1 for r in rows if r["board"] in {"chinext", "star"})
            if board in {"chinext", "star"} and (chinext_star + 1) / (len(rows) + 1) > CHINEXT_STAR_MAX_SHARE:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "instrument_type": "stock",
                    "exchange": exchange,
                    "board": board,
                    "pool": pool,
                    "index_name": index_name,
                    "reason": f"{pool}+指数成分补足;流动性待拉数后质检",
                    "asof_date": asof_date,
                }
            )
            have.add(symbol)
    return rows


def expand_etfs(existing: list[dict[str, str]], asof: str) -> list[dict[str, str]]:
    rows = list(existing)
    have_sym = {row["symbol"] for row in rows}
    have_idx = {row["index_name"] for row in rows}
    asof_date = asof or (existing[0]["asof_date"] if existing else "")
    for item in EXTRA_ETFS:
        if len(rows) >= ETF_TARGET:
            break
        idx = item["index_name"]
        if idx in have_idx:
            continue
        if item["symbol"] in have_sym:
            continue
        if "沪深300" in idx and "沪深300" in have_idx:
            continue
        rows.append(
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "instrument_type": "etf",
                "exchange": "SH" if item["symbol"].endswith(".SH") else "SZ",
                "board": item["board"],
                "pool": item["pool"],
                "index_name": idx,
                "reason": item["reason"],
                "asof_date": asof_date,
            }
        )
        have_sym.add(item["symbol"])
        have_idx.add(idx)
    return rows[:ETF_TARGET]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="overwrite docs/p0 CSVs")
    parser.add_argument("--asof", default="", help="asof_date YYYY-MM-DD")
    args = parser.parse_args()

    stocks = expand_stocks(_read_csv(STOCK_PATH), args.asof)
    etfs = expand_etfs(_read_csv(ETF_PATH), args.asof)
    print(f"stocks {len(stocks)} (cap {STOCK_TARGET}), etfs {len(etfs)} (cap {ETF_TARGET})")
    chinext_star = sum(1 for r in stocks if r["board"] in {"chinext", "star"})
    print(f"chinext+star {chinext_star}/{len(stocks)} = {chinext_star/len(stocks):.1%}")

    if args.apply:
        _write_csv(STOCK_PATH, stocks)
        _write_csv(ETF_PATH, etfs)
        print(f"wrote {STOCK_PATH} and {ETF_PATH}")
    else:
        print("dry-run only; pass --apply to write")


if __name__ == "__main__":
    main()
