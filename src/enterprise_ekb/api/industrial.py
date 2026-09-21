"""P1-⑤ 工业 KPI 看板聚合端点（只读）。

诚实口径（MPB）：所有指标均从控制面既有公开 store 方法（recent_audits）聚合推导，
是产线 proxy 指标而非真实 PLC/电表数据——每个 KPI 的 ``basis`` 字段写明数据来源与口径，
缺失读路径的能力（如 harness_runs 延迟查询）列入 ``unavailable``，绝不编造数值。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from litestar import Request, get
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext

# 供 KPI 聚合的最大审计回看条数（recent_audits 为公开读方法，LIMIT 上限保护）。
AUDIT_SAMPLE_LIMIT = 5000
# 性能腿推导目标：审计 payload 携带的 latency_ms 优于该值视为满性能（proxy 口径）。
LATENCY_TARGET_MS = 500.0

TIMESERIES_METRICS = ("audit_events", "accepted_events", "rejected_events")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_oee(availability: float, performance: float | None, quality: float) -> float | None:
    """OEE = 可用率 × 性能率 × 良率。

    performance 为 None（窗口内无延迟样本）时无法诚实给出三因子乘积，返回 None
    而非用假值补位。
    """
    if performance is None:
        return None
    return round(_clamp01(availability) * _clamp01(performance) * _clamp01(quality), 4)


def parse_ts(value: Any) -> datetime | None:
    """容错解析 recent_audits 返回的 created_at（datetime 或 SQLite 字符串）。"""
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace(" ", "T", 1)
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def clamp_hours(hours: int) -> int:
    return max(1, min(168, int(hours)))


def _latency_samples(audits: list[dict[str, Any]]) -> list[float]:
    samples: list[float] = []
    for row in audits:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        for key in ("latency_ms", "latency_p95_ms", "duration_ms"):
            raw = payload.get(key)
            if isinstance(raw, (int, float)) and raw > 0:
                samples.append(float(raw))
                break
    return samples


def _performance_from_latency(samples: list[float]) -> float | None:
    """性能率 proxy = min(1, 目标时延 / p95 时延)。无样本返回 None。"""
    if not samples:
        return None
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
    p95 = ordered[idx] or 1.0
    return round(_clamp01(LATENCY_TARGET_MS / p95), 4)


def _tenant_kpis(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """单租户（或全局）KPI 聚合：输入为 recent_audits 形状的 dict 列表。"""
    total = len(audits)
    accepted = sum(1 for row in audits if row.get("accepted"))
    rejected = total - accepted

    if total == 0:
        return {
            "records": 0,
            "oee": {
                "value": 0.0,
                "components": {"availability": 0.0, "performance": None, "quality": 0.0},
                "proxy_for": "equipment_oee",
                "basis": "窗口内无审计数据，返回零值（不造假数据）",
            },
            "first_pass_yield": {
                "value": 0.0,
                "accepted": 0,
                "total": 0,
                "proxy_for": "line_first_pass_yield",
                "basis": "窗口内无审计数据，返回零值",
            },
            "defect_distribution": {
                "items": [],
                "rejected": 0,
                "total": 0,
                "proxy_for": "quality_defect_pareto",
                "basis": "窗口内无审计数据，返回空分布",
            },
            "energy_proxy": {
                "events_per_hour": 0.0,
                "total_events": 0,
                "window_hours": 0.0,
                "proxy_for": "plant_energy_consumption",
                "basis": "窗口内无审计数据，返回零值",
            },
        }

    availability = round(accepted / total, 4)
    quality = round(accepted / total, 4)  # 良率 proxy：无拒绝即视为良品直行
    samples = _latency_samples(audits)
    performance = _performance_from_latency(samples)
    oee_value = compute_oee(availability, performance, quality)

    # 缺陷分布：拒绝事件按 decision_reason 聚合（帕累托降序）。
    defect_counts: dict[str, int] = {}
    for row in audits:
        if row.get("accepted"):
            continue
        reason = str(row.get("decision_reason") or "unknown")
        defect_counts[reason] = defect_counts.get(reason, 0) + 1
    defects = [
        {"reason": reason, "count": count, "ratio": round(count / total, 4)}
        for reason, count in sorted(defect_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 能耗 proxy：窗口跨度内的事件密度（事件量/小时），非真实电表读数。
    stamps = [t for t in (parse_ts(row.get("created_at")) for row in audits) if t is not None]
    if len(stamps) >= 2:
        span_seconds = max((max(stamps) - min(stamps)).total_seconds(), 60.0)
        window_hours = round(span_seconds / 3600.0, 4)
    else:
        window_hours = 1.0
    events_per_hour = round(total / max(window_hours, 1e-6), 4)

    latency_note = (
        f"窗口内 {len(samples)} 条审计 payload 携带 latency 样本，p95 推导性能率"
        if samples
        else "窗口内审计 payload 无 latency 字段，性能腿缺失，OEE 置为 null（不造假）"
    )

    return {
        "records": total,
        "oee": {
            "value": oee_value,
            "components": {
                "availability": availability,
                "performance": performance,
                "quality": quality,
            },
            "proxy_for": "equipment_oee",
            "basis": (
                "可用率=accepted/total（放行率 proxy）；性能率=min(1, "
                f"{int(LATENCY_TARGET_MS)}ms/延迟p95)；良率=accepted/total。"
                f"数据源：recent_audits 控制面审计，非 PLC 实测。{latency_note}"
            ),
        },
        "first_pass_yield": {
            "value": round(accepted / total, 4),
            "accepted": accepted,
            "total": total,
            "proxy_for": "line_first_pass_yield",
            "basis": "直通率 proxy：审计放行占比（一次通过未被策略拒绝），数据源 recent_audits，非产线 MES 实测",
        },
        "defect_distribution": {
            "items": defects,
            "rejected": rejected,
            "total": total,
            "proxy_for": "quality_defect_pareto",
            "basis": "缺陷分布 proxy：被拒绝审计按 decision_reason 聚合（替代 reasons_json 维度，字段在 audits 表为 decision_reason）",
        },
        "energy_proxy": {
            "events_per_hour": events_per_hour,
            "total_events": total,
            "window_hours": window_hours,
            "proxy_for": "plant_energy_consumption",
            "basis": "能耗 proxy：审计事件密度（事件/小时），非电表 kWh 实测，仅反映活动强度",
        },
    }


def aggregate_kpis(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """多租户 KPI 面板：全局 + 按租户分组，附 unavailable 诚实清单。"""
    tenants: dict[str, list[dict[str, Any]]] = {}
    for row in audits:
        tenants.setdefault(str(row.get("tenant_id") or "default"), []).append(row)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "source": "recent_audits",
            "limit": AUDIT_SAMPLE_LIMIT,
            "records": len(audits),
        },
        "overall": _tenant_kpis(audits),
        "tenants": {tenant: _tenant_kpis(rows) for tenant, rows in sorted(tenants.items())},
        "unavailable": [
            ("harness_runs 延迟聚合：store 无公开的 harness_runs 查询方法（仅 append_harness_run 写入），"
            "OEE 性能腿退化为审计 payload latency 字段，无样本时 OEE 置 null"),
            "真实设备级 OEE / 电表能耗 / MES 直通率：需接入产线 PLC/SCADA/电表数据源，当前控制面无此数据",
        ],
    }


def bucket_timeseries(
    audits: list[dict[str, Any]],
    metric: str,
    hours: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """按分钟（≤24h）或小时（>24h）聚合审计事件计数，窗口零填充。"""
    if metric not in TIMESERIES_METRICS:
        raise HTTPException(status_code=400, detail=f"unsupported_metric:{metric}")
    hours = clamp_hours(hours)
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)
    bucket_seconds = 60 if hours <= 24 else 3600

    def _selected(row: dict[str, Any]) -> bool:
        accepted = bool(row.get("accepted"))
        if metric == "accepted_events":
            return accepted
        if metric == "rejected_events":
            return not accepted
        return True

    counters: dict[int, int] = {}
    for row in audits:
        ts = parse_ts(row.get("created_at"))
        if ts is None or ts < window_start or ts > now:
            continue
        if not _selected(row):
            continue
        key = int(ts.timestamp() // bucket_seconds)
        counters[key] = counters.get(key, 0) + 1

    first_bucket = int(window_start.timestamp() // bucket_seconds)
    last_bucket = int(now.timestamp() // bucket_seconds)
    points = [
        {
            "ts": datetime.fromtimestamp(bucket * bucket_seconds, tz=timezone.utc).isoformat(),
            "value": counters.get(bucket, 0),
        }
        for bucket in range(first_bucket, last_bucket + 1)
    ]
    return {
        "metric": metric,
        "hours": hours,
        "bucket_seconds": bucket_seconds,
        "points": points,
        "basis": f"recent_audits 时间戳按 {'分钟' if bucket_seconds == 60 else '小时'} 桶聚合，控制面事件 proxy",
    }


def routes(ctx: ControlPlaneContext) -> list:
    @get("/industrial/kpis", status_code=200, sync_to_thread=True)
    def industrial_kpis(request: Request) -> dict[str, Any]:
        ctx._require_auth(request)
        audits = ctx.store.recent_audits(limit=AUDIT_SAMPLE_LIMIT)
        return aggregate_kpis(audits)

    @get("/industrial/timeseries", status_code=200, sync_to_thread=True)
    def industrial_timeseries(
        request: Request,
        metric: str = "audit_events",
        hours: int = 24,
    ) -> dict[str, Any]:
        ctx._require_auth(request)
        if metric not in TIMESERIES_METRICS:
            raise HTTPException(status_code=400, detail=f"unsupported_metric:{metric}")
        audits = ctx.store.recent_audits(limit=AUDIT_SAMPLE_LIMIT)
        return bucket_timeseries(audits, metric, hours)

    return [industrial_kpis, industrial_timeseries]
