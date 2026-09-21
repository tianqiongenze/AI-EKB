"""P1-⑤ 工业 KPI 端点测试：纯函数单测 + TestClient 集成（路由接线后生效）。"""
from datetime import datetime, timedelta, timezone

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from enterprise_ekb.api.industrial import (
    AUDIT_SAMPLE_LIMIT,
    aggregate_kpis,
    bucket_timeseries,
    clamp_hours,
    compute_oee,
    parse_ts,
)
from enterprise_ekb.app import create_app

# ---------- 纯函数：OEE 计算 ----------

def test_compute_oee_multiplies_three_factors() -> None:
    assert compute_oee(0.9, 0.8, 0.5) == round(0.9 * 0.8 * 0.5, 4)


def test_compute_oee_clamps_out_of_range_inputs() -> None:
    assert compute_oee(1.5, 2.0, 0.5) == 0.5  # 各因子截断到 [0,1]
    assert compute_oee(-1.0, 0.5, 0.5) == 0.0


def test_compute_oee_returns_none_without_performance() -> None:
    # 性能腿缺失时不造假：返回 None 由前端显示 N/A
    assert compute_oee(0.9, None, 0.9) is None


def test_clamp_hours_bounds() -> None:
    assert clamp_hours(0) == 1
    assert clamp_hours(24) == 24
    assert clamp_hours(999) == 168


def test_parse_ts_handles_datetime_and_sqlite_string() -> None:
    dt = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)
    assert parse_ts(dt) == dt
    assert parse_ts("2026-09-21 08:00:00") == dt
    assert parse_ts("2026-09-21T08:00:00+00:00") == dt
    assert parse_ts("garbage") is None
    assert parse_ts(None) is None


# ---------- 纯函数：KPI 聚合 ----------

def _audit(n: int, tenant: str = "group", accepted: bool = True, reason: str = "allow:low-risk", latency_ms: int | None = None, minutes_ago: int = 0):
    payload: dict = {"trace": n}
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    return {
        "id": n,
        "tenant_id": tenant,
        "accepted": accepted,
        "decision_reason": reason,
        "payload": payload,
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
    }


def test_aggregate_kpis_empty_window_returns_zero_values() -> None:
    panel = aggregate_kpis([])
    assert panel["window"]["records"] == 0
    assert panel["overall"]["oee"]["value"] == 0.0
    assert panel["overall"]["defect_distribution"]["items"] == []
    assert panel["overall"]["energy_proxy"]["events_per_hour"] == 0.0
    # 诚实清单必须存在且说明缺失能力
    assert len(panel["unavailable"]) >= 2


def test_aggregate_kpis_computes_oee_from_latency_samples() -> None:
    audits = [
        _audit(1, accepted=True, latency_ms=400),
        _audit(2, accepted=True, latency_ms=500),
        _audit(3, accepted=False, reason="deny:policy", latency_ms=900),
    ]
    panel = aggregate_kpis(audits)
    overall = panel["overall"]
    assert overall["records"] == 3
    assert overall["oee"]["components"]["availability"] == round(2 / 3, 4)
    # p95 取 900ms → performance = 500/900
    assert overall["oee"]["components"]["performance"] == round(500 / 900, 4)
    availability = round(2 / 3, 4)
    performance = round(500 / 900, 4)
    assert overall["oee"]["value"] == compute_oee(availability, performance, availability)
    assert overall["oee"]["proxy_for"] == "equipment_oee"
    assert "basis" in overall["oee"] and overall["oee"]["basis"]
    # 缺陷分布按 decision_reason 聚合
    assert overall["defect_distribution"]["items"] == [{"reason": "deny:policy", "count": 1, "ratio": round(1 / 3, 4)}]
    # 多租户分组
    assert panel["tenants"]["group"]["records"] == 3


def test_aggregate_kpis_no_latency_samples_gives_null_oee() -> None:
    audits = [_audit(1), _audit(2)]
    panel = aggregate_kpis(audits)
    assert panel["overall"]["oee"]["value"] is None
    assert panel["overall"]["oee"]["components"]["performance"] is None
    assert panel["overall"]["first_pass_yield"]["value"] == 1.0


def test_aggregate_kpis_multi_tenant_split() -> None:
    audits = [_audit(1, tenant="group"), _audit(2, tenant="yadea"), _audit(3, tenant="yadea", accepted=False, reason="deny:quota")]
    panel = aggregate_kpis(audits)
    assert set(panel["tenants"]) == {"group", "yadea"}
    assert panel["tenants"]["group"]["records"] == 1
    assert panel["tenants"]["yadea"]["defect_distribution"]["rejected"] == 1


# ---------- 纯函数：时序分桶 ----------

def test_bucket_timeseries_minute_buckets_within_24h() -> None:
    now = datetime.now(timezone.utc)
    audits = [
        _audit(1, minutes_ago=2),
        _audit(2, minutes_ago=2),
        _audit(3, accepted=False, reason="deny", minutes_ago=1),
    ]
    out = bucket_timeseries(audits, "audit_events", 1, now=now)
    assert out["metric"] == "audit_events"
    assert out["bucket_seconds"] == 60
    values = [p["value"] for p in out["points"]]
    assert sum(values) == 3
    assert out["points"][0]["ts"].startswith("20")

    accepted_only = bucket_timeseries(audits, "accepted_events", 1, now=now)
    assert sum(p["value"] for p in accepted_only["points"]) == 2
    rejected_only = bucket_timeseries(audits, "rejected_events", 1, now=now)
    assert sum(p["value"] for p in rejected_only["points"]) == 1


def test_bucket_timeseries_hour_buckets_beyond_24h() -> None:
    audits = [_audit(1, minutes_ago=60)]
    out = bucket_timeseries(audits, "audit_events", 48)
    assert out["bucket_seconds"] == 3600
    assert sum(p["value"] for p in out["points"]) == 1


def test_bucket_timeseries_rejects_unknown_metric() -> None:
    with pytest.raises(Exception):
        bucket_timeseries([], "watt_meter", 24)


# ---------- TestClient 集成：路由已接线时验证鉴权与端点行为 ----------

def _industrial_mounted(app: Litestar) -> bool:
    return any(getattr(r, "path", None) == "/industrial/kpis" for r in app.routes)


@pytest.mark.skipif(
    not _industrial_mounted(create_app()),
    reason="/industrial/* 未接线到 app.ROUTE_MODULES（主线程统一接线后此测试生效）",
)
class TestIndustrialEndpointsWired:
    def test_kpis_and_timeseries_return_ok(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("EKB_AUTH_TOKEN", "t0ken")
        app = create_app(db_path=str(tmp_path / "ind.db"))
        with TestClient(app=app) as client:
            resp = client.get("/industrial/kpis", headers={"Authorization": "Bearer t0ken"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["window"]["records"] == 0 and "overall" in body
            resp2 = client.get(
                "/industrial/timeseries?metric=audit_events&hours=24",
                headers={"Authorization": "Bearer t0ken"},
            )
            assert resp2.status_code == 200
            assert "points" in resp2.json()

    def test_timeseries_rejects_bad_metric(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("EKB_AUTH_TOKEN", "t0ken")
        app = create_app(db_path=str(tmp_path / "ind.db"))
        with TestClient(app=app) as client:
            resp = client.get(
                "/industrial/timeseries?metric=watt",
                headers={"Authorization": "Bearer t0ken"},
            )
            assert resp.status_code == 400


def test_sample_limit_is_bounded() -> None:
    # 防御性契约：KPI 回看条数有上限，避免全表扫描
    assert 0 < AUDIT_SAMPLE_LIMIT <= 10000
