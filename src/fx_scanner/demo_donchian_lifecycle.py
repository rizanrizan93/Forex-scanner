from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .demo_donchian_adaptive_tournament import DonchianVariant
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
TOURNAMENT_WORKER = "ctrader_demo_donchian_adaptive_tournament"
FREEZE_EVENT = "DEMO_DONCHIAN_CANDIDATE_FROZEN"
DEMOTION_EVENT = "DEMO_DONCHIAN_CANDIDATE_DEMOTED"
PROMOTION_STATE_EVENT = "DEMO_DONCHIAN_PROMOTION_STATE"
MIN_FORWARD_DECISIVE = 100
MIN_FORWARD_REVIEW = 30


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    strategy_id: str
    variant: DonchianVariant
    frozen_at: datetime
    historical_decision: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "params": asdict(self.variant),
            "frozen_at": self.frozen_at.isoformat(),
            "historical_decision": dict(self.historical_decision),
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
        }


def _parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _account_id() -> str:
    return str(os.getenv("CTRADER_ACCOUNT_ID") or os.getenv("CTRADER_TRADER_LOGIN") or "UNKNOWN")


def _latest_event(store: SupabaseOperationalStore, event_type: str) -> dict[str, Any] | None:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", event_type)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return None if not rows else dict(rows[0])


def active_frozen_candidate(store: SupabaseOperationalStore) -> FrozenCandidate | None:
    freeze = _latest_event(store, FREEZE_EVENT)
    if not freeze or not isinstance(freeze.get("payload"), Mapping):
        return None
    payload = dict(freeze["payload"])
    strategy_id = str(payload.get("strategy_id") or "").strip()
    params = payload.get("params")
    if not strategy_id or not isinstance(params, Mapping):
        return None
    frozen_at = _parse_time(payload.get("frozen_at") or freeze.get("observed_at"))

    demotion = _latest_event(store, DEMOTION_EVENT)
    if demotion and isinstance(demotion.get("payload"), Mapping):
        demotion_payload = dict(demotion["payload"])
        if (
            str(demotion_payload.get("strategy_id") or "") == strategy_id
            and _parse_time(demotion.get("observed_at")) >= frozen_at
        ):
            return None

    variant = DonchianVariant(
        int(params["lookback"]),
        int(params["atr_period"]),
        float(params["buffer_atr"]),
    )
    if variant.strategy_id != strategy_id:
        return None
    return FrozenCandidate(
        strategy_id=strategy_id,
        variant=variant,
        frozen_at=frozen_at,
        historical_decision=dict(payload.get("historical_decision") or {}),
    )


def _latest_tournament_details(store: SupabaseOperationalStore) -> dict[str, Any] | None:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", TOURNAMENT_WORKER)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if len(rows) != 1 or not bool(rows[0].get("healthy")):
        return None
    details = rows[0].get("details")
    if not isinstance(details, Mapping):
        return None
    return {"observed_at": rows[0].get("observed_at"), **dict(details)}


def freeze_latest_eligible_candidate(store: SupabaseOperationalStore) -> FrozenCandidate | None:
    existing = active_frozen_candidate(store)
    if existing is not None:
        return existing
    tournament = _latest_tournament_details(store)
    if tournament is None:
        return None
    decision = tournament.get("decision")
    if not isinstance(decision, Mapping) or str(decision.get("stage")) != "FORWARD_SHADOW_ELIGIBLE":
        return None
    strategy_id = str(decision.get("selected_strategy_id") or "").strip()
    params = decision.get("selected_params")
    if not strategy_id or not isinstance(params, Mapping):
        return None
    variant = DonchianVariant(
        int(params["lookback"]),
        int(params["atr_period"]),
        float(params["buffer_atr"]),
    )
    if variant.strategy_id != strategy_id:
        return None
    frozen_at = _parse_time(tournament["observed_at"])
    candidate = FrozenCandidate(strategy_id, variant, frozen_at, dict(decision))
    store.record_order_event(
        backend="CTRADER",
        account_id=_account_id(),
        signal_key=f"DONCHIAN_FREEZE:{strategy_id}:{frozen_at.isoformat()}",
        event_type=FREEZE_EVENT,
        broker_order_id=f"DONCHIAN_FREEZE:{strategy_id}",
        accepted=True,
        code="FORWARD_SHADOW",
        message="Donchian candidate frozen after historical walk-forward and stability gates",
        payload=candidate.payload(),
    )
    return candidate


def promotion_state(
    *,
    candidate: FrozenCandidate,
    forward_metrics: Mapping[str, Any],
    stress_acceptance: Mapping[str, Any],
    drawdown_limit_r: float,
) -> dict[str, Any]:
    decisive = int(forward_metrics.get("completed_trades") or 0)
    win_rate = forward_metrics.get("win_rate")
    profit_factor = forward_metrics.get("profit_factor")
    expectancy = forward_metrics.get("expectancy_r")
    drawdown = forward_metrics.get("max_drawdown_r")
    metrics_pass = bool(
        win_rate is not None
        and float(win_rate) >= float(stress_acceptance["win_rate_min"])
        and profit_factor is not None
        and float(profit_factor) >= float(stress_acceptance["profit_factor_min"])
        and expectancy is not None
        and float(expectancy) >= float(stress_acceptance["expectancy_r_min"])
        and drawdown is not None
        and float(drawdown) <= float(drawdown_limit_r)
    )
    if decisive < MIN_FORWARD_REVIEW:
        state = "FORWARD_SHADOW_COLLECTING"
    elif decisive < MIN_FORWARD_DECISIVE:
        state = "FORWARD_SHADOW_PROVISIONAL"
    elif metrics_pass:
        state = "DEMO_LIMITED_PROMOTION_ELIGIBLE"
    else:
        state = "FORWARD_SHADOW_FAILED"
    return {
        "strategy_id": candidate.strategy_id,
        "state": state,
        "forward_decisive": decisive,
        "minimum_forward_review": MIN_FORWARD_REVIEW,
        "minimum_forward_decisive": MIN_FORWARD_DECISIVE,
        "metrics_pass": metrics_pass,
        "forward_metrics": dict(forward_metrics),
        "stress_acceptance": dict(stress_acceptance),
        "drawdown_limit_r": float(drawdown_limit_r),
        "execution_influence": False,
        "policy_effect": "LIFECYCLE_ONLY",
    }


def demotion_required(
    *,
    state: Mapping[str, Any],
    recent_metrics: Mapping[str, Any],
    minimum_recent_trades: int = 30,
) -> bool:
    if str(state.get("state") or "") != "DEMO_LIMITED_PROMOTION_ELIGIBLE":
        return False
    completed = int(recent_metrics.get("completed_trades") or 0)
    if completed < minimum_recent_trades:
        return False
    expectancy = recent_metrics.get("expectancy_r")
    profit_factor = recent_metrics.get("profit_factor")
    return bool(
        expectancy is None
        or float(expectancy) < 0.0
        or profit_factor is None
        or float(profit_factor) < 0.90
    )
