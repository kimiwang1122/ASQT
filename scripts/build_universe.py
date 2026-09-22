#!/usr/bin/env python3
"""Expand POC universe CSVs toward policy caps (≤300 stocks, ≤200 ETFs).

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

STOCK_TARGET = 300
ETF_TARGET = 200
CHINEXT_STAR_MAX_SHARE = 0.40
# 中航成飞 002013→302132 换码，BaoStock 复权因子约 6 倍且无对应送转，入池会把质量闸门打成 block。
STOCK_EXCLUDE = {"302132.SZ"}
ETF_EXCLUDE = {"510230.SH", "512930.SH"}  # adj_factor 跳变无核实送转，入池会 block 闸门
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
    if code6.startswith(("300", "301", "302")):
        return f"{code6}.SZ", "SZ", "chinext"
    if code6.startswith(("000", "001", "002", "003")):
        return f"{code6}.SZ", "SZ", "main"
    raise ValueError(f"unsupported code {code6}")


def _is_st(name: str) -> bool:
    return bool(re.search(r"ST|退", name, re.I))


def _fetch_csindex(symbol: str) -> list[tuple[str, str]]:
    errors: list[str] = []
    try:
        return _fetch_tushare_index(symbol)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"tushare {symbol}: {exc}")
    try:
        return _fetch_akshare_index(symbol)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"akshare {symbol}: {exc}")
    raise RuntimeError("; ".join(errors))


def _fetch_akshare_index(symbol: str) -> list[tuple[str, str]]:
    import akshare as ak

    df = ak.index_stock_cons_csindex(symbol=symbol)
    out: list[tuple[str, str]] = []
    for _, row in df.iterrows():
        code = str(row["成分券代码"]).zfill(6)
        name = str(row["成分券名称"]).strip()
        out.append((code, name))
    return out


def _fetch_tushare_index(symbol: str) -> list[tuple[str, str]]:
    from asqt.adapters.tushare_source import TushareAdapter

    adapter = TushareAdapter()
    ts_code = f"{symbol}.SH"
    weights = adapter._query(
        "index_weight",
        {"index_code": ts_code, "start_date": "20260801", "end_date": "20260831"},
        "index_code,con_code,trade_date,weight",
    )
    if not weights:
        raise RuntimeError(f"empty index_weight for {ts_code}")
    basics = adapter._query("stock_basic", {"list_status": "L"}, "ts_code,name")
    names = {str(row.get("ts_code")): str(row.get("name") or "").strip() for row in basics}
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for row in sorted(weights, key=lambda item: -float(item.get("weight") or 0)):
        con = str(row.get("con_code") or "")
        if not con or con in seen:
            continue
        seen.add(con)
        name = names.get(con, "")
        if not name:
            continue
        out.append((con.split(".")[0], name))
    if not out:
        raise RuntimeError(f"no named constituents for {ts_code}")
    return out


def expand_stocks(existing: list[dict[str, str]], asof: str) -> list[dict[str, str]]:
    have = {row["symbol"] for row in existing if row["symbol"] not in STOCK_EXCLUDE}
    rows = [row for row in existing if row["symbol"] not in STOCK_EXCLUDE]
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
            if symbol in have or symbol in STOCK_EXCLUDE:
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


_ETF_SKIP = re.compile(
    r"货币|债券|国债|城投|可转债|短融|同业存单|信用债|中债|公司债|地方债|地债|政金债|"
    r"黄金|原油|商品|豆粕|期货|"
    r"REIT|REITs|港股|恒生|纳斯达克|标普|日经|德国|亚太|全球|跨境|美元|"
    r"杠杆|反向|双向|中概|美股|沙特|法国|韩国|印度|越南|巴西|MSCI|FOF"
)


def _keep_etf_row(row: dict[str, str]) -> bool:
    symbol = row.get("symbol") or ""
    if symbol in ETF_EXCLUDE or symbol.startswith("511"):
        return False
    blob = f"{row.get('name','')} {row.get('index_name','')}"
    return _ETF_SKIP.search(blob) is None


_ETF_BROAD = frozenset(
    {
        "沪深300",
        "中证500",
        "中证800",
        "中证1000",
        "中证2000",
        "中证A50",
        "中证A100",
        "中证A500",
        "上证50",
        "上证180",
        "上证综指",
        "上证指数",
        "深证100",
        "深证成指",
        "创业板指",
        "创业板50",
        "科创50",
        "科创100",
        "科创成长",
        "国证2000",
        "双创50",
        "上证380",
        "中证全A",
        "上证红利",
        "中证红利",
        "红利低波",
    }
)


def _etf_board_pool(index_name: str) -> tuple[str, str]:
    if index_name in _ETF_BROAD:
        return "broad_index", "etf_broad"
    return "sector", "etf_sector_fallback"


def _fetch_tushare_etfs() -> list[dict[str, str]]:
    from asqt.adapters.tushare_source import TushareAdapter
    from asqt.symbols import infer_instrument_type

    adapter = TushareAdapter()
    fields = "ts_code,csname,extname,index_name,setup_date,list_date,list_status,exchange,etf_type"
    raw: list[dict] = []
    for exchange in ("SH", "SZ"):
        raw.extend(adapter._query("etf_basic", {"list_status": "L", "exchange": exchange}, fields))
    best: dict[str, dict[str, str]] = {}
    for row in raw:
        if str(row.get("etf_type") or "") != "纯境内":
            continue
        symbol = str(row.get("ts_code") or "").strip()
        if symbol.startswith("511"):
            continue
        try:
            if infer_instrument_type(symbol) != "etf":
                continue
        except ValueError:
            continue
        index_name = str(row.get("index_name") or "").strip()
        name = str(row.get("csname") or row.get("extname") or "").strip()
        blob = " ".join(str(row.get(key) or "") for key in ("csname", "extname", "index_name"))
        if not symbol or not index_name or not name or _ETF_SKIP.search(blob):
            continue
        list_date = str(row.get("list_date") or "99999999")
        prev = best.get(index_name)
        if prev is None or list_date < prev["_list"]:
            exchange = "SH" if symbol.endswith(".SH") else "SZ"
            board, pool = _etf_board_pool(index_name)
            best[index_name] = {
                "symbol": symbol,
                "name": name,
                "instrument_type": "etf",
                "exchange": exchange,
                "board": board,
                "pool": pool,
                "index_name": index_name,
                "reason": "wide_lab" if board == "broad_index" else "sector_lab",
                "_list": list_date,
            }
    ranked = sorted(best.values(), key=lambda item: item["_list"])
    for item in ranked:
        item.pop("_list", None)
    return ranked


def expand_etfs(existing: list[dict[str, str]], asof: str) -> list[dict[str, str]]:
    rows = [row for row in existing if _keep_etf_row(row)]
    have_sym = {row["symbol"] for row in rows}
    have_idx = {row["index_name"] for row in rows}
    asof_date = asof or (existing[0]["asof_date"] if existing else "")

    extras = list(EXTRA_ETFS)
    try:
        extras = _fetch_tushare_etfs() + extras
    except Exception as exc:  # noqa: BLE001
        print(f"tushare etf_basic: {exc}")

    for item in extras:
        if len(rows) >= ETF_TARGET:
            break
        idx = item["index_name"]
        if idx in have_idx or item["symbol"] in have_sym or item["symbol"] in ETF_EXCLUDE:
            continue
        if item["symbol"].startswith("511"):
            continue
        rows.append(
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "instrument_type": "etf",
                "exchange": item.get("exchange") or ("SH" if item["symbol"].endswith(".SH") else "SZ"),
                "board": item["board"],
                "pool": item["pool"],
                "index_name": idx,
                "reason": item.get("reason") or ("wide_lab" if item["board"] == "broad_index" else "sector_lab"),
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
