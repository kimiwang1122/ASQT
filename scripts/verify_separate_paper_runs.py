#!/usr/bin/env python3
"""Verify solo paper runs get full portfolio cash; multi-run splits among participants."""

from __future__ import annotations

import json
import sys
from typing import Any

from asqt.config import get_settings
from asqt.db import query_all
from asqt.ops import kill_engaged, paper_account_config, paper_trading_enabled
from asqt.paper import (
    account_id_for,
    paper_admitted_ids,
    paper_board,
    reset_paper_account,
    run_paper_days,
)
from asqt.strategies import STRATEGY_SPECS


def approx(a: Any, b: Any, *, rel: float = 1e-6, abs_tol: float = 0.05) -> bool:
    return abs(float(a) - float(b)) <= max(abs_tol, abs(float(b)) * rel)


def check(cond: bool, msg: str, bag: list[str]) -> bool:
    if not cond:
        bag.append(msg)
    return cond


def main() -> int:
    settings = get_settings()
    cfg = paper_account_config(settings)
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    portfolio = float(cfg["initial_cash"])
    admitted = paper_admitted_ids(settings)
    strategies = [sid for sid in STRATEGY_SPECS if sid in set(admitted)]
    failures: list[str] = []

    print("=== prep ===")
    print(f"paper_enabled={paper_trading_enabled(settings)} kill={kill_engaged(settings)}")
    print(f"portfolio_cash={portfolio} admitted={len(admitted)} days={days}")

    if not strategies:
        print("FAILED: no admitted strategies")
        return 1

    reset_paper_account(strategy_id="all", settings=settings, clear_kill=True)

    # Solo: one selected strategy gets full portfolio cash.
    sid0 = strategies[0]
    print(f"\n=== solo run {sid0} expect full {portfolio} ===")
    solo = run_paper_days(strategy_id=sid0, days=days, settings=settings, mode="sequential")
    board0 = paper_board(sid0, settings)["summary"]
    check(solo.get("ok") is True, f"solo.ok={solo.get('ok')}", failures)
    check(solo.get("book_cash") == [portfolio], f"solo.book_cash={solo.get('book_cash')}", failures)
    check(solo.get("funding_universe") == [sid0], f"solo.universe={solo.get('funding_universe')}", failures)
    check(approx(board0.get("initial_cash"), portfolio), f"solo.initial={board0.get('initial_cash')}", failures)

    if len(strategies) >= 2:
        reset_paper_account(strategy_id="all", settings=settings, clear_kill=True)
        pair = strategies[:2]
        print(f"\n=== multi run {pair} expect split ===")
        multi = run_paper_days(
            strategy_ids=pair,
            days=days,
            settings=settings,
            mode="sequential",
        )
        check(multi.get("ok") is True, f"multi.ok={multi.get('ok')}", failures)
        book_cash = multi.get("book_cash") or []
        check(len(book_cash) == 2, f"multi.book_cash len={len(book_cash)}", failures)
        check(approx(sum(book_cash), portfolio), f"multi sum={sum(book_cash)}", failures)
        for sid, share in zip(pair, book_cash):
            sm = paper_board(sid, settings)["summary"]
            check(approx(sm.get("initial_cash"), share), f"{sid} initial={sm.get('initial_cash')}", failures)
            snaps = query_all(
                "SELECT position_detail FROM account_snapshot WHERE account_id=?",
                (account_id_for(sid),),
                settings=settings,
            )
            for row in snaps[:3]:
                detail = json.loads(row["position_detail"] or "{}")
                check(
                    approx(detail.get("initial_cash"), share),
                    f"{sid} snap initial {detail.get('initial_cash')}",
                    failures,
                )

    print("\n=== verdict ===")
    if failures:
        print(f"FAILED ({len(failures)})")
        for item in failures:
            print(" -", item)
        return 1
    print("PASSED: solo gets full cash; multi splits among run participants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
