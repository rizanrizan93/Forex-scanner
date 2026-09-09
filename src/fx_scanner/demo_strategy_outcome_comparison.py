from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable

from .demo_adaptive_calibration_v2 import (
    SYSTEM_BREAKEVENS,
    SYSTEM_LOSSES,
    SYSTEM_WINS,
)
from .demo_adaptive_calibration_v2_runtime import (
    _account_ids,
    _closed_rows,
    _enrich_rows,
    _feature_snapshot_context,
    _geometry_context,
    _signal_context,
    _trajectory_context,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER = "ctrader_demo_strategy_outcome_comparison"
EMA_FAMILY = "FOUR_EMA_PULLBACK"
BASELINE_LABEL = "SMC_ICT_BASELINE_COMPARABLE"
EMA_ACTIVE_LABEL = "SMC_ICT_PLUS_FOUR_EMA_ACTIVE"
EMA_INACTIVE_LABEL = "SMC_ICT_FOUR_EMA_INACTIVE"


@dataclass(frozen=True, slots=True)
class OutcomeStats:
    closed: int
    decisive: int
    wins: int
    losses: int
    breakevens: int
    net_pnl: float
    r_count: int
    r_sum: float
    gross_positive_pnl: float
    gross_negative_pnl: float
    max_drawdown_r: float | None
    max_consecutive_losses: int
    mae_r_sum: float
    mae_r_count: int
    mfe_r_sum: float
    mfe_r_count: int

    @property
    def win_rate(self) -> float | None:
        return None if self.decisive <= 0 else self.wins / self.decisive

    @property
    def expectancy_r(self) -> float | None:
        return None if self.r_count <= 0 else self.r_sum / self.r_count

    @property
    def profit_factor(self) -> float | None:
        if self.gross_negative_pnl < -1e-12:
            return self.gross_positive_pnl / abs(self.gross_negative_pnl)
        if self.gross_positive_pnl > 0:
            return float("inf")
        return None

    @property
    def avg_mae_r(self) -> float | None:
        return None if self.mae_r_count <= 0 else self.mae_r_sum / self.mae_r_count

    @property
    def avg_mfe_r(self) -> float | None:
        return None if self.mfe_r_count <= 0 else self.mfe_r_sum / self.mfe_r_count

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.update(
            {
                "win_rate": self.win_rate,
                "expectancy_r": self.expectancy_r,
                "profit_factor": self.profit_factor,
                "avg_mae_r": self.avg_mae_r,
                "avg_mfe_r": self.avg_mfe_r,
            }
        )
        return value


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    return dict(value) if isinstance(value, dict) else {}


def _number(payload: dict[str, Any], key: str) -> float | None:
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _text(payload: dict[str, Any], key: str) -> str:
    return str(payload.get(key, "") or "").upper().strip()


def _observed_at(row: dict[str, Any]) -> datetime:
    raw = row.get("observed_at")
    if isinstance(raw, datetime):
        value = raw
    else:
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            value = datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _realized_r(payload: dict[str, Any]) -> float | None:
    direct = _number(payload, "realized_r")
    if direct is not None:
        return max(-10.0, min(10.0, direct))
    direction = _text(payload, "direction")
    entry_low = _number(payload, "entry_low")
    entry_high = _number(payload, "entry_high")
    stop = _number(payload, "planned_sl")
    exit_price = _number(payload, "exit_price")
    if (
        direction not in {"LONG", "SHORT"}
        or entry_low is None
        or entry_high is None
        or stop is None
        or exit_price is None
        or entry_low <= 0
        or entry_high < entry_low
    ):
        return None
    entry = (entry_low + entry_high) / 2.0
    risk = abs(entry - stop)
    if risk <= 1e-12:
        return None
    value = (exit_price - entry) / risk if direction == "LONG" else (entry - exit_price) / risk
    return max(-10.0, min(10.0, value)) if isfinite(value) else None


def _strategy_hypothesis(payload: dict[str, Any], family: str) -> dict[str, Any] | None:
    rows = payload.get("strategy_hypotheses")
    if not isinstance(rows, list):
        return None
    wanted = str(family).upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("family", "") or "").upper() == wanted:
            return dict(row)
    return None


def _comparable_four_ema(payload: dict[str, Any]) -> bool:
    try:
        version = int(payload.get("strategy_lab_version") or 0)
    except (TypeError, ValueError):
        version = 0
    hypothesis = _strategy_hypothesis(payload, EMA_FAMILY)
    return bool(
        version >= 2
        and hypothesis is not None
        and str(payload.get("ema4_policy_effect", "") or "").upper() == "OBSERVATION_ONLY"
    )


def _four_ema_active(payload: dict[str, Any]) -> bool:
    hypothesis = _strategy_hypothesis(payload, EMA_FAMILY)
    return bool(hypothesis and hypothesis.get("active") is True)


def _empty_stats() -> OutcomeStats:
    return OutcomeStats(
        closed=0,
        decisive=0,
        wins=0,
        losses=0,
        breakevens=0,
        net_pnl=0.0,
        r_count=0,
        r_sum=0.0,
        gross_positive_pnl=0.0,
        gross_negative_pnl=0.0,
        max_drawdown_r=None,
        max_consecutive_losses=0,
        mae_r_sum=0.0,
        mae_r_count=0,
        mfe_r_sum=0.0,
        mfe_r_count=0,
    )


def build_outcome_stats(rows: Iterable[dict[str, Any]]) -> OutcomeStats:
    ordered = sorted((dict(row) for row in rows), key=_observed_at)
    if not ordered:
        return _empty_stats()

    wins = losses = breakevens = 0
    net_pnl = 0.0
    r_values: list[float] = []
    gross_positive = 0.0
    gross_negative = 0.0
    max_loss_streak = current_loss_streak = 0
    mae_sum = mfe_sum = 0.0
    mae_count = mfe_count = 0

    equity_r = peak_r = 0.0
    maximum_drawdown = 0.0
    drawdown_observed = False

    for row in ordered:
        payload = _payload(row)
        exit_type = _text(payload, "exit_type")
        win = exit_type in SYSTEM_WINS
        loss = exit_type in SYSTEM_LOSSES
        breakeven = exit_type in SYSTEM_BREAKEVENS
        wins += int(win)
        losses += int(loss)
        breakevens += int(breakeven)

        pnl = _number(payload, "net_pnl_estimate")
        if pnl is None:
            pnl = 0.0
        net_pnl += pnl
        if pnl > 0:
            gross_positive += pnl
        elif pnl < 0:
            gross_negative += pnl

        realized_r = _realized_r(payload)
        if realized_r is not None:
            r_values.append(realized_r)
            equity_r += realized_r
            peak_r = max(peak_r, equity_r)
            maximum_drawdown = max(maximum_drawdown, peak_r - equity_r)
            drawdown_observed = True

        if loss:
            current_loss_streak += 1
            max_loss_streak = max(max_loss_streak, current_loss_streak)
        elif win or breakeven:
            current_loss_streak = 0

        mae = _number(payload, "mae_r")
        if mae is None:
            mae = _number(payload, "sampled_mae_r")
        if mae is not None:
            mae_sum += mae
            mae_count += 1
        mfe = _number(payload, "mfe_r")
        if mfe is None:
            mfe = _number(payload, "sampled_mfe_r")
        if mfe is not None:
            mfe_sum += mfe
            mfe_count += 1

    return OutcomeStats(
        closed=len(ordered),
        decisive=wins + losses,
        wins=wins,
        losses=losses,
        breakevens=breakevens,
        net_pnl=net_pnl,
        r_count=len(r_values),
        r_sum=sum(r_values),
        gross_positive_pnl=gross_positive,
        gross_negative_pnl=gross_negative,
        max_drawdown_r=maximum_drawdown if drawdown_observed else None,
        max_consecutive_losses=max_loss_streak,
        mae_r_sum=mae_sum,
        mae_r_count=mae_count,
        mfe_r_sum=mfe_sum,
        mfe_r_count=mfe_count,
    )


def build_strategy_outcome_report(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    all_rows = tuple(dict(row) for row in rows)
    comparable = tuple(row for row in all_rows if _comparable_four_ema(_payload(row)))
    ema_active = tuple(row for row in comparable if _four_ema_active(_payload(row)))
    ema_inactive = tuple(row for row in comparable if not _four_ema_active(_payload(row)))

    baseline = build_outcome_stats(comparable)
    active = build_outcome_stats(ema_active)
    inactive = build_outcome_stats(ema_inactive)

    delta_win_rate_pp = None
    if baseline.win_rate is not None and active.win_rate is not None:
        delta_win_rate_pp = 100.0 * (active.win_rate - baseline.win_rate)
    delta_expectancy_r = None
    if baseline.expectancy_r is not None and active.expectancy_r is not None:
        delta_expectancy_r = active.expectancy_r - baseline.expectancy_r
    delta_max_drawdown_r = None
    if baseline.max_drawdown_r is not None and active.max_drawdown_r is not None:
        delta_max_drawdown_r = active.max_drawdown_r - baseline.max_drawdown_r

    candidate_stage = "OBSERVE"
    if active.decisive >= 100:
        candidate_stage = "BOUNDED_POLICY_REVIEW"
    elif active.decisive >= 50:
        candidate_stage = "ROBUSTNESS_REVIEW"
    elif active.decisive >= 20:
        candidate_stage = "PATTERN_REVIEW"
    elif active.decisive >= 10:
        candidate_stage = "EARLY_COMPARISON"

    return {
        "mode": "DEMO_STRATEGY_OUTCOME_COMPARISON",
        "comparison_version": 1,
        "policy_effect": "SHADOW_ONLY",
        "production_mutation": False,
        "execution_mutation": False,
        "risk_mutation": False,
        "sltp_mutation": False,
        "candidate_family": EMA_FAMILY,
        "candidate_stage": candidate_stage,
        "minimum_decisive_for_early_comparison": 10,
        "minimum_decisive_for_policy_review": 100,
        "comparable_closed_rows": len(comparable),
        "legacy_or_noncomparable_closed_rows": len(all_rows) - len(comparable),
        "cohorts": {
            BASELINE_LABEL: baseline.payload(),
            EMA_ACTIVE_LABEL: active.payload(),
            EMA_INACTIVE_LABEL: inactive.payload(),
        },
        "candidate_uplift_vs_comparable_baseline": {
            "win_rate_delta_pp": delta_win_rate_pp,
            "expectancy_r_delta": delta_expectancy_r,
            "max_drawdown_r_delta": delta_max_drawdown_r,
        },
    }


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    account_ids = _account_ids(store)
    if not account_ids:
        raise SystemExit("CTRADER_DEMO_STRATEGY_OUTCOME_ACCOUNT_ID_MISSING")

    raw_rows = _closed_rows(store, account_ids=account_ids)
    rows = _enrich_rows(
        raw_rows,
        _signal_context(store),
        _geometry_context(store, account_ids=account_ids),
        _trajectory_context(store, account_ids=account_ids),
        _feature_snapshot_context(store, account_ids=account_ids),
    )
    report = build_strategy_outcome_report(rows)
    store.write_heartbeat(
        WORKER,
        healthy=True,
        lag_seconds=0.0,
        details=report,
    )

    baseline = report["cohorts"][BASELINE_LABEL]
    candidate = report["cohorts"][EMA_ACTIVE_LABEL]
    print(
        "CTRADER_DEMO_STRATEGY_OUTCOME_COMPARISON "
        f"comparable={report['comparable_closed_rows']} "
        f"candidate_stage={report['candidate_stage']} "
        f"baseline_decisive={baseline['decisive']} "
        f"ema_active_decisive={candidate['decisive']} "
        f"baseline_expectancy_r={baseline['expectancy_r']} "
        f"ema_expectancy_r={candidate['expectancy_r']} "
        "policy=SHADOW_ONLY execution_mutation=0 risk_mutation=0 sltp_mutation=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
