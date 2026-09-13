"""P2 research engine: local backtest behind ResearchEngine / StrategyService."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import execute, executemany, initialize_database, query_all
from asqt.factor_pipeline import compute_factor_frame, write_factor_signals
from asqt.pipeline import check_market_daily
from asqt.selectors import select_targets
from asqt.storage import read_market_daily
from asqt.strategies import (
    CODE_VERSION,
    STOCK_HOLDER_INCREASE_FOLLOW,
    STRATEGY_SPECS,
    adj_close,
    asof_rows,
    factor_specs_for,
    market_by_symbol,
    selector_rules_for,
    suspended_keys,
    weights_for,
)
from asqt.versioning import data_version_for

ALLOWED_TRANSITIONS = {
    "draft": {"backtest"},
    "backtest": {"candidate", "failed"},
    "failed": {"draft"},
    "candidate": {"paper", "retired"},
    "paper": {"paused", "archived", "retired"},
    "paused": {"paper", "retired"},
}

ORDERABLE = {"paper"}
RESEARCH_STATUSES = {"draft", "backtest", "candidate", "failed"}
HOLD_RESEARCH = {"paper", "paused"}
BLOCK_RESEARCH = {"retired", "archived"}
FROZEN_FOR_RESEARCH = HOLD_RESEARCH | BLOCK_RESEARCH
RISK_CONFIG = "docs/p0/risk_defaults.md"


def _nav_metrics(points: list[dict[str, Any]], *, start_nav: float = 1.0) -> dict[str, Any]:
    """Segment metrics relative to ``start_nav`` (not the first point's nav).

    Backtest points store cumulative NAV from the full-run start. IS therefore
    uses ``start_nav=1``; OOS uses the last in-sample NAV so
    ``(1+is)*(1+oos) == final_nav``.
    """
    if not points:
        return {"n_days": 0, "total_return": 0.0, "max_drawdown": 0.0}
    baseline = float(start_nav)
    if baseline <= 0:
        baseline = 1.0
    navs = [baseline] + [float(item["nav"]) for item in points]
    peak = navs[0]
    max_dd = 0.0
    for value in navs:
        peak = max(peak, value)
        if peak:
            max_dd = min(max_dd, value / peak - 1.0)
    return {
        "n_days": len(points),
        "total_return": round(navs[-1] / baseline - 1.0, 10),
        "max_drawdown": round(max_dd, 10),
    }


class LocalStrategyService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def list_versions(self, strategy_id: str | None = None) -> list[dict[str, Any]]:
        if strategy_id:
            return query_all(
                "SELECT * FROM strategy_version WHERE strategy_id = ? ORDER BY created_at",
                (strategy_id,),
                settings=self.settings,
            )
        return query_all("SELECT * FROM strategy_version ORDER BY strategy_id, created_at", settings=self.settings)

    def generate_target_positions(self, strategy_id: str, trade_date: str) -> list[dict[str, Any]]:
        version = self._require_orderable(strategy_id)
        rows = read_market_daily(end=trade_date, settings=self.settings)
        limits = query_all(
            "SELECT * FROM limit_suspension WHERE trade_date = ?",
            (trade_date,),
            settings=self.settings,
        )
        params = dict(STRATEGY_SPECS[strategy_id]["params"])
        rebalance_every_n = max(1, int(params.get("rebalance_every_n") or 1))
        dates = sorted({str(row["trade_date"]) for row in rows})
        signal_index = dates.index(trade_date) if trade_date in dates else -1
        hold_prior = (
            rebalance_every_n > 1
            and signal_index > 0
            and signal_index % rebalance_every_n != 0
        )
        if hold_prior:
            prior = query_all(
                """
                SELECT symbol, target_weight FROM target_position
                WHERE strategy_id = ? AND trade_date = (
                    SELECT MAX(trade_date) FROM target_position
                    WHERE strategy_id = ? AND trade_date < ?
                )
                """,
                (strategy_id, strategy_id, trade_date),
                settings=self.settings,
            )
            weights = {str(row["symbol"]): float(row["target_weight"]) for row in prior}
        else:
            weights = weights_for(
                strategy_id,
                rows,
                trade_date,
                limits=limits,
                params=params,
                settings=self.settings,
            )
        pool_tags = params.get("pool_tags")
        if pool_tags:
            from asqt.tags import resolve_pool

            allowed = resolve_pool(pool_tags, settings=self.settings)
            weights = {symbol: weight for symbol, weight in weights.items() if symbol in allowed}
        from asqt.overrides import apply_overrides

        weights, override_reasons = apply_overrides(weights, strategy_id, settings=self.settings)
        data_version = data_version_for(asof_rows(rows, trade_date))
        from asqt.decision_log import record_pending

        decision = record_pending(
            strategy_id=strategy_id,
            signal_date=trade_date,
            weights=weights,
            strategy_version=version["version"],
            data_version=data_version,
            settings=self.settings,
        )
        decision_id = str(decision["decision_id"])
        execute(
            "DELETE FROM target_position WHERE strategy_id = ? AND trade_date = ?",
            (strategy_id, trade_date),
            settings=self.settings,
        )
        default_reason = STRATEGY_SPECS[strategy_id]["kind"]
        records = [
            {
                "target_id": str(uuid4()),
                "trade_date": trade_date,
                "strategy_id": strategy_id,
                "strategy_version": version["version"],
                "symbol": symbol,
                "target_weight": weight,
                "target_amount": None,
                "target_volume": None,
                "reason": override_reasons.get(symbol, default_reason),
                "data_version": data_version,
                "decision_id": decision_id,
            }
            for symbol, weight in weights.items()
        ]
        if records:
            executemany(
                """
                INSERT INTO target_position
                    (target_id, trade_date, strategy_id, strategy_version, symbol,
                     target_weight, target_amount, target_volume, reason, data_version, decision_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["target_id"],
                        item["trade_date"],
                        item["strategy_id"],
                        item["strategy_version"],
                        item["symbol"],
                        item["target_weight"],
                        item["target_amount"],
                        item["target_volume"],
                        item["reason"],
                        item["data_version"],
                        item["decision_id"],
                    )
                    for item in records
                ],
                settings=self.settings,
            )
        return records

    def current_version(self, strategy_id: str) -> dict[str, Any] | None:
        versions = self.list_versions(strategy_id)
        return versions[-1] if versions else None

    def admit_to_paper(self, strategy_id: str, reason: str, *, actor: str = "operator") -> dict[str, Any]:
        return self._lifecycle(strategy_id, "paper", reason, actor=actor, require_experiment=True)

    def pause(self, strategy_id: str, reason: str, *, actor: str = "operator") -> dict[str, Any]:
        return self._lifecycle(strategy_id, "paused", reason, actor=actor)

    def resume(self, strategy_id: str, reason: str, *, actor: str = "operator") -> dict[str, Any]:
        return self._lifecycle(strategy_id, "paper", reason, actor=actor, require_experiment=True)

    def retire(self, strategy_id: str, reason: str, *, actor: str = "operator") -> dict[str, Any]:
        return self._lifecycle(strategy_id, "retired", reason, actor=actor)

    def _lifecycle(
        self,
        strategy_id: str,
        new_status: str,
        reason: str,
        *,
        actor: str,
        require_experiment: bool = False,
    ) -> dict[str, Any]:
        from asqt.risk_gate import evaluate as evaluate_risk_gate

        if not (reason or "").strip():
            raise ValueError("lifecycle change requires a reason")
        current = self.current_version(strategy_id)
        if not current:
            raise PermissionError(f"{strategy_id} has no version")
        if new_status == "paper":
            gate = evaluate_risk_gate(
                purpose="admit",
                strategy_id=strategy_id,
                settings=self.settings,
                require_experiment=require_experiment,
                check_overrides=True,
            )
            if gate.rejected or gate.decision == "review":
                raise PermissionError(gate.reason_code)
            execute(
                """
                UPDATE strategy_version
                SET risk_config = ?, effective_date = COALESCE(effective_date, ?)
                WHERE strategy_id = ? AND version = ?
                """,
                (RISK_CONFIG, datetime.now(timezone.utc).date().isoformat(), strategy_id, current["version"]),
                settings=self.settings,
            )
        LocalResearchEngine(self.settings)._transition(strategy_id, new_status, actor, reason)
        updated = self.current_version(strategy_id)
        assert updated is not None
        return updated

    def _require_orderable(self, strategy_id: str) -> dict[str, Any]:
        versions = self.list_versions(strategy_id)
        if not versions:
            raise PermissionError(f"{strategy_id} has no version; draft/backtest cannot emit targets")
        current = versions[-1]
        if current["status"] not in ORDERABLE:
            raise PermissionError(
                f"{strategy_id} status={current['status']} cannot generate target positions"
            )
        return current


class LocalResearchEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)
        self.strategies = LocalStrategyService(self.settings)

    def run_backtest(
        self,
        strategy_id: str,
        parameter_set_id: str,
        data_version: str,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        if strategy_id not in STRATEGY_SPECS:
            raise ValueError(f"unknown strategy: {strategy_id}")
        spec = STRATEGY_SPECS[strategy_id]
        if parameter_set_id != spec["parameter_set_id"]:
            raise ValueError(f"parameter_set_id must be {spec['parameter_set_id']}")

        rows = read_market_daily(settings=self.settings)
        computed_version = data_version_for(rows)
        if data_version not in {"auto", computed_version}:
            raise ValueError("data_version does not match current market_daily")
        data_version = computed_version

        dates = sorted({str(row["trade_date"]) for row in rows})
        steps = max(1, len(dates) - 1)
        if progress:
            progress(0, steps, f"{strategy_id} quality")

        quality = check_market_daily(settings=self.settings)
        run_id = str(uuid4())
        held = self._held_lifecycle(strategy_id)
        if held in BLOCK_RESEARCH:
            raise ValueError(f"{strategy_id} 已{held}，不能重跑回测")
        if held:
            self._audit(strategy_id, "research_rerun", held, held, f"keep lifecycle {run_id}")
            execute(
                """
                UPDATE strategy_version
                SET code_version = ?
                WHERE strategy_id = ? AND version = 'v1'
                """,
                (CODE_VERSION, strategy_id),
                settings=self.settings,
            )
        else:
            self._ensure_version(strategy_id, spec["parameter_set_id"], "draft")
            self._transition(strategy_id, "backtest", run_id, "start backtest")

        if not quality.get("trade_allowed", False):
            if held:
                report = {
                    "ok": False,
                    "run_id": run_id,
                    "strategy_id": strategy_id,
                    "parameter_set_id": spec["parameter_set_id"],
                    "code_version": CODE_VERSION,
                    "data_version": data_version,
                    "status": held,
                    "reason": "quality_block",
                    "quality": {"trade_allowed": False, "issue_count": quality.get("issue_count", 0)},
                }
                path = self._write_report(report)
                report["experiment_path"] = str(path)
                return report
            report = self._fail(strategy_id, run_id, data_version, "quality_block", quality)
            return report

        in_sample_end = self._in_sample_end(rows)
        limits = query_all("SELECT * FROM limit_suspension", settings=self.settings)
        grouped = market_by_symbol(rows)
        halted = suspended_keys(limits)
        nav = 1.0
        is_points: list[dict[str, Any]] = []
        oos_points: list[dict[str, Any]] = []
        last_weights: dict[str, float] = {}

        by_date_symbol = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
        params = dict(spec["params"])
        rebalance_every_n = max(1, int(params.get("rebalance_every_n") or 1))
        # Precompute factors once; daily loop only select_targets (plan §2).
        signal_dates = dates[:-1]
        event_rows = None
        if strategy_id == STOCK_HOLDER_INCREASE_FOLLOW:
            from asqt.events import query_events

            event_rows = query_events(settings=self.settings, newest_first=False)
        factor_payload = compute_factor_frame(
            grouped,
            factor_specs_for(strategy_id, params, events=event_rows, settings=self.settings),
            dates=signal_dates,
            source_run_id=run_id,
            model_version=CODE_VERSION,
        )
        factors_by_date: dict[str, list[dict[str, Any]]] = {}
        for row in factor_payload:
            factors_by_date.setdefault(str(row["trade_date"]), []).append(row)
        rules = selector_rules_for(strategy_id, params)
        for index, signal_date in enumerate(signal_dates):
            fill_date = dates[index + 1]
            if index % rebalance_every_n == 0 or not last_weights:
                weights = select_targets(
                    factors_by_date.get(signal_date, []),
                    signal_date,
                    rules,
                    limits=limits,
                    suspended=halted,
                )
            else:
                weights = dict(last_weights)
            # Hook point for tags/overrides on paper targets lives in
            # generate_target_positions (apply_overrides); backtest stays pure.
            last_weights = weights
            period_return = 0.0
            for symbol, weight in weights.items():
                left = by_date_symbol.get((signal_date, symbol))
                right = by_date_symbol.get((fill_date, symbol))
                if not left or not right:
                    continue
                start_px = adj_close(left)
                if start_px <= 0:
                    continue
                period_return += weight * (adj_close(right) / start_px - 1.0)
            nav = round(nav * (1.0 + period_return), 12)
            point = {"trade_date": fill_date, "nav": nav, "gross": round(sum(weights.values()), 10)}
            if fill_date <= in_sample_end:
                is_points.append(point)
            else:
                oos_points.append(point)
            if progress and (index == 0 or index + 1 == steps or index % 8 == 0):
                progress(index + 1, steps, f"{strategy_id} {fill_date}")

        if progress:
            progress(steps, steps, f"{strategy_id} persist")
        self._write_factors(factor_payload)
        research_ok = bool(oos_points)
        if held:
            status = held
            reason = "oos isolated" if research_ok else "missing_oos_window"
        elif research_ok:
            status = "candidate"
            reason = "oos isolated"
            self._transition(strategy_id, "candidate", run_id, reason)
        else:
            status = "failed"
            reason = "missing_oos_window"
            self._transition(strategy_id, "failed", run_id, reason)

        is_metrics = _nav_metrics(is_points, start_nav=1.0)
        oos_start = float(is_points[-1]["nav"]) if is_points else 1.0
        oos_metrics = _nav_metrics(oos_points, start_nav=oos_start)
        report = {
            "ok": research_ok,
            "run_id": run_id,
            "strategy_id": strategy_id,
            "kind": spec["kind"],
            "parameter_set_id": spec["parameter_set_id"],
            "code_version": CODE_VERSION,
            "data_version": data_version,
            "status": status,
            "t_plus_one": True,
            "in_sample_end": in_sample_end,
            "nav": round(nav, 10),
            "metrics": {"is": is_metrics, "oos": oos_metrics},
            "last_weights": last_weights,
            "quality": {"trade_allowed": True, "issue_count": quality.get("issue_count", 0)},
            "factor_rows": len(factor_payload),
        }
        path = self._write_report(report)
        report["experiment_path"] = str(path)
        return report

    def _in_sample_end(self, rows: list[dict[str, Any]]) -> str:
        dates = sorted({str(row["trade_date"]) for row in rows})
        if len(dates) < 4:
            raise ValueError("need at least 4 trade dates to isolate an out-of-sample window")
        return dates[int(len(dates) * 0.7)]

    def _ensure_version(self, strategy_id: str, parameter_set_id: str, status: str) -> None:
        existing = query_all(
            "SELECT strategy_id FROM strategy_version WHERE strategy_id = ? AND version = ?",
            (strategy_id, "v1"),
            settings=self.settings,
        )
        if existing:
            return
        execute(
            """
            INSERT INTO strategy_version
                (strategy_id, version, status, parameter_set_id, code_version, risk_config, effective_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (strategy_id, "v1", status, parameter_set_id, CODE_VERSION, RISK_CONFIG, None),
            settings=self.settings,
        )
        self._audit(strategy_id, "create", None, status, "register p2 strategy")

    def _held_lifecycle(self, strategy_id: str) -> str | None:
        current = self.strategies.current_version(strategy_id)
        if not current:
            return None
        status = current["status"]
        if status in FROZEN_FOR_RESEARCH:
            return status
        return None

    def _transition(self, strategy_id: str, new_status: str, run_id: str, reason: str) -> None:
        current = query_all(
            "SELECT status FROM strategy_version WHERE strategy_id = ? AND version = ?",
            (strategy_id, "v1"),
            settings=self.settings,
        )
        before = current[0]["status"] if current else None
        if before == new_status:
            return
        if before in FROZEN_FOR_RESEARCH and new_status in RESEARCH_STATUSES | {"backtest"}:
            raise ValueError(f"{strategy_id} 已是{before}，不能改回测状态")
        allowed = ALLOWED_TRANSITIONS.get(before or "", set())
        if before and new_status not in allowed:
            if before == "candidate" and new_status == "backtest":
                execute(
                    "UPDATE strategy_version SET status = ? WHERE strategy_id = ? AND version = ?",
                    ("draft", strategy_id, "v1"),
                    settings=self.settings,
                )
                self._audit(strategy_id, "rerun", "candidate", "draft", run_id)
                before = "draft"
                allowed = ALLOWED_TRANSITIONS[before]
            elif before == "failed" and new_status == "backtest":
                execute(
                    "UPDATE strategy_version SET status = ? WHERE strategy_id = ? AND version = ?",
                    ("draft", strategy_id, "v1"),
                    settings=self.settings,
                )
                self._audit(strategy_id, "rerun", "failed", "draft", run_id)
                before = "draft"
            else:
                raise ValueError(f"{strategy_id} 不允许从 {before} 进入 {new_status}")
        execute(
            "UPDATE strategy_version SET status = ? WHERE strategy_id = ? AND version = ?",
            (new_status, strategy_id, "v1"),
            settings=self.settings,
        )
        self._audit(strategy_id, "transition", before, new_status, f"{reason} {run_id}")

    def _audit(self, strategy_id: str, action: str, before: str | None, after: str | None, reason: str) -> None:
        execute(
            """
            INSERT INTO operation_audit
                (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), "research_engine", action, "strategy_version", strategy_id, reason, before, after),
            settings=self.settings,
        )

    def _fail(self, strategy_id: str, run_id: str, data_version: str, reason: str, quality: dict[str, Any]) -> dict[str, Any]:
        self._transition(strategy_id, "failed", run_id, reason)
        report = {
            "ok": False,
            "run_id": run_id,
            "strategy_id": strategy_id,
            "parameter_set_id": STRATEGY_SPECS[strategy_id]["parameter_set_id"],
            "code_version": CODE_VERSION,
            "data_version": data_version,
            "status": "failed",
            "reason": reason,
            "quality": {"trade_allowed": False, "issue_count": quality.get("issue_count", 0)},
        }
        path = self._write_report(report)
        report["experiment_path"] = str(path)
        return report

    def _write_factors(self, rows: list[dict[str, Any]]) -> None:
        write_factor_signals(rows, settings=self.settings)

    def _write_report(self, report: dict[str, Any]) -> Path:
        from asqt.reporting import write_run_tree

        run_id = str(report.get("run_id") or "unknown")
        return write_run_tree(
            "backtest",
            run_id,
            report,
            settings=self.settings,
            strategy_id=str(report.get("strategy_id") or ""),
            manifest={"code_version": report.get("code_version"), "data_version": report.get("data_version")},
        )


def run_p2_acceptance_suite(settings: Settings | None = None) -> dict[str, Any]:
    engine = LocalResearchEngine(settings)
    reports = []
    for strategy_id in STRATEGY_SPECS:
        reports.append(
            engine.run_backtest(
                strategy_id,
                STRATEGY_SPECS[strategy_id]["parameter_set_id"],
                "auto",
            )
        )
    return {"ok": all(item.get("ok") for item in reports), "reports": reports}
