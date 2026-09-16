from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping

from .demo_xau_m15_ema_reversal_recovery import STRATEGY_ID as EMA_STRATEGY_ID
from .demo_xau_m15_liquidity_sweep_fade import STRATEGY_ID as SWEEP_STRATEGY_ID
from .research_xau_m15_dual_strategy import MAX_HOLD_BARS, RESEARCH_VERSION

UTC = timezone.utc
AUTHORITY_CONTRACT = "XAU_M15_EVIDENCE_AUTHORITY_V1"
FORWARD_HOLD_BINDING_CONTRACT = "HISTORICAL_SELECTED_MAX_HOLD_V1"
HISTORICAL_WORKER = "ctrader_xau_m15_dual_strategy_research"
FORWARD_WORKERS = {
    EMA_STRATEGY_ID: "ctrader_demo_xau_m15_ema_reversal_forward_evidence",
    SWEEP_STRATEGY_ID: "ctrader_demo_xau_m15_liquidity_sweep_forward_evidence",
}
HISTORICAL_MAX_AGE = timedelta(hours=96)
FORWARD_MAX_AGE = timedelta(hours=36)
FUTURE_TOLERANCE = timedelta(minutes=5)
MIN_FORWARD_CLOSED_TRADES = 30
MIN_FORWARD_PROFIT_FACTOR = 1.15
MIN_FORWARD_EXPECTANCY_R = 0.0
MAX_FORWARD_DRAWDOWN_R = 8.0
FORWARD_PASS_STATE = "EVIDENCE_POSITIVE_REVIEW_CANDIDATE"


@dataclass(frozen=True, slots=True)
class EvidenceAuthorityDecision:
    strategy_id: str
    execution_authorized: bool
    lifecycle_stage: str
    reason: str
    historical_state: str
    forward_state: str
    selected_max_hold_bars: int | None = None
    forward_candidate_max_hold_bars: int | None = None
    historical_observed_at: str | None = None
    forward_observed_at: str | None = None
    forward_closed_trades: int | None = None
    forward_expectancy_r: float | None = None
    forward_profit_factor: float | None = None
    forward_max_drawdown_r: float | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "authority_contract": AUTHORITY_CONTRACT,
            **asdict(self),
            "environment": "DEMO",
            "live_execution_enabled": False,
        }


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _row_status(
    row: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    max_age: timedelta,
    label: str,
) -> tuple[bool, str, datetime | None, Mapping[str, Any]]:
    if not row:
        return False, f"{label}_MISSING", None, {}
    observed = _parse_timestamp(row.get("observed_at"))
    if observed is None:
        return False, f"{label}_TIMESTAMP_INVALID", None, {}
    now = as_of.astimezone(UTC)
    if observed > now + FUTURE_TOLERANCE:
        return False, f"{label}_TIMESTAMP_FUTURE", observed, {}
    if now - observed > max_age:
        return False, f"{label}_STALE", observed, {}
    if not bool(row.get("healthy")):
        return False, f"{label}_UNHEALTHY", observed, {}
    details = row.get("details")
    if not isinstance(details, Mapping):
        return False, f"{label}_DETAILS_INVALID", observed, {}
    return True, f"{label}_FRESH", observed, details


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def assess_xau_m15_evidence_authority(
    strategy_id: str,
    *,
    historical_row: Mapping[str, Any] | None,
    forward_row: Mapping[str, Any] | None,
    as_of: datetime | None = None,
) -> EvidenceAuthorityDecision:
    strategy = str(strategy_id).strip()
    if strategy not in FORWARD_WORKERS:
        return EvidenceAuthorityDecision(
            strategy, False, "SHADOW_ONLY", "STRATEGY_NOT_REGISTERED",
            "NOT_REGISTERED", "NOT_EVALUATED"
        )
    now = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    historical_ok, historical_state, historical_at, historical_details = _row_status(
        historical_row,
        as_of=now,
        max_age=HISTORICAL_MAX_AGE,
        label="HISTORICAL_EVIDENCE",
    )
    historical_at_iso = None if historical_at is None else historical_at.isoformat()
    if not historical_ok:
        return EvidenceAuthorityDecision(
            strategy, False, "SHADOW_ONLY", historical_state,
            historical_state, "NOT_EVALUATED",
            historical_observed_at=historical_at_iso,
        )
    if str(historical_details.get("research_version") or "") != RESEARCH_VERSION:
        return EvidenceAuthorityDecision(
            strategy, False, "SHADOW_ONLY", "HISTORICAL_CONTRACT_MISMATCH",
            "HISTORICAL_CONTRACT_MISMATCH", "NOT_EVALUATED",
            historical_observed_at=historical_at_iso,
        )
    decision = historical_details.get("decision")
    strategies = decision.get("strategies") if isinstance(decision, Mapping) else None
    if not isinstance(strategies, list):
        return EvidenceAuthorityDecision(
            strategy, False, "SHADOW_ONLY", "HISTORICAL_STRATEGY_EVIDENCE_MISSING",
            "HISTORICAL_STRATEGY_EVIDENCE_MISSING", "NOT_EVALUATED",
            historical_observed_at=historical_at_iso,
        )
    strategy_evidence = next(
        (
            row for row in strategies
            if isinstance(row, Mapping) and str(row.get("strategy_id") or "") == strategy
        ),
        None,
    )
    if not isinstance(strategy_evidence, Mapping):
        return EvidenceAuthorityDecision(
            strategy, False, "SHADOW_ONLY", "HISTORICAL_STRATEGY_EVIDENCE_MISSING",
            "HISTORICAL_STRATEGY_EVIDENCE_MISSING", "NOT_EVALUATED",
            historical_observed_at=historical_at_iso,
        )
    selected_hold = _int_or_none(strategy_evidence.get("selected_max_hold_bars"))
    historical_pass = bool(
        strategy_evidence.get("stage") == "FORWARD_SHADOW_ELIGIBLE"
        and strategy_evidence.get("development_pass") is True
        and strategy_evidence.get("holdout_opened") is True
        and strategy_evidence.get("holdout_pass") is True
        and selected_hold in MAX_HOLD_BARS
    )
    if not historical_pass:
        evidence_reason = str(
            strategy_evidence.get("reason") or strategy_evidence.get("stage") or "FAILED"
        )
        return EvidenceAuthorityDecision(
            strategy, False, "SHADOW_ONLY",
            f"HISTORICAL_GATE_NOT_PASSED:{evidence_reason}",
            "HISTORICAL_GATE_NOT_PASSED", "NOT_EVALUATED",
            selected_max_hold_bars=selected_hold,
            historical_observed_at=historical_at_iso,
        )

    forward_ok, forward_state, forward_at, forward_details = _row_status(
        forward_row,
        as_of=now,
        max_age=FORWARD_MAX_AGE,
        label="FORWARD_EVIDENCE",
    )
    forward_at_iso = None if forward_at is None else forward_at.isoformat()
    if not forward_ok:
        return EvidenceAuthorityDecision(
            strategy, False, "FORWARD_OBSERVATION", forward_state,
            "HISTORICAL_PASS", forward_state,
            selected_max_hold_bars=selected_hold,
            historical_observed_at=historical_at_iso,
            forward_observed_at=forward_at_iso,
        )
    if str(forward_details.get("strategy_id") or "") != strategy:
        return EvidenceAuthorityDecision(
            strategy, False, "FORWARD_OBSERVATION", "FORWARD_STRATEGY_MISMATCH",
            "HISTORICAL_PASS", "FORWARD_STRATEGY_MISMATCH",
            selected_max_hold_bars=selected_hold,
            historical_observed_at=historical_at_iso,
            forward_observed_at=forward_at_iso,
        )
    forward_hold = _int_or_none(forward_details.get("authority_candidate_max_hold_bars"))
    binding_contract = str(forward_details.get("authority_candidate_contract") or "")
    if (
        binding_contract != FORWARD_HOLD_BINDING_CONTRACT
        or forward_hold != selected_hold
        or forward_hold not in MAX_HOLD_BARS
    ):
        return EvidenceAuthorityDecision(
            strategy, False, "FORWARD_OBSERVATION", "FORWARD_MAX_HOLD_BINDING_MISMATCH",
            "HISTORICAL_PASS", "FORWARD_MAX_HOLD_BINDING_MISMATCH",
            selected_max_hold_bars=selected_hold,
            forward_candidate_max_hold_bars=forward_hold,
            historical_observed_at=historical_at_iso,
            forward_observed_at=forward_at_iso,
        )

    metrics = forward_details.get("metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
    closed = _int_or_none(metrics.get("closed_trades")) or 0
    expectancy = _float_or_none(metrics.get("expectancy_r"))
    pf = _float_or_none(metrics.get("profit_factor"))
    max_dd = _float_or_none(metrics.get("max_drawdown_r"))
    state = str(metrics.get("promotion_evidence_state") or "")
    forward_pass = bool(
        closed >= MIN_FORWARD_CLOSED_TRADES
        and state == FORWARD_PASS_STATE
        and expectancy is not None and expectancy > MIN_FORWARD_EXPECTANCY_R
        and pf is not None and pf >= MIN_FORWARD_PROFIT_FACTOR
        and max_dd is not None and max_dd <= MAX_FORWARD_DRAWDOWN_R
    )
    common = dict(
        selected_max_hold_bars=selected_hold,
        forward_candidate_max_hold_bars=forward_hold,
        historical_observed_at=historical_at_iso,
        forward_observed_at=forward_at_iso,
        forward_closed_trades=closed,
        forward_expectancy_r=expectancy,
        forward_profit_factor=pf,
        forward_max_drawdown_r=max_dd,
    )
    if not forward_pass:
        return EvidenceAuthorityDecision(
            strategy, False, "FORWARD_OBSERVATION",
            f"FORWARD_GATE_NOT_PASSED:{state or 'INSUFFICIENT'}",
            "HISTORICAL_PASS", "FORWARD_GATE_NOT_PASSED", **common,
        )
    return EvidenceAuthorityDecision(
        strategy, True, "DEMO_EXECUTION_AUTHORIZED",
        "HISTORICAL_AND_FORWARD_EVIDENCE_PASSED",
        "HISTORICAL_PASS", "FORWARD_PASS", **common,
    )


def _load_heartbeat(store: Any, worker_name: str) -> Mapping[str, Any] | None:
    try:
        response = (
            store.client.table("runtime_heartbeats")
            .select("worker_name,observed_at,healthy,details")
            .eq("worker_name", worker_name)
            .limit(2)
            .execute()
        )
        rows = list(response.data or [])
    except Exception:
        return None
    if len(rows) != 1:
        return None
    return dict(rows[0])


def resolve_xau_m15_evidence_authority(
    store: Any,
    strategy_id: str,
    *,
    as_of: datetime | None = None,
) -> EvidenceAuthorityDecision:
    strategy = str(strategy_id).strip()
    historical = _load_heartbeat(store, HISTORICAL_WORKER)
    forward_worker = FORWARD_WORKERS.get(strategy)
    forward = None if forward_worker is None else _load_heartbeat(store, forward_worker)
    return assess_xau_m15_evidence_authority(
        strategy,
        historical_row=historical,
        forward_row=forward,
        as_of=as_of,
    )
