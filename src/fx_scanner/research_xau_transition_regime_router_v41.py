from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    L12_ID,
    L20_ID,
    MARGIN_FLOOR_PCT,
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    annotate_m15,
    build_d1_context,
    build_h1_context,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    M15_VARIANTS,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_TRANSITION_REGIME_ROUTER_V41"
ARTIFACT_CONTRACT = "XAU_TRANSITION_REGIME_ROUTER_V41_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

DISPLACEMENT_BODY_ATR = 0.75
VOL_EXPANSION_MULTIPLIER = 1.10
VOL_BASELINE_DAYS = 60

ROUTES = (
    "POSTFLIP_L12_L20_5D_NORMAL",
    "POSTFLIP_PHASED_20D_NORMAL",
    "POSTFLIP_PHASED_20D_STRICT",
    "POSTFLIP_3OF5_PHASED_20D_NORMAL",
    "POSTFLIP_4OF5_PHASED_20D_NORMAL",
    "POSTFLIP_3OF5_L12_5D_NORMAL",
)


def build_transition_context(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = build_d1_context(rows).copy()
    d1["body"] = d1["close"] - d1["open"]
    d1["body_atr"] = d1["body"].abs() / d1["atr14"].replace(0.0, np.nan)
    d1["atr14_prior_median60"] = (
        d1["atr14"].shift(1).rolling(VOL_BASELINE_DAYS, min_periods=40).median()
    )
    d1["vol_expansion"] = (
        d1["atr14"] >= VOL_EXPANSION_MULTIPLIER * d1["atr14_prior_median60"]
    )

    prev_close = d1["close"].shift(1)
    prev_ema = d1["ema200"].shift(1)
    prev_ret60 = d1["ret60"].shift(1)
    prev_slope = d1["ema200_slope20"].shift(1)

    d1["bull_ema_reclaim"] = (d1["close"] > d1["ema200"]) & (prev_close <= prev_ema)
    d1["bear_ema_loss"] = (d1["close"] < d1["ema200"]) & (prev_close >= prev_ema)
    d1["bull_momentum_flip"] = (d1["ret60"] > 0.0) & (prev_ret60 <= 0.0)
    d1["bear_momentum_flip"] = (d1["ret60"] < 0.0) & (prev_ret60 >= 0.0)
    d1["bull_slope_flip"] = (d1["ema200_slope20"] > 0.0) & (prev_slope <= 0.0)
    d1["bear_slope_flip"] = (d1["ema200_slope20"] < 0.0) & (prev_slope >= 0.0)
    d1["bull_displacement"] = (d1["body"] > 0.0) & (d1["body_atr"] >= DISPLACEMENT_BODY_ATR)
    d1["bear_displacement"] = (d1["body"] < 0.0) & (d1["body_atr"] >= DISPLACEMENT_BODY_ATR)

    origin_side = 0
    transition_open = False
    transition_days = 0
    bull_flags = {"ema": False, "mom": False, "slope": False, "disp": False, "vol": False}
    bear_flags = {"ema": False, "mom": False, "slope": False, "disp": False, "vol": False}
    confirmed_side = 0
    post_flip_age = 0
    confirmation_score = 0
    confirmation_transition_days = 0

    transition_origin: list[int] = []
    transition_age: list[int] = []
    confirmed_from_side: list[int] = []
    post_age: list[int] = []
    score: list[int] = []
    confirm_days: list[int] = []

    last_nonzero = 0

    for _, row in d1.iterrows():
        side = int(row["regime_side"])

        if side == 0:
            if not transition_open and last_nonzero != 0:
                transition_open = True
                origin_side = last_nonzero
                transition_days = 1
                bull_flags = {"ema": False, "mom": False, "slope": False, "disp": False, "vol": False}
                bear_flags = {"ema": False, "mom": False, "slope": False, "disp": False, "vol": False}
            elif transition_open:
                transition_days += 1

            if transition_open:
                bull_flags["ema"] |= bool(row["bull_ema_reclaim"])
                bull_flags["mom"] |= bool(row["bull_momentum_flip"])
                bull_flags["slope"] |= bool(row["bull_slope_flip"])
                bull_flags["disp"] |= bool(row["bull_displacement"])
                bull_flags["vol"] |= bool(row["vol_expansion"])
                bear_flags["ema"] |= bool(row["bear_ema_loss"])
                bear_flags["mom"] |= bool(row["bear_momentum_flip"])
                bear_flags["slope"] |= bool(row["bear_slope_flip"])
                bear_flags["disp"] |= bool(row["bear_displacement"])
                bear_flags["vol"] |= bool(row["vol_expansion"])

            confirmed_side = 0
            post_flip_age = 0
            confirmation_score = 0
            confirmation_transition_days = 0

        else:
            if transition_open:
                bull_flags["ema"] |= bool(row["bull_ema_reclaim"])
                bull_flags["mom"] |= bool(row["bull_momentum_flip"])
                bull_flags["slope"] |= bool(row["bull_slope_flip"])
                bull_flags["disp"] |= bool(row["bull_displacement"])
                bull_flags["vol"] |= bool(row["vol_expansion"])
                bear_flags["ema"] |= bool(row["bear_ema_loss"])
                bear_flags["mom"] |= bool(row["bear_momentum_flip"])
                bear_flags["slope"] |= bool(row["bear_slope_flip"])
                bear_flags["disp"] |= bool(row["bear_displacement"])
                bear_flags["vol"] |= bool(row["vol_expansion"])

                if origin_side != 0 and side == -origin_side:
                    confirmed_side = side
                    post_flip_age = 1
                    confirmation_transition_days = transition_days
                    flags = bull_flags if side > 0 else bear_flags
                    confirmation_score = sum(int(v) for v in flags.values())
                else:
                    confirmed_side = 0
                    post_flip_age = 0
                    confirmation_score = 0
                    confirmation_transition_days = 0

                transition_open = False
                transition_days = 0
                origin_side = 0
            elif confirmed_side == side and confirmed_side != 0:
                post_flip_age += 1
            else:
                confirmed_side = 0
                post_flip_age = 0
                confirmation_score = 0
                confirmation_transition_days = 0

            last_nonzero = side

        transition_origin.append(origin_side if transition_open else 0)
        transition_age.append(transition_days if transition_open else 0)
        confirmed_from_side.append(-confirmed_side if confirmed_side != 0 else 0)
        post_age.append(post_flip_age)
        score.append(confirmation_score)
        confirm_days.append(confirmation_transition_days)

    d1["transition_origin_side"] = transition_origin
    d1["transition_age_days"] = transition_age
    d1["confirmed_from_side"] = confirmed_from_side
    d1["post_flip_age_days"] = post_age
    d1["transition_confirmation_score"] = score
    d1["confirmation_transition_days"] = confirm_days
    return d1


def annotate_transition_m15(
    trades: Sequence[TournamentTrade],
    *,
    transition_context: pd.DataFrame,
    h1_context: pd.DataFrame,
) -> tuple[dict[str, Any], ...]:
    base = annotate_m15(
        trades,
        d1_context=transition_context,
        h1_context=h1_context,
    )
    lookup = _Asof(transition_context)
    out: list[dict[str, Any]] = []
    for row in base:
        d1 = lookup.row(row["trade"].signal_at)
        if d1 is None:
            continue
        enriched = dict(row)
        enriched.update(
            {
                "post_flip_age_days": int(d1.get("post_flip_age_days") or 0),
                "transition_confirmation_score": int(
                    d1.get("transition_confirmation_score") or 0
                ),
                "confirmation_transition_days": int(
                    d1.get("confirmation_transition_days") or 0
                ),
                "confirmed_from_side": int(d1.get("confirmed_from_side") or 0),
            }
        )
        out.append(enriched)
    return tuple(out)


def _select(
    annotated: Sequence[Mapping[str, Any]],
    route: str,
) -> tuple[TournamentTrade, ...]:
    selected: list[TournamentTrade] = []
    for row in annotated:
        family = str(row["family"])
        age = int(row["post_flip_age_days"])
        quality = int(row["transition_confirmation_score"])
        d1_match = bool(row["d1_match"])
        normal = bool(row["h1_normal"])
        strict = bool(row["h1_strict"])

        keep = False
        if route == "POSTFLIP_L12_L20_5D_NORMAL":
            keep = d1_match and normal and 1 <= age <= 5 and family in {"L12", "L20"}
        elif route == "POSTFLIP_PHASED_20D_NORMAL":
            keep = (
                d1_match
                and normal
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        elif route == "POSTFLIP_PHASED_20D_STRICT":
            keep = (
                d1_match
                and strict
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        elif route == "POSTFLIP_3OF5_PHASED_20D_NORMAL":
            keep = (
                quality >= 3
                and d1_match
                and normal
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        elif route == "POSTFLIP_4OF5_PHASED_20D_NORMAL":
            keep = (
                quality >= 4
                and d1_match
                and normal
                and (
                    (1 <= age <= 5 and family in {"L12", "L20"})
                    or (6 <= age <= 20 and family == "L20")
                )
            )
        elif route == "POSTFLIP_3OF5_L12_5D_NORMAL":
            keep = (
                quality >= 3
                and d1_match
                and normal
                and 1 <= age <= 5
                and family == "L12"
            )
        else:
            raise ValueError(f"V41_ROUTE_INVALID:{route}")

        if keep:
            selected.append(row["trade"])
    return tuple(selected)


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": _metrics(values),
        "direction_metrics": _direction_metrics(values),
    }


def _age_bucket(age: int) -> str:
    if 1 <= age <= 5:
        return "POST_FLIP_1_5"
    if 6 <= age <= 20:
        return "POST_FLIP_6_20"
    if age > 20:
        return "POST_FLIP_GT20"
    return "NOT_POST_FLIP"


def _diagnostics(
    annotated: Sequence[Mapping[str, Any]],
    *,
    trading_days: int,
) -> dict[str, Any]:
    post = tuple(x for x in annotated if int(x["post_flip_age_days"]) > 0 and bool(x["d1_match"]))
    ages = ("POST_FLIP_1_5", "POST_FLIP_6_20", "POST_FLIP_GT20")
    return {
        "family_x_post_flip_phase": {
            f"{family}|{phase}": _stats(
                tuple(
                    row["trade"]
                    for row in post
                    if str(row["family"]) == family
                    and _age_bucket(int(row["post_flip_age_days"])) == phase
                ),
                trading_days,
            )
            for family in ("L12", "L20")
            for phase in ages
        },
        "quality_score": {
            str(q): _stats(
                tuple(
                    row["trade"]
                    for row in post
                    if int(row["transition_confirmation_score"]) == q
                ),
                trading_days,
            )
            for q in range(0, 6)
        },
        "h1_permission": {
            key: _stats(
                tuple(
                    row["trade"]
                    for row in post
                    if bool(row[field])
                ),
                trading_days,
            )
            for key, field in (
                ("SOFT", "h1_soft"),
                ("NORMAL", "h1_normal"),
                ("STRICT", "h1_strict"),
            )
        },
    }


def evaluate_v41(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V41_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    transition_context = build_transition_context(rows)
    h1_context = build_h1_context(rows)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    selected_variants = tuple(
        x for x in M15_VARIANTS if x.variant_id in {L12_ID, L20_ID}
    )
    signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in selected_variants
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )

        m15_all: list[TournamentTrade] = []
        for variant in selected_variants:
            m15_all.extend(
                simulate_m15(
                    rows,
                    signals=signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        m15 = _period(tuple(m15_all), start=start, end=end)
        annotated = annotate_transition_m15(
            m15,
            transition_context=transition_context,
            h1_context=h1_context,
        )

        routes = {route: _select(annotated, route) for route in ROUTES}
        portfolios: dict[str, Any] = {
            "D1_CLASSIC_ONLY": _stats(classic, trading_days),
        }

        for route, selected in routes.items():
            combined = _limit_concurrency(
                _dedupe_with_classic((*classic, *selected))
            )
            payload = _stats(combined, trading_days)
            if cost_id == "V24_STRESS_4675":
                payload["cash_fixed_001"] = _cash_path_stopout_safe(
                    combined,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=trading_dates,
                )
            portfolios[f"D1_CLASSIC_PLUS_{route}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "portfolios": portfolios,
            "routed_m15": {
                route: _stats(trades, trading_days)
                for route, trades in routes.items()
            },
            "diagnostics": _diagnostics(
                annotated,
                trading_days=trading_days,
            ),
        }

    episode_rows = transition_context[
        transition_context["post_flip_age_days"] == 1
    ]
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "era_id": era_id,
        "era_start": start.isoformat(),
        "era_end_exclusive": end.isoformat(),
        "trading_days": trading_days,
        "transition_episodes": int(len(episode_rows)),
        "preregistered_contract": {
            "d1_transition_required": "OPPOSITE_NONZERO_REGIME -> ONE_OR_MORE TRANSITION DAYS -> OPPOSITE_NONZERO_REGIME",
            "confirmation_features": [
                "EMA200_RECLAIM_OR_LOSS",
                "RET60_SIGN_CHANGE",
                "EMA200_SLOPE20_SIGN_CHANGE",
                f"ALIGNED_D1_DISPLACEMENT_BODY_ATR_GE_{DISPLACEMENT_BODY_ATR}",
                f"ATR14_GE_{VOL_EXPANSION_MULTIPLIER}_X_PRIOR_60D_MEDIAN",
            ],
            "quality_score_range": "0_TO_5",
            "h1_role": "PERMISSION_ONLY",
            "m15_entries": "FROZEN_V20_L12_L20",
            "post_flip_aggressive_window_days": 5,
            "post_flip_l20_only_window_end_day": 20,
            "m15_off_during_transition": True,
            "countertrend_m15_allowed": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
        },
        "routes": list(ROUTES),
        "scenario_results": scenario_results,
        "note": (
            "V41 isolates causal D1 transition episodes and post-flip age. "
            "It does not modify L12/L20 entry rules and cannot authorize execution."
        ),
    }
