"""Pure, read-only research overlay for manual reversal zones.

Consumes *normalized, independently observed* order-flow facts only; it cannot
construct Bookmap data from OHLC or control orders. All weights are uncalibrated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

CONTRACT = "RIZAN_REVERSAL_LIQUIDITY_FUSION_RESEARCH_V1"
SOURCE_BY_SYMBOL = {
    "XAUUSD": frozenset({"CME_GC", "CTRADER_LEVEL_II"}),
    "EURUSD": frozenset({"CME_6E", "CTRADER_LEVEL_II"}),
    "BTCUSD": frozenset({"CRYPTO_SPOT", "CRYPTO_PERP", "CTRADER_LEVEL_II"}),
}


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp wajib ISO8601 / datetime")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp wajib memiliki timezone")
    return result.astimezone(timezone.utc)


def _number(evidence: Mapping[str, Any], key: str, lo: float, hi: float) -> float:
    raw = evidence.get(key)
    if isinstance(raw, bool):
        raise ValueError(f"{key} harus angka")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} tidak tersedia") from exc
    if not isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{key} di luar rentang")
    return value


def _result(state: str, reason: str, *, zone_id: str | None, source: str | None = None,
            evidence_at: str | None = None, index: float | None = None,
            components: Mapping[str, float] | None = None) -> dict[str, Any]:
    return {
        "contract": CONTRACT, "state": state, "reason": reason,
        "zone_id": zone_id, "source": source, "evidence_at": evidence_at,
        "support_index": index, "components": dict(components or {}),
        "probability": None, "win_rate": None, "execution_authority": False,
        "execution_influence": False, "research_only": True,
    }


def evaluate_zone_orderflow(zone: Mapping[str, Any], evidence: Mapping[str, Any] | None,
                            *, symbol: str = "XAUUSD", now: datetime | str,
                            max_age_seconds: float = 20.0) -> dict[str, Any]:
    """Return an *ordinal* support index, not entry permission or win probability.

    Evidence schema (already converted into target-CFD zone coordinates):
    zone_id, symbol, source, window_start, window_end, depth_updates,
    depth_imbalance [-1,1] (positive favors bids), near_wall_retention [0,1],
    near_wall_pull_ratio [0,1], mapped_zone_overlap bool.
    For non-broker feeds, also: mapping_error_atr [0,1] measured point-in-time.
    When both trades and depth are licensed/observed: trade_count,
    signed_cvd_change [-1,1], signed_absorption [-1,1] (positive favors BUY).
    A broker DOM-only payload may not claim trade-derived signals.
    """
    zone_id = zone.get("zone_id")
    if not zone_id or zone.get("direction") not in {"BUY", "SELL"}:
        raise ValueError("zona harus memiliki zone_id dan BUY/SELL")
    if symbol not in SOURCE_BY_SYMBOL:
        raise ValueError("simbol belum didukung")
    if not evidence:
        return _result("NO_DATA", "FEED_ORDERFLOW_BELUM_TERHUBUNG", zone_id=zone_id)
    source = str(evidence.get("source") or "")
    if source not in SOURCE_BY_SYMBOL[symbol] or evidence.get("symbol") != symbol:
        return _result("NO_DATA", "SUMBER_ATAU_INSTRUMEN_TIDAK_COCOK", zone_id=zone_id, source=source)
    if evidence.get("zone_id") != zone_id:
        return _result("NO_DATA", "ZONE_ID_TIDAK_COCOK", zone_id=zone_id, source=source)
    current = _time(now)
    start, end = _time(evidence.get("window_start")), _time(evidence.get("window_end"))
    # The source event must be available only after zone creation: no lookahead.
    zone_available = _time(zone.get("available_at"))
    if start < zone_available or end < start or end > current:
        return _result("NO_DATA", "URUTAN_WAKTU_TIDAK_KAUSAL", zone_id=zone_id, source=source)
    age = (current - end).total_seconds()
    if age > max_age_seconds:
        return _result("STALE", "ORDERFLOW_KEDALUWARSA", zone_id=zone_id,
                       source=source, evidence_at=end.isoformat())
    if not evidence.get("mapped_zone_overlap"):
        return _result("NO_DATA", "BUKTI_TIDAK_DI_ZONA", zone_id=zone_id,
                       source=source, evidence_at=end.isoformat())
    if source != "CTRADER_LEVEL_II":
        try:
            if _number(evidence, "mapping_error_atr", 0.0, 1.0) > 0.20:
                return _result("NO_DATA", "BASIS_FUTURES_CFD_TIDAK_PRESISI",
                               zone_id=zone_id, source=source, evidence_at=end.isoformat())
        except ValueError:
            return _result("NO_DATA", "MAPPING_HARGA_TIDAK_TERSEDIA",
                           zone_id=zone_id, source=source, evidence_at=end.isoformat())
    depth_updates = _number(evidence, "depth_updates", 0.0, 1_000_000_000.0)
    if depth_updates < 5:
        return _result("NO_DATA", "DEPTH_SAMPLE_TIDAK_CUKUP", zone_id=zone_id,
                       source=source, evidence_at=end.isoformat())
    imbalance = _number(evidence, "depth_imbalance", -1.0, 1.0)
    retention = _number(evidence, "near_wall_retention", 0.0, 1.0)
    pull = _number(evidence, "near_wall_pull_ratio", 0.0, 1.0)
    side = 1 if zone["direction"] == "BUY" else -1
    components = {
        "depth": 18.0 * side * imbalance,
        "retention": 8.0 * retention,
        "pull_penalty": -12.0 * pull,
    }
    flow_present = source != "CTRADER_LEVEL_II" and evidence.get("trade_count") is not None
    if flow_present:
        if _number(evidence, "trade_count", 0.0, 1_000_000_000.0) >= 5:
            components["cvd"] = 14.0 * side * _number(evidence, "signed_cvd_change", -1.0, 1.0)
            components["absorption"] = 16.0 * side * _number(evidence, "signed_absorption", -1.0, 1.0)
        else:
            flow_present = False
    index = max(0.0, min(100.0, 50.0 + sum(components.values())))
    state = "SUPPORTIVE" if index >= 60 else "OPPOSING" if index <= 40 else "MIXED"
    suffix = "FLOW_AND_DEPTH" if flow_present else "DEPTH_ONLY"
    return _result(state, suffix + "_UNCALIBRATED", zone_id=zone_id,
                   source=source, evidence_at=end.isoformat(), index=round(index, 2),
                   components={k: round(v, 4) for k, v in components.items()})
