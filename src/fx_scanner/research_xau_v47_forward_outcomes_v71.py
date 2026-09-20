from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import inf, isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import MAX_HOLD_BARS
from .research_xau_m15_dual_strategy_runtime import _fetch_history
from .research_xau_v47_forward_freeze_v69 import (
    FORWARD_CONTRACT,
    PROSPECTIVE_EPOCH,
    assess_forward_snapshot,
)
from .research_xau_v47_forward_observer_v70 import (
    EVENT_TYPE as EVALUATION_EVENT,
    RESEARCH_VERSION as V70_RESEARCH_VERSION,
    SYMBOL,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
RESEARCH_VERSION = "XAU_V47_FORWARD_OUTCOMES_V71"
ARTIFACT_CONTRACT = "XAU_V47_FORWARD_OUTCOMES_V71_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False
OUTCOME_EVENT = "DEMO_XAU_V47_FORWARD_OUTCOME"
WORKER_NAME = "ctrader_demo_xau_v47_forward_outcomes_v71"
HISTORY_BARS = 10_000


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    exit_at: datetime
    exit_price: float
    gross_r: float
    cost_r: float
    net_r: float
    mae_r: float
    mfe_r: float
    bars_held: int
    reason: str

    def payload(self) -> dict[str, Any]:
        return {
            "exit_at": self.exit_at.isoformat(),
            "exit_price": self.exit_price,
            "gross_r": self.gross_r,
            "cost_r": self.cost_r,
            "net_r": self.net_r,
            "mae_r": self.mae_r,
            "mfe_r": self.mfe_r,
            "bars_held": self.bars_held,
            "reason": self.reason,
        }


def _dt(value: Any) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return ensure_utc(stamp)


def _excursions(
    bars: Sequence[Bar],
    *,
    entry_price: float,
    risk_price: float,
    direction: str,
) -> tuple[float, float]:
    if not bars or risk_price <= 0.0:
        return 0.0, 0.0
    if direction == "LONG":
        adverse = [(float(row.low) - entry_price) / risk_price for row in bars]
        favorable = [(float(row.high) - entry_price) / risk_price for row in bars]
    else:
        adverse = [(entry_price - float(row.high)) / risk_price for row in bars]
        favorable = [(entry_price - float(row.low)) / risk_price for row in bars]
    return min(adverse), max(favorable)


def resolve_forward_outcome(
    bars: Sequence[Bar],
    *,
    evaluation: Mapping[str, Any],
) -> ForwardOutcome | None:
    direction = str(evaluation.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("V71_DIRECTION_INVALID")

    entry_at = _dt(evaluation["entry_at"])
    entry_price = float(evaluation["entry_price"])
    stop = float(evaluation["stop"])
    target = float(evaluation["target"])
    cost_r = float(evaluation["entry_friction_r"])
    if not all(isfinite(x) for x in (entry_price, stop, target, cost_r)):
        raise ValueError("V71_EVALUATION_NUMERIC_INVALID")
    if cost_r < 0.0:
        raise ValueError("V71_COST_R_INVALID")

    risk_price = (
        entry_price - stop
        if direction == "LONG"
        else stop - entry_price
    )
    if not isfinite(risk_price) or risk_price <= 0.0:
        raise ValueError("V71_RISK_INVALID")

    ordered = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    entry_index = next(
        (
            index
            for index, row in enumerate(ordered)
            if ensure_utc(row.timestamp) == entry_at
        ),
        None,
    )
    if entry_index is None:
        return None

    last_index = min(len(ordered) - 1, entry_index + MAX_HOLD_BARS)
    inspected: list[Bar] = []
    for index in range(entry_index, last_index + 1):
        bar = ordered[index]
        inspected.append(bar)
        if direction == "LONG":
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= stop
            target_hit = float(bar.low) <= target

        raw_target_hit = target_hit
        if index == entry_index:
            # Frozen V18/V47 execution model: target cannot complete on the
            # entry candle, while stop remains active immediately.
            target_hit = False

        bars_held = index - entry_index
        if stop_hit:
            mae_r, mfe_r = _excursions(
                inspected,
                entry_price=entry_price,
                risk_price=risk_price,
                direction=direction,
            )
            gross_r = -1.0
            return ForwardOutcome(
                exit_at=ensure_utc(bar.timestamp),
                exit_price=stop,
                gross_r=gross_r,
                cost_r=cost_r,
                net_r=gross_r - cost_r,
                mae_r=mae_r,
                mfe_r=mfe_r,
                bars_held=bars_held,
                reason=(
                    "STOP_FIRST_AMBIGUOUS"
                    if raw_target_hit
                    else "STOP_HIT"
                ),
            )
        if target_hit:
            mae_r, mfe_r = _excursions(
                inspected,
                entry_price=entry_price,
                risk_price=risk_price,
                direction=direction,
            )
            reward_r = float(evaluation["reward_r"])
            return ForwardOutcome(
                exit_at=ensure_utc(bar.timestamp),
                exit_price=target,
                gross_r=reward_r,
                cost_r=cost_r,
                net_r=reward_r - cost_r,
                mae_r=mae_r,
                mfe_r=mfe_r,
                bars_held=bars_held,
                reason="TARGET_HIT",
            )

    if entry_index + MAX_HOLD_BARS >= len(ordered):
        return None

    exit_bar = ordered[entry_index + MAX_HOLD_BARS]
    exit_price = float(exit_bar.close)
    gross_r = (
        (exit_price - entry_price) / risk_price
        if direction == "LONG"
        else (entry_price - exit_price) / risk_price
    )
    inspected = list(ordered[entry_index: entry_index + MAX_HOLD_BARS + 1])
    mae_r, mfe_r = _excursions(
        inspected,
        entry_price=entry_price,
        risk_price=risk_price,
        direction=direction,
    )
    return ForwardOutcome(
        exit_at=ensure_utc(exit_bar.timestamp),
        exit_price=exit_price,
        gross_r=gross_r,
        cost_r=cost_r,
        net_r=gross_r - cost_r,
        mae_r=mae_r,
        mfe_r=mfe_r,
        bars_held=MAX_HOLD_BARS,
        reason="TIME_EXIT",
    )


def summarize_outcomes(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("exit_at") or ""))
    values = [float(row["net_r"]) for row in ordered]
    n = len(values)
    if n == 0:
        return {
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "profit_factor": None,
            "profit_factor_infinite": False,
            "expectancy_r": None,
            "net_r": 0.0,
            "max_drawdown_r": 0.0,
        }

    wins = sum(value > 0.0 for value in values)
    losses = sum(value < 0.0 for value in values)
    gross_profit = sum(value for value in values if value > 0.0)
    gross_loss = -sum(value for value in values if value < 0.0)
    profit_factor_infinite = bool(gross_loss <= 0.0 and gross_profit > 0.0)
    if gross_loss <= 0.0:
        profit_factor = None
    else:
        profit_factor = gross_profit / gross_loss

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "closed_trades": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / float(n),
        "profit_factor": profit_factor,
        "profit_factor_infinite": profit_factor_infinite,
        "expectancy_r": sum(values) / float(n),
        "net_r": sum(values),
        "max_drawdown_r": max_dd,
    }


def _evaluation_rows(store: Any) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,observed_at,payload")
        .eq("event_type", EVALUATION_EVENT)
        .eq("code", V70_RESEARCH_VERSION)
        .order("observed_at", desc=False)
        .limit(5000)
        .execute()
    )
    selected: list[dict[str, Any]] = []
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        signal_at_raw = payload.get("signal_at")
        if not signal_at_raw:
            continue
        if _dt(signal_at_raw) < PROSPECTIVE_EPOCH:
            continue
        if not bool(payload.get("v47_approved")):
            continue
        group = str(payload.get("primary_forward_group") or "")
        if group not in {"SWEEP", "NON_SWEEP"}:
            continue
        selected.append(
            {
                "signal_key": str(row["signal_key"]),
                "observed_at": str(row["observed_at"]),
                "payload": payload,
            }
        )
    return tuple(selected)


def _existing_outcomes(store: Any) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,observed_at,payload")
        .eq("event_type", OUTCOME_EVENT)
        .eq("code", RESEARCH_VERSION)
        .order("observed_at", desc=False)
        .limit(5000)
        .execute()
    )
    return {
        str(row["signal_key"]): dict(row.get("payload") or {})
        for row in (response.data or [])
    }


def _metrics_from_outcomes(
    outcomes: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    primary = [
        payload
        for payload in outcomes.values()
        if str(payload.get("primary_forward_group")) == "SWEEP"
    ]
    reference = [
        payload
        for payload in outcomes.values()
        if str(payload.get("primary_forward_group")) == "NON_SWEEP"
    ]
    return summarize_outcomes(primary), summarize_outcomes(reference)


def _effective_pf(metrics: Mapping[str, Any]) -> float | None:
    if bool(metrics.get("profit_factor_infinite")):
        return inf
    value = metrics.get("profit_factor")
    return None if value is None else float(value)


def _assessment(
    primary: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    return assess_forward_snapshot(
        primary_closed_trades=int(primary["closed_trades"]),
        reference_closed_trades=int(reference["closed_trades"]),
        primary_profit_factor=_effective_pf(primary),
        reference_profit_factor=_effective_pf(reference),
        primary_expectancy_r=primary["expectancy_r"],
        reference_expectancy_r=reference["expectancy_r"],
        primary_net_r=float(primary["net_r"]),
        primary_max_drawdown_r=float(primary["max_drawdown_r"]),
        reference_max_drawdown_r=float(reference["max_drawdown_r"]),
    )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V71_CTRADER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V71_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("V71_XAU_NOT_CONFIGURED")

    store = SupabaseOperationalStore.from_env()
    evaluations = _evaluation_rows(store)
    existing = _existing_outcomes(store)

    as_of = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=HISTORY_BARS, as_of=as_of)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    account = (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )
    if not account:
        raise SystemExit("V71_CTRADER_ACCOUNT_LABEL_REQUIRED")

    resolved_new = 0
    unresolved = 0
    for row in evaluations:
        signal_key = str(row["signal_key"])
        if signal_key in existing:
            continue
        evaluation = dict(row["payload"])
        outcome = resolve_forward_outcome(bars, evaluation=evaluation)
        if outcome is None:
            unresolved += 1
            continue
        payload = {
            "source_contract": "XAU_V47_FORWARD_OBSERVER_V70_EVIDENCE_1",
            "forward_contract": FORWARD_CONTRACT,
            "prospective_epoch": PROSPECTIVE_EPOCH.isoformat(),
            "primary_forward_group": str(evaluation["primary_forward_group"]),
            "family": str(evaluation["family"]),
            "variant_id": str(evaluation["variant_id"]),
            "signal_at": str(evaluation["signal_at"]),
            "entry_at": str(evaluation["entry_at"]),
            "entry_price": float(evaluation["entry_price"]),
            "stop": float(evaluation["stop"]),
            "target": float(evaluation["target"]),
            "reward_r": float(evaluation["reward_r"]),
            "entry_friction_r": float(evaluation["entry_friction_r"]),
            **outcome.payload(),
            "execution_influence": False,
            "promotion_authority": False,
            "live_money": False,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        }
        store.record_order_event(
            backend="CTRADER",
            account_id=account,
            signal_key=signal_key,
            broker_order_id=None,
            event_type=OUTCOME_EVENT,
            accepted=None,
            code=RESEARCH_VERSION,
            message="Prospective XAU V47 paper outcome; no broker action",
            payload=payload,
        )
        existing[signal_key] = payload
        resolved_new += 1

    primary, reference = _metrics_from_outcomes(existing)
    assessment = _assessment(primary, reference)
    details = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "observed_at": as_of.isoformat(),
        "prospective_epoch": PROSPECTIVE_EPOCH.isoformat(),
        "evaluations_seen": len(evaluations),
        "resolved_new": resolved_new,
        "unresolved": unresolved,
        "closed_outcomes_total": len(existing),
        "primary_sweep": primary,
        "reference_non_sweep": reference,
        "assessment": assessment,
        "history_bars": len(bars),
        "history_pages": pages,
        "storage_table": "broker_order_events",
        "outcome_event_type": OUTCOME_EVENT,
    }
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )

    path = Path(
        os.getenv(
            "V71_EVIDENCE_OUTPUT",
            "artifacts/xau-v47-forward-outcomes-v71.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n"
    )
    print(
        "V71_FORWARD_OUTCOMES "
        f"evaluations={len(evaluations)} new={resolved_new} unresolved={unresolved} "
        f"closed={len(existing)} sweep_n={primary['closed_trades']} "
        f"nonsweep_n={reference['closed_trades']} "
        f"decision={assessment['decision']} artifact={path} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
