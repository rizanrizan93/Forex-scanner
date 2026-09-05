from __future__ import annotations

import os
from typing import Any

from .demo_adaptive_calibration_v2 import build_adaptive_calibration_v2_report
from .storage.supabase_operational import SupabaseOperationalStore

V2_WORKER = "ctrader_demo_adaptive_calibration_v2"
CLOSED_LIMIT = 500
SIGNAL_LIMIT = 1000
GEOMETRY_LIMIT = 1500


def _account_id() -> str:
    return str(
        os.getenv("CTRADER_ACCOUNT_ID")
        or os.getenv("CTRADER_TRADER_LOGIN")
        or ""
    ).strip()


def _closed_rows(store: SupabaseOperationalStore, *, account_id: str) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,code,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", account_id)
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(CLOSED_LIMIT)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _signal_context(store: SupabaseOperationalStore) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("signals")
        .select(
            "id,observed_at,symbol,direction,setup_type,final_score,"
            "h1_bias,h4_bias,entry_low,entry_high,sl,tp1,tp2,rr1,rr2"
        )
        .order("observed_at", desc=True)
        .limit(SIGNAL_LIMIT)
        .execute()
    )
    return {
        str(row.get("id")): dict(row)
        for row in (response.data or [])
        if row.get("id")
    }


def _geometry_context(
    store: SupabaseOperationalStore,
    *,
    account_id: str,
) -> dict[str, dict[str, Any]]:
    """Load immutable producer geometry keyed by scanner signal UUID.

    Geometry events are durable point-in-time evidence produced before broker
    submission. Joining them here enriches calibration without mutating historic
    closed-trade rows or coupling the execution hot path to v2.
    """
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", account_id)
        .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
        .order("observed_at", desc=True)
        .limit(GEOMETRY_LIMIT)
        .execute()
    )
    output: dict[str, dict[str, Any]] = {}
    for row in response.data or []:
        signal_id = str(row.get("signal_key") or "").strip()
        payload = row.get("payload")
        if signal_id and signal_id not in output and isinstance(payload, dict):
            output[signal_id] = dict(payload)
    return output


def _regime_proxy(signal: dict[str, Any]) -> str:
    direction = str(signal.get("direction", "") or "").upper()
    h1 = str(signal.get("h1_bias", "") or "").upper()
    h4 = str(signal.get("h4_bias", "") or "").upper()
    bullish = {"LONG", "BULL", "BULLISH", "UP", "UPTREND"}
    bearish = {"SHORT", "BEAR", "BEARISH", "DOWN", "DOWNTREND"}
    if direction == "LONG" and h1 in bullish and h4 in bullish:
        return "TREND"
    if direction == "SHORT" and h1 in bearish and h4 in bearish:
        return "TREND"
    if h1 and h4 and h1 == h4 and h1 not in bullish | bearish:
        return "RANGE"
    if h1 or h4:
        return "MIXED"
    return "UNKNOWN"


def _enrich_rows(
    rows: tuple[dict[str, Any], ...],
    signals: dict[str, dict[str, Any]],
    geometries: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = dict(item.get("payload")) if isinstance(item.get("payload"), dict) else {}
        signal_id = str(item.get("signal_key") or payload.get("signal_id") or "").strip()
        signal = signals.get(signal_id, {})
        geometry = geometries.get(signal_id, {})

        # Geometry is the preferred source for immutable point-in-time features.
        # Closed-trade fields always win when already present.
        for key, value in geometry.items():
            if payload.get(key) is None and value is not None:
                payload[key] = value

        # The durable signal row fills context that is not part of the geometry
        # event yet. This remains a read-time join; historical rows are untouched.
        for target, source in (
            ("symbol", "symbol"),
            ("direction", "direction"),
            ("setup_type", "setup_type"),
            ("final_score", "final_score"),
            ("entry_low", "entry_low"),
            ("entry_high", "entry_high"),
            ("planned_sl", "sl"),
            ("planned_tp1", "tp1"),
            ("planned_tp2", "tp2"),
            ("rr1", "rr1"),
            ("rr2", "rr2"),
        ):
            if payload.get(target) is None and signal.get(source) is not None:
                payload[target] = signal.get(source)

        if not str(payload.get("regime", "") or "").strip() and signal:
            payload["regime"] = _regime_proxy(signal)
        if signal:
            payload.setdefault("h1_bias", signal.get("h1_bias"))
            payload.setdefault("h4_bias", signal.get("h4_bias"))
        sources = ["DEMO_TRADE_CLOSED"]
        if geometry:
            sources.append("DEMO_SIGNAL_GEOMETRY")
        if signal:
            sources.append("SIGNALS")
        payload["v2_context_source"] = "+".join(sources)
        item["payload"] = payload
        enriched.append(item)
    return tuple(enriched)


def run() -> int:
    account_id = _account_id()
    if not account_id:
        raise SystemExit("CTRADER_DEMO_ADAPTIVE_V2_ACCOUNT_ID_MISSING")

    store = SupabaseOperationalStore.from_env()
    raw_rows = _closed_rows(store, account_id=account_id)
    signals = _signal_context(store)
    geometries = _geometry_context(store, account_id=account_id)
    rows = _enrich_rows(raw_rows, signals, geometries)
    report = build_adaptive_calibration_v2_report(rows)
    details = report.details()
    details.update(
        {
            "data_source": "DEMO_TRADE_CLOSED+DEMO_SIGNAL_GEOMETRY+SIGNALS",
            "closed_rows_scanned": len(raw_rows),
            "signal_context_rows": len(signals),
            "geometry_context_rows": len(geometries),
            "policy_effect": "SHADOW_ONLY",
            "risk_mutation": False,
            "sltp_mutation": False,
            "production_mutation": False,
            "live_unlock": False,
        }
    )
    store.write_heartbeat(
        V2_WORKER,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )

    print(
        "CTRADER_DEMO_ADAPTIVE_CALIBRATION_V2 "
        f"stage={report.stage} decisive={report.decisive} "
        f"snapshot_coverage={report.snapshot_coverage:.3f} "
        f"cohorts={len(report.cohorts)} diagnostics={len(report.diagnostics)} "
        f"geometry_rows={len(geometries)} "
        "policy=SHADOW_ONLY sltp_mutation=0 risk_mutation=0 production_mutation=0"
    )
    for item in report.diagnostics[:20]:
        print(
            "CTRADER_DEMO_ADAPTIVE_V2_DIAGNOSTIC "
            f"code={item.code} severity={item.severity} evidence={item.evidence_count} "
            f"scope={item.scope}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
