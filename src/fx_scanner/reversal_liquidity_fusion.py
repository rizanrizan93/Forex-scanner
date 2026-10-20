"""Read-only research rating from actual venue observations; never an order signal."""
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


def _result(state: str, reason: str, *, zone_id: str | None,
            source: str | None = None, evidence_at: str | None = None,
            index: float | None = None,
            components: Mapping[str, float] | None = None) -> dict[str, Any]:
    return {
        "contract": CONTRACT, "state": state, "reason": reason,
        "zone_id": zone_id, "source": source, "evidence_at": evidence_at,
        "support_index": index, "components": dict(components or {}),
        "probability": None, "win_rate": None, "execution_authority": False,
        "execution_influence": False, "research_only": True,
    }


def evaluate_zone_orderflow(
    zone: Mapping[str, Any], evidence: Mapping[str, Any] | None,
    *, symbol: str = "XAUUSD", now: datetime | str,
    max_age_seconds: float = 20.0,
) -> dict[str, Any]:
    """Compute an *uncalibrated ordinal* index from point-in-time evidence.

    Required: exact zone_id, symbol, venue-specific source, bounded UTC window,
    depth_updates, mapped_zone_overlap, directional depth_imbalance,
    near_wall_retention and near_wall_pull_ratio (for the supporting side).
    For CME/crypto, also require a historical-only price mapping residual.
    Broker Level-II never claims exchange traded volume, CVD or absorption.
    """
    zone_id = zone.get("zone_id")
    if not zone_id or zone.get("direction") not in {"BUY", "SELL"}:
        raise ValueError("zone_id and BUY/SELL required")
    if symbol not in SOURCE_BY_SYMBOL:
        raise ValueError("unsupported symbol")
    if not evidence:
        return _result("NO_DATA", "FEED_ORDERFLOW_BELUM_TERHUBUNG", zone_id=zone_id)
    source = str(evidence.get("source") or "")
    if source not in SOURCE_BY_SYMBOL[symbol] or evidence.get("symbol") != symbol:
        return _result("NO_DATA", "SUMBER_ATAU_INSTRUMEN_TIDAK_COCOK", zone_id=zone_id, source=source)
    if evidence.get("zone_id") != zone_id:
        return _result("NO_DATA", "ZONE_ID_TIDAK_COCOK", zone_id=zone_id, source=source)

    current = _time(now)
    start, end = _time(evidence.get("window_start")), _time(evidence.get("window_end"))
    available = _time(zone.get("available_at"))
    if start < available or end < start or end > current:
        return _result("NO_DATA", "URUTAN_WAKTU_TIDAK_KAUSAL", zone_id=zone_id, source=source)
    if not isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError("invalid age limit")
    if (current - end).total_seconds() > max_age_seconds:
        return _result("STALE", "ORDERFLOW_KEDALUWARSA", zone_id=zone_id, source=source,
                       evidence_at=end.isoformat())
    if evidence.get("mapped_zone_overlap") is not True:
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

    if _number(evidence, "depth_updates", 0.0, 1e9) < 5:
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
        if _number(evidence, "trade_count", 0.0, 1e9) >= 5:
            components["cvd"] = 14.0 * side * _number(evidence, "signed_cvd_change", -1.0, 1.0)
            components["absorption"] = 16.0 * side * _number(evidence, "signed_absorption", -1.0, 1.0)
        else:
            flow_present = False

    index = max(0.0, min(100.0, 50.0 + sum(components.values())))
    state = "SUPPORTIVE" if index >= 60 else "OPPOSING" if index <= 40 else "MIXED"
    reason = ("FLOW_AND_DEPTH" if flow_present else "DEPTH_ONLY") + "_UNCALIBRATED"
    return _result(state, reason, zone_id=zone_id,
                   source=source, evidence_at=end.isoformat(), index=round(index, 2),
                   components={k: round(v, 4) for k, v in components.items()})
