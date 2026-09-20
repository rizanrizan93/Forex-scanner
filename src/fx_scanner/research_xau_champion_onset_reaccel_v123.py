from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_causal_era_selector_v98 import (
    NORMAL_SCORE_THRESHOLD,
    build_causal_state_frame,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_v110_robustness_v111 import assemble_v110_selector

RESEARCH_VERSION = "XAU_CHAMPION_ONSET_REACCEL_V123"
ARTIFACT_CONTRACT = "XAU_CHAMPION_ONSET_REACCEL_V123_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False

ROUTES = ("DIRECTION_REACCEL", "COMPRESSED_REACCEL")
EVALUATION_START = datetime(2012, 1, 1, tzinfo=timezone.utc)


class _Asof:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.sort_values("available_at").reset_index(drop=True)
        self.times = [ensure_utc(x) for x in self.frame["available_at"]]

    def row(self, timestamp) -> Mapping[str, Any] | None:
        i = bisect_right(self.times, ensure_utc(timestamp)) - 1
        if i < 0:
            return None
        return self.frame.iloc[i].to_dict()


def _side_from_direction_state(value: Any) -> str | None:
    x = str(value or "").upper()
    if x == "BULL":
        return "LONG"
    if x == "BEAR":
        return "SHORT"
    return None


def _compressed_raw_matches(row: Mapping[str, Any], side: str) -> bool:
    raw = str(row.get("raw_state") or "")
    return (
        (side == "LONG" and raw == "BULL_COMPRESSED")
        or (side == "SHORT" and raw == "BEAR_COMPRESSED")
    )


def build_reaccel_route_frame(
    state_frame: pd.DataFrame,
    *,
    route_id: str,
) -> tuple[pd.DataFrame, tuple[dict[str, Any], ...]]:
    if route_id not in ROUTES:
        raise ValueError("V123_ROUTE_NOT_PREREGISTERED")

    x = state_frame.copy().sort_values("available_at").reset_index(drop=True)
    active_side: str | None = None
    active_start = None
    prev_side: str | None = None
    routed: list[str | None] = []
    epochs: list[dict[str, Any]] = []

    for _, row in x.iterrows():
        now = ensure_utc(row["available_at"])
        side = _side_from_direction_state(row.get("direction_state"))
        direction_transition = side is not None and side != prev_side

        if route_id == "DIRECTION_REACCEL":
            onset = direction_transition
        else:
            onset = direction_transition and _compressed_raw_matches(row, side)

        # Direction loss invalidates the existing epoch immediately at this
        # completed-D1 availability timestamp.
        if active_side is not None and side != active_side:
            epochs.append(
                {
                    "route_id": route_id,
                    "side": active_side,
                    "start": ensure_utc(active_start).isoformat(),
                    "end_exclusive": now.isoformat(),
                }
            )
            active_side = None
            active_start = None

        if active_side is None and onset:
            active_side = side
            active_start = now

        routed.append(active_side)
        prev_side = side

    if active_side is not None:
        epochs.append(
            {
                "route_id": route_id,
                "side": active_side,
                "start": ensure_utc(active_start).isoformat(),
                "end_exclusive": None,
            }
        )

    x[f"active_{route_id.lower()}"] = routed
    return x, tuple(epochs)


def route_v110_trades(
    trades: Sequence[TournamentTrade],
    *,
    route_frame: pd.DataFrame,
    route_id: str,
) -> tuple[TournamentTrade, ...]:
    col = f"active_{route_id.lower()}"
    if col not in route_frame:
        raise ValueError("V123_ROUTE_FRAME_COLUMN_MISSING")
    lookup = _Asof(route_frame)

    kept = []
    for trade in sorted(trades, key=lambda t: ensure_utc(t.entry_at)):
        # D1 entries occur at the next open after the signal-day close; for M15,
        # the latest completed D1 state is likewise the causal macro permission.
        row = lookup.row(trade.entry_at)
        if row is None:
            continue
        active = row.get(col)
        if active is None:
            continue
        if str(active).upper() == str(trade.direction).upper():
            kept.append(trade)
    return tuple(kept)


def _period(
    trades: Sequence[TournamentTrade],
    start,
    end,
) -> tuple[TournamentTrade, ...]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    return tuple(t for t in trades if a <= ensure_utc(t.entry_at) < b)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _epoch_period(
    epochs: Sequence[Mapping[str, Any]],
    start,
    end,
) -> tuple[dict[str, Any], ...]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    out = []
    for ep in epochs:
        s = ensure_utc(pd.Timestamp(ep["start"]).to_pydatetime())
        e = (
            b
            if ep.get("end_exclusive") is None
            else ensure_utc(pd.Timestamp(ep["end_exclusive"]).to_pydatetime())
        )
        if s < b and e > a:
            out.append(dict(ep))
    return tuple(out)


def _cash(
    trades: Sequence[TournamentTrade],
    *,
    bars: Sequence[Bar],
    start,
    end,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    a = ensure_utc(start)
    b = ensure_utc(end)
    vals = _period(trades, a, b)
    dates = _trading_dates(bars, start=a, end=b)
    return _cash_path_stopout_safe(
        vals,
        spec=broker_spec,
        tiers=leverage_tiers,
        account_leverage=100.0,
        stopout_pct=50.0,
        trading_dates=dates,
    )


def evaluate_v123(
    rows: Sequence[Bar],
    *,
    evaluation_end,
    pip_size: float,
    costs,
    broker_spec,
    leverage_tiers,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    end = ensure_utc(evaluation_end)
    state = build_causal_state_frame(bars)
    _, selector_all, _ = assemble_v110_selector(
        bars,
        costs=costs,
        pip_size=pip_size,
        evaluation_end=end,
    )

    windows = (
        ("2012_2018", datetime(2012, 1, 1, tzinfo=end.tzinfo), datetime(2019, 1, 1, tzinfo=end.tzinfo)),
        ("2019_2024", datetime(2019, 1, 1, tzinfo=end.tzinfo), datetime(2025, 1, 1, tzinfo=end.tzinfo)),
        ("2025_2026YTD", datetime(2025, 1, 1, tzinfo=end.tzinfo), end),
    )

    route_results: dict[str, Any] = {}
    for route_id in ROUTES:
        route_frame, epochs = build_reaccel_route_frame(state, route_id=route_id)
        routed_all = route_v110_trades(
            selector_all,
            route_frame=route_frame,
            route_id=route_id,
        )
        routed = _period(routed_all, EVALUATION_START, end)

        eras = {}
        for label, a, b in windows:
            vals = _period(routed_all, a, b)
            eps = _epoch_period(epochs, a, b)
            eras[label] = {
                "metrics": _metrics(vals),
                "fresh_100_cash": _cash(
                    routed_all,
                    bars=bars,
                    start=a,
                    end=b,
                    broker_spec=broker_spec,
                    leverage_tiers=leverage_tiers,
                ),
                "epoch_count": len(eps),
                "epochs": list(eps),
            }

        route_results[route_id] = {
            "full_metrics": _metrics(routed),
            "continuous_100_cash_2012_to_end": _cash(
                routed_all,
                bars=bars,
                start=EVALUATION_START,
                end=end,
                broker_spec=broker_spec,
                leverage_tiers=leverage_tiers,
            ),
            "eras": eras,
            "epoch_count_full": len(_epoch_period(epochs, EVALUATION_START, end)),
            "epochs_2024_onward": [
                ep
                for ep in epochs
                if ensure_utc(pd.Timestamp(ep["start"]).to_pydatetime())
                >= datetime(2024, 1, 1, tzinfo=end.tzinfo)
            ],
        }

    baseline = _period(selector_all, EVALUATION_START, end)
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "base_strategy": "exact frozen V110 selector",
            "routes_preregistered_before_results": list(ROUTES),
            "direction_reaccel": (
                "activate when completed-D1 direction_state changes into BULL/LONG "
                "or BEAR/SHORT; remain active only while that instantaneous direction persists"
            ),
            "compressed_reaccel": (
                "same transition, but onset is permitted only when frozen V98 raw_state "
                "is side-matched *_COMPRESSED; remain active while direction persists"
            ),
            "compressed_threshold_source": (
                f"frozen V98 NORMAL_SCORE_THRESHOLD={NORMAL_SCORE_THRESHOLD}; no V123 threshold search"
            ),
            "symmetry": "LONG/BULL and SHORT/BEAR identical",
            "market_data_availability": "completed D1 state available_at only",
            "calendar_year_used_for_routing": False,
            "future_trade_outcome_used_for_routing": False,
            "parameter_grid_search": False,
            "starting_balance_usd": 100.0,
            "account_leverage": 100.0,
            "lot": "fixed 0.01 via existing cash simulator",
            "risk_pct_filter": None,
            "broker_stopout_pct": 50.0,
            "otherwise": "CASH",
        },
        "baseline_v110_full_metrics": _metrics(baseline),
        "routes": route_results,
        "note": (
            "V123 is a historical hypothesis test, not a promotion candidate. It asks whether "
            "a simple causal D1 re-acceleration epoch can suppress hostile periods while retaining "
            "the early-2025 bootstrap. No route is selected or promoted by this experiment."
        ),
    }
