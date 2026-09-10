from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from .storage.supabase_operational import SupabaseOperationalStore

EVENT_TYPE = "DEMO_XAU_EXPANSION_CHALLENGER_SHADOW"
HEARTBEAT_NAME = "ctrader_demo_xau_expansion_challenger_shadow"
RULE_VERSION = "XAU_IMPULSE_RETEST_EXPANSION_SHADOW_V1"
MAX_ROWS = 500


@dataclass(frozen=True, slots=True)
class ChallengerDecision:
    active: bool
    score: float
    evidence: dict[str, Any]


def _text(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().upper()


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _directional_structure(row: Mapping[str, Any], direction: str) -> bool:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    return _text(row.get("bos")) == wanted or _text(row.get("mss")) == wanted


def _directional_displacement(row: Mapping[str, Any], direction: str) -> bool:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    return bool(row.get("displacement_valid")) and _text(row.get("displacement_direction")) == wanted


def _displacement_quality(row: Mapping[str, Any], direction: str) -> tuple[float | None, float | None]:
    if not _directional_displacement(row, direction):
        return None, None
    return _finite(row.get("displacement_range_atr_ratio")), _finite(row.get("displacement_body_ratio"))


def classify_snapshot(payload: Mapping[str, Any]) -> ChallengerDecision:
    """Classify one immutable feature snapshot without any execution authority.

    V1 is preregistered as a strict subset of IMPULSE_RETEST_V2:
    directional impulse + directional structure + controlled first retest remain
    mandatory. The challenger additionally requires a high-quality impulse and
    either aligned EMA expansion or dual-timeframe displacement. Session/regime
    are recorded as context only because the public holdout did not support
    making them universal hard filters.
    """

    symbol = _text(payload.get("symbol"))
    direction = _text(payload.get("direction"))
    m5 = _mapping(payload.get("structure_m5"))
    m15 = _mapping(payload.get("structure_m15"))
    ema_m5 = _mapping(payload.get("ema4_m5"))
    ema_m15 = _mapping(payload.get("ema4_m15"))

    m5_impulse = _directional_displacement(m5, direction)
    m15_impulse = _directional_displacement(m15, direction)
    impulse_present = m5_impulse or m15_impulse
    structure_present = _directional_structure(m5, direction) or _directional_structure(m15, direction)

    q5 = _displacement_quality(m5, direction)
    q15 = _displacement_quality(m15, direction)
    ranges = [value for value in (q5[0], q15[0]) if value is not None]
    bodies = [value for value in (q5[1], q15[1]) if value is not None]
    best_range_atr = max(ranges) if ranges else None
    best_body_atr = max(bodies) if bodies else None
    quality_impulse = bool(
        best_range_atr is not None
        and best_body_atr is not None
        and best_range_atr >= 1.20
        and best_body_atr >= 0.80
    )

    pullback_atr = _finite(payload.get("pullback_atr"))
    entry_mode = _text(payload.get("entry_mode"))
    controlled_retest = bool(
        pullback_atr is not None
        and 0.10 <= pullback_atr <= 1.25
        and any(token in entry_mode for token in ("PULLBACK", "RETRACE", "FVG"))
    )

    ema_release_m5 = bool(ema_m5.get("directional_aligned")) and _text(ema_m5.get("spread_state")) == "EXPANDING"
    ema_release_m15 = bool(ema_m15.get("directional_aligned")) and _text(ema_m15.get("spread_state")) == "EXPANDING"
    ema_release = ema_release_m5 or ema_release_m15
    dual_tf_impulse = m5_impulse and m15_impulse
    expansion_confirmed = ema_release or dual_tf_impulse

    base_required = bool(
        symbol == "XAUUSD"
        and direction in {"LONG", "SHORT"}
        and impulse_present
        and structure_present
        and controlled_retest
    )
    active = bool(base_required and quality_impulse and expansion_confirmed)

    score = 0.0
    score += 35.0 if base_required else 0.0
    score += 25.0 if quality_impulse else 0.0
    score += 20.0 if ema_release else 0.0
    score += 10.0 if dual_tf_impulse else 0.0
    session = _text(payload.get("session"))
    liquid_session = session in {"LONDON", "NEW_YORK", "LONDON_NY_OVERLAP", "LONDON_NEW_YORK_OVERLAP", "OVERLAP"}
    score += 5.0 if liquid_session else 0.0
    regime = _text(payload.get("regime"))
    score += 5.0 if regime in {"TRANSITION", "TREND_WEAK", "TREND_STRONG"} else 0.0
    score = max(0.0, min(100.0, score))

    evidence = {
        "rule_version": RULE_VERSION,
        "policy_effect": "OBSERVATION_ONLY",
        "execution_influence": False,
        "symbol": symbol,
        "direction": direction,
        "base_required": base_required,
        "impulse_present": impulse_present,
        "m5_directional_impulse": m5_impulse,
        "m15_directional_impulse": m15_impulse,
        "directional_structure": structure_present,
        "controlled_retest": controlled_retest,
        "pullback_atr": pullback_atr,
        "best_displacement_range_atr": best_range_atr,
        "best_displacement_body_atr": best_body_atr,
        "quality_impulse": quality_impulse,
        "ema_release": ema_release,
        "dual_tf_impulse": dual_tf_impulse,
        "expansion_confirmed": expansion_confirmed,
        "session": session,
        "liquid_session": liquid_session,
        "regime": regime,
    }
    return ChallengerDecision(active=active, score=score, evidence=evidence)


def _snapshot_rows(store: SupabaseOperationalStore) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,account_id,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", "DEMO_SIGNAL_FEATURE_SNAPSHOT_V2")
        .order("observed_at", desc=True)
        .limit(MAX_ROWS)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _existing_keys(store: SupabaseOperationalStore) -> set[str]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key")
        .eq("backend", "CTRADER")
        .eq("event_type", EVENT_TYPE)
        .order("observed_at", desc=True)
        .limit(MAX_ROWS)
        .execute()
    )
    return {str(row.get("signal_key") or "") for row in (response.data or []) if row.get("signal_key")}


def _closed_outcomes(store: SupabaseOperationalStore) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", "DEMO_TRADE_CLOSED")
        .order("observed_at", desc=True)
        .limit(MAX_ROWS)
        .execute()
    )
    outcomes: dict[str, dict[str, Any]] = {}
    for row in response.data or []:
        key = str(row.get("signal_key") or "")
        payload = row.get("payload")
        if key and isinstance(payload, dict) and key not in outcomes:
            outcomes[key] = dict(payload)
    return outcomes


def _is_reliable_outcome(payload: Mapping[str, Any]) -> bool:
    exit_type = _text(payload.get("exit_type"))
    if not exit_type or exit_type.startswith("MANUAL_CLOSE_") or bool(payload.get("partial_close")):
        return False
    return _finite(payload.get("net_pnl_estimate")) is not None


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    existing = _existing_keys(store)
    snapshots = _snapshot_rows(store)
    emitted = 0
    active_total = 0
    active_keys: set[str] = set()

    for row in reversed(snapshots):
        payload = row.get("payload")
        signal_key = str(row.get("signal_key") or "")
        if not signal_key or not isinstance(payload, dict):
            continue
        if _text(payload.get("symbol")) != "XAUUSD":
            continue
        decision = classify_snapshot(payload)
        if decision.active:
            active_total += 1
            active_keys.add(signal_key)
        if signal_key in existing:
            continue
        event_payload = dict(decision.evidence)
        event_payload.update({"score": decision.score, "active": decision.active, "source_snapshot": "DEMO_SIGNAL_FEATURE_SNAPSHOT_V2"})
        store.record_order_event(
            backend="CTRADER",
            account_id=str(row.get("account_id") or "UNKNOWN"),
            signal_key=signal_key,
            event_type=EVENT_TYPE,
            broker_order_id=f"EXPANSION_SHADOW:{signal_key}",
            accepted=True,
            code="ACTIVE" if decision.active else "INACTIVE",
            message="XAUUSD expansion challenger shadow classification",
            payload=event_payload,
        )
        emitted += 1

    outcomes = _closed_outcomes(store)
    decisive = wins = losses = 0
    realized_net = 0.0
    for signal_key in active_keys:
        outcome = outcomes.get(signal_key)
        if not outcome or not _is_reliable_outcome(outcome):
            continue
        net = _finite(outcome.get("net_pnl_estimate"))
        if net is None or abs(net) <= 0.01:
            continue
        decisive += 1
        wins += int(net > 0)
        losses += int(net < 0)
        realized_net += net

    win_rate = None if decisive == 0 else wins / decisive
    store.write_heartbeat(
        HEARTBEAT_NAME,
        healthy=True,
        lag_seconds=0.0,
        details={
            "rule_version": RULE_VERSION,
            "policy_effect": "OBSERVATION_ONLY",
            "execution_influence": False,
            "snapshot_rows_considered": len(snapshots),
            "shadow_rows_emitted": emitted,
            "active_snapshot_count": active_total,
            "active_decisive_closed": decisive,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "realized_net_pnl": realized_net,
            "outcome_contract": "DEMO_TRADE_CLOSED_RELIABLE_NONMANUAL_NET_PNL_SIGN",
        },
    )
    print(
        "CTRADER_DEMO_XAU_EXPANSION_CHALLENGER "
        f"version={RULE_VERSION} emitted={emitted} active={active_total} "
        f"decisive={decisive} wins={wins} losses={losses} "
        f"win_rate={'NONE' if win_rate is None else f'{win_rate:.4f}'} "
        f"realized_net={realized_net:.8g} policy=OBSERVATION_ONLY execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
