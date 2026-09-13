"""市场事件功能完整回归：拉取/去重数量、分页、筛选、重置、列表字段。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.config import Settings
from asqt.events import make_event_id, normalize_holder_trade_row, pull_holder_trade_events


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "market_events.json"
FRONTEND_INDEX = ROOT / "frontend" / "index.html"
FRONTEND_APP_JS = ROOT / "frontend" / "assets" / "app.js"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "asqt.sqlite3",
        parquet_dir=tmp_path / "data" / "parquet",
        raw_dir=tmp_path / "data" / "raw_data",
        standard_dir=tmp_path / "data" / "standard_data",
        qlib_dir=tmp_path / "data" / "qlib_data",
        experiment_dir=tmp_path / "data" / "experiment",
        logs_dir=tmp_path / "data" / "logs",
        frontend_dir=tmp_path / "frontend",
    )


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Settings]:
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    return TestClient(create_app()), settings


def _wait_events_pull(client: TestClient, run_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/events/pull/{run_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("status") in {"success", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"events pull {run_id} did not finish: {last}")


def _pull_events(client: TestClient, payload: dict | None = None) -> dict:
    started = client.post("/api/events/pull", json=payload or {})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body.get("run_id"), body
    done = _wait_events_pull(client, body["run_id"])
    assert done["status"] == "success", done
    result = done.get("result") or {}
    assert isinstance(result, dict), done
    return result


def _raw_row(
    ts_code: str,
    ann_date: str,
    holder_name: str,
    in_de: str,
    change_vol: float,
) -> dict:
    return {
        "ts_code": ts_code,
        "ann_date": ann_date,
        "holder_name": holder_name,
        "holder_type": "P",
        "in_de": in_de,
        "change_vol": change_vol,
        "change_ratio": 0.1,
        "after_share": None,
        "after_ratio": None,
        "avg_price": 10.0,
        "total_share": None,
        "begin_date": None,
        "close_date": None,
    }


class BulkFakeTushare:
    """Simulate a pull batch with intentional duplicates (same event_id)."""

    source_id = "tushare"
    last_errors: list[dict[str, str]] = []

    def __init__(self, rows: list[dict]):
        self._rows = list(rows)

    def fetch_stk_holdertrade(self, symbols=None, start=None, end=None, *, trade_type=None):
        return list(self._rows)


def _unique_event_ids(raw_rows: list[dict]) -> set[str]:
    ids: set[str] = set()
    for raw in raw_rows:
        ids.add(normalize_holder_trade_row(raw)["event_id"])
    return ids


REQUIRED_LIST_FIELDS = {
    "event_id",
    "event_date",
    "asof_date",
    "event_type",
    "symbol",
    "actor",
    "value",
    "source",
}


def test_frontend_events_controls_present():
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = FRONTEND_APP_JS.read_text(encoding="utf-8")
    for needle in (
        'id="events-filters"',
        'id="events-type"',
        'id="events-symbol"',
        'id="events-start"',
        'id="events-end"',
        'id="events-reset"',
        'id="events-import"',
        'id="events-pull"',
        'id="events-prev"',
        'id="events-next"',
        'id="events-page-label"',
        'id="events-body"',
        'class="col-actor"',
    ):
        assert needle in html, f"missing UI control: {needle}"
    assert "EVENTS_PAGE_SIZE = 10" in js
    assert "events-reset" in js
    assert "unique_in_batch" in js
    assert "stored_total" in js


def test_events_regression_empty_list_then_pull_dedup_and_pagination(tmp_path: Path, monkeypatch):
    client, settings = _client(tmp_path, monkeypatch)

    empty = client.get("/api/events", params={"page": 1, "page_size": 10})
    assert empty.status_code == 200
    body = empty.json()
    assert body == {"items": [], "total": 0, "page": 1, "pages": 1, "page_size": 10}

    # 25 unique + 10 exact duplicates of the first unique → fetched 35, unique 25.
    unique_raw: list[dict] = []
    for i in range(25):
        code = f"{i:06d}.SZ"
        unique_raw.append(
            _raw_row(
                code,
                f"202403{(i % 28) + 1:02d}",
                f"Holder {i}",
                "IN" if i % 2 == 0 else "DE",
                1000 + i,
            )
        )
    batch = unique_raw + unique_raw[:10]
    assert len(batch) == 35
    expected_unique = len(_unique_event_ids(batch))
    assert expected_unique == 25

    monkeypatch.setattr(
        "asqt.adapters.tushare_source.TushareAdapter",
        lambda *a, **k: BulkFakeTushare(batch),
    )
    pulled = _pull_events(client, {"start": "2024-03-01", "end": "2024-03-31"})
    stats = pulled
    assert stats["fetched"] == 35
    assert stats["upserted"] == 35
    assert stats["unique_in_batch"] == 25
    assert stats["deduped_in_batch"] == 10
    assert stats["stored_total"] == 25
    assert stats["persisted"]["sqlite"] == "market_event"

    # List meta must match stored unique count (the UI "共 N 条").
    page1 = client.get("/api/events", params={"page": 1, "page_size": 10})
    assert page1.status_code == 200
    p1 = page1.json()
    assert p1["total"] == 25
    assert p1["page"] == 1
    assert p1["pages"] == 3
    assert p1["page_size"] == 10
    assert len(p1["items"]) == 10
    for row in p1["items"]:
        assert REQUIRED_LIST_FIELDS <= set(row)
        assert row["source"] == "tushare"
        assert row["event_type"] in {"holder_increase", "holder_decrease"}

    page3 = client.get("/api/events", params={"page": 3, "page_size": 10})
    assert page3.status_code == 200
    p3 = page3.json()
    assert p3["page"] == 3
    assert len(p3["items"]) == 5
    assert p3["total"] == 25

    # Overflow page clamps to last page.
    overflow = client.get("/api/events", params={"page": 99, "page_size": 10})
    assert overflow.status_code == 200
    assert overflow.json()["page"] == 3
    assert len(overflow.json()["items"]) == 5

    # Second identical pull: fetched again, stored_total stays unique.
    stats2 = _pull_events(client, {})
    assert stats2["fetched"] == 35
    assert stats2["stored_total"] == 25
    listed = client.get("/api/events", params={"page_size": 10})
    assert listed.json()["total"] == 25


def test_events_regression_pull_rejects_concurrent(tmp_path: Path, monkeypatch):
    import threading

    client, _settings = _client(tmp_path, monkeypatch)
    gate = threading.Event()
    released = threading.Event()

    class SlowFake:
        source_id = "tushare"
        last_errors: list = []
        last_holdertrade_meta = {
            "start": "2024-03-01",
            "end": "2024-03-31",
            "requests": 1,
            "chunks": 1,
            "chunk_hits_limit": [],
            "day_hits_limit": [],
        }

        def fetch_stk_holdertrade(self, symbols=None, start=None, end=None, *, trade_type=None):
            gate.set()
            assert released.wait(timeout=2.0)
            return [_raw_row("000001.SZ", "20240310", "Slow", "IN", 1)]

    monkeypatch.setattr(
        "asqt.adapters.tushare_source.TushareAdapter",
        lambda *a, **k: SlowFake(),
    )
    first = client.post("/api/events/pull", json={"start": "2024-03-01", "end": "2024-03-31"})
    assert first.status_code == 200, first.text
    assert gate.wait(timeout=2.0)
    second = client.post("/api/events/pull", json={})
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "events_busy"
    released.set()
    done = _wait_events_pull(client, first.json()["run_id"])
    assert done["status"] == "success"
    assert done["result"]["stored_total"] == 1


def test_events_regression_filters_and_reset(tmp_path: Path, monkeypatch):
    client, _settings = _client(tmp_path, monkeypatch)

    imported = client.post("/api/events/import", json={"path": str(FIXTURE)})
    assert imported.status_code == 200
    assert imported.json()["imported"] == 4

    all_rows = client.get("/api/events", params={"page_size": 10})
    assert all_rows.status_code == 200
    assert all_rows.json()["total"] == 4
    assert len(all_rows.json()["items"]) == 4

    # Type filter.
    only_inc = client.get(
        "/api/events",
        params={"event_type": "holder_increase", "page_size": 10},
    )
    assert only_inc.status_code == 200
    inc_body = only_inc.json()
    assert inc_body["total"] == 3
    assert len(inc_body["items"]) == 3
    assert all(row["event_type"] == "holder_increase" for row in inc_body["items"])

    only_dec = client.get(
        "/api/events",
        params={"event_type": "holder_decrease", "page_size": 10},
    )
    assert only_dec.json()["total"] == 1
    assert only_dec.json()["items"][0]["symbol"] == "000001.SZ"

    # Fuzzy symbol (UI search box).
    fuzzy = client.get("/api/events", params={"symbol": "000001", "page_size": 10})
    assert fuzzy.status_code == 200
    fuzzy_body = fuzzy.json()
    assert fuzzy_body["total"] == 2
    assert {row["symbol"] for row in fuzzy_body["items"]} == {"000001.SZ"}
    assert {row["event_type"] for row in fuzzy_body["items"]} == {
        "holder_increase",
        "holder_decrease",
    }

    fuzzy_sh = client.get("/api/events", params={"symbol": "600", "page_size": 10})
    assert fuzzy_sh.json()["total"] == 1
    assert fuzzy_sh.json()["items"][0]["symbol"] == "600000.SH"

    # Date range (start/end on event_date).
    ranged = client.get(
        "/api/events",
        params={"start": "2024-01-01", "end": "2024-01-12", "page_size": 10},
    )
    assert ranged.status_code == 200
    ranged_body = ranged.json()
    assert ranged_body["total"] == 2
    assert {row["event_date"] for row in ranged_body["items"]} == {"2024-01-05", "2024-01-10"}

    # Combined filters.
    combo = client.get(
        "/api/events",
        params={
            "event_type": "holder_increase",
            "symbol": "000",
            "start": "2024-01-01",
            "end": "2024-01-31",
            "page_size": 10,
        },
    )
    assert combo.json()["total"] == 2
    assert {row["symbol"] for row in combo.json()["items"]} == {"000001.SZ", "000002.SZ"}

    # Reset ≡ clear all filters → back to full universe.
    reset = client.get("/api/events", params={"page": 1, "page_size": 10})
    assert reset.json()["total"] == 4
    assert len(reset.json()["items"]) == 4
    assert {row["symbol"] for row in reset.json()["items"]} == {
        "000001.SZ",
        "000002.SZ",
        "600000.SH",
    }

    # Types endpoint used by UI dropdown.
    types = client.get("/api/events/types")
    assert types.status_code == 200
    assert set(types.json()) == {"holder_decrease", "holder_increase"}


def test_events_regression_pull_then_list_content_matches_normalized(tmp_path: Path, monkeypatch):
    client, settings = _client(tmp_path, monkeypatch)
    raw = [
        _raw_row("600519.SH", "20240912", "贵州茅台酒厂(集团)有限责任公司", "IN", 2398600),
        _raw_row("001298.SZ", "20240912", "深圳市点通投资管理中心(有限合伙)", "DE", 1689330),
        # Duplicate of first row → should not inflate stored_total.
        _raw_row("600519.SH", "20240912", "贵州茅台酒厂(集团)有限责任公司", "IN", 2398600),
    ]
    monkeypatch.setattr(
        "asqt.adapters.tushare_source.TushareAdapter",
        lambda *a, **k: BulkFakeTushare(raw),
    )

    stats = _pull_events(client, {"start": "2024-09-01", "end": "2024-09-30"})
    assert stats["fetched"] == 3
    assert stats["upserted"] == 3
    assert stats["unique_in_batch"] == 2
    assert stats["deduped_in_batch"] == 1
    assert stats["stored_total"] == 2

    listed = client.get("/api/events", params={"page": 1, "page_size": 10})
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert body["pages"] == 1
    assert len(body["items"]) == 2

    by_symbol = {row["symbol"]: row for row in body["items"]}
    assert set(by_symbol) == {"600519.SH", "001298.SZ"}

    expected_inc = normalize_holder_trade_row(raw[0])
    expected_dec = normalize_holder_trade_row(raw[1])
    got_inc = by_symbol["600519.SH"]
    got_dec = by_symbol["001298.SZ"]

    assert got_inc["event_type"] == "holder_increase"
    assert got_inc["event_date"] == "2024-09-12"
    assert got_inc["asof_date"] == "2024-09-12"
    assert got_inc["actor"] == "贵州茅台酒厂(集团)有限责任公司"
    assert got_inc["value"] == 2398600.0
    assert got_inc["source"] == "tushare"
    assert got_inc["event_id"] == expected_inc["event_id"]
    assert got_inc["event_id"] == make_event_id(
        event_type="holder_increase",
        symbol="600519.SH",
        event_date="2024-09-12",
        actor="贵州茅台酒厂(集团)有限责任公司",
        value=2398600.0,
        source="tushare",
    )

    assert got_dec["event_type"] == "holder_decrease"
    assert got_dec["value"] == -1689330.0
    assert got_dec["actor"] == "深圳市点通投资管理中心(有限合伙)"
    assert got_dec["event_id"] == expected_dec["event_id"]

    # Direct pull helper stays consistent with API list totals.
    again = pull_holder_trade_events(
        settings=settings,
        adapter=BulkFakeTushare(raw),
        start="2024-09-01",
        end="2024-09-30",
    )
    assert again["stored_total"] == 2
    listed2 = client.get("/api/events", params={"page_size": 10})
    assert listed2.json()["total"] == again["stored_total"]


def test_events_regression_import_then_pull_accumulates_unique(tmp_path: Path, monkeypatch):
    client, _settings = _client(tmp_path, monkeypatch)

    imported = client.post("/api/events/import", json={"path": str(FIXTURE)})
    assert imported.json()["imported"] == 4
    assert client.get("/api/events").json()["total"] == 4

    raw = [_raw_row("000001.SZ", "20240310", "API Mock", "DE", 99)]
    monkeypatch.setattr(
        "asqt.adapters.tushare_source.TushareAdapter",
        lambda *a, **k: BulkFakeTushare(raw),
    )
    stats = _pull_events(client, {"symbols": ["000001.SZ"]})
    assert stats["stored_total"] == 5

    listed = client.get("/api/events", params={"page_size": 10})
    assert listed.json()["total"] == 5
    sources = {row["source"] for row in listed.json()["items"]}
    assert sources == {"fixture", "tushare"}

    # Filter to tushare-only via fuzzy+type still works after mix.
    tushare_dec = client.get(
        "/api/events",
        params={"event_type": "holder_decrease", "symbol": "000001", "page_size": 10},
    )
    assert tushare_dec.json()["total"] == 2
    assert {row["source"] for row in tushare_dec.json()["items"]} == {"fixture", "tushare"}
