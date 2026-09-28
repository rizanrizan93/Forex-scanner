from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .demo_xau_m5_bidirectional_path_v196 import evaluate_bidirectional_m5_path
from .demo_xau_supply_demand_atlas_v182 import evaluate_supply_demand_atlas
from .demo_xau_zone_reuse_v200 import evaluate_bidirectional_reuse
from .demo_xau_v226_rizan_depth_map import build_depth_map
from .models import Bar, ensure_utc
from .research_xau_htf_strategic_regime_v180 import evaluate_htf_regime_research
from .xau_canonical_decision_v240 import build_canonical_xau_decision
from .xau_dynamic_depth_hazard_v251 import build_dynamic_depth_hazard
from .xau_pressure_transition_v249 import evaluate_pressure_transition

CONTRACT = "XAU_RIZAN_STANDALONE_V253"
DEFAULT_HISTORY_ARTIFACT = "calibration/xau_v225_2_depth_prior.json"


def load_frozen_depth_prior(root: Path) -> dict[str, Any]:
    path = Path(root) / DEFAULT_HISTORY_ARTIFACT
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if str(payload.get("research_version") or "") != "XAU_ZONE_REVERSAL_DEPTH_V225_2":
        raise ValueError("standalone V225.2 calibration artifact version mismatch")
    if int(payload.get("year_count") or 0) < 15:
        raise ValueError("standalone V225.2 calibration artifact incomplete")
    return payload


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dom_heartbeat(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    current = dict(current or {})
    previous = dict(previous or {})
    score = _f(current.get("dom_pressure_score"))
    previous_score = _f(previous.get("dom_pressure_score"))
    observed_at = current.get("window_end") or now.isoformat()
    previous_observed_at = previous.get("window_end")
    analysis = dict(current)
    analysis["cross_run"] = {
        "previous_observed_at": previous_observed_at,
        "previous_state": previous.get("state"),
        "pressure_score_change": (
            None
            if score is None or previous_score is None
            else score - previous_score
        ),
        "imbalance_change": (
            None
            if _f(current.get("last_imbalance")) is None
            or _f(previous.get("last_imbalance")) is None
            else float(current["last_imbalance"]) - float(previous["last_imbalance"])
        ),
    }
    unhealthy_states = {
        "ERROR",
        "INSUFFICIENT_DOM_SAMPLES",
        "DOM_EMPTY_OR_ONE_SIDED",
    }
    return {
        "worker_name": "standalone_ctrader_dom",
        "observed_at": observed_at,
        "healthy": str(current.get("state") or "") not in unhealthy_states,
        "details": {"analysis": analysis},
    }


def build_standalone_xau_state(
    *,
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
    bid: float,
    ask: float,
    quote_timestamp: datetime,
    dom_analysis: dict[str, Any],
    previous_dom_analysis: dict[str, Any] | None,
    previous_projection: dict[str, Any] | None,
    history_details: dict[str, Any],
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Build the RIZAN dashboard directly from cTrader without Supabase REST.

    This is deliberately read-only. It reuses the production research geometry
    and canonical V240 plan builder, but grants no order/execution authority.
    """
    now = ensure_utc(as_of or datetime.now(tz=UTC))
    quote_ts = ensure_utc(quote_timestamp)
    mid = (float(bid) + float(ask)) / 2.0

    regime = evaluate_htf_regime_research(tuple(m15_bars))
    strategic = dict(regime.get("current") or {})
    strategic_bias = str(strategic.get("strategic_bias") or "NEUTRAL").upper()

    atlas = evaluate_supply_demand_atlas(
        tuple(m15_bars),
        as_of=now,
        strategic_bias=strategic_bias,
    )
    projection = evaluate_bidirectional_m5_path(
        tuple(m5_bars),
        path_map=dict(atlas.get("path_map") or {}),
        as_of=now,
        previous_projection=dict(previous_projection or {}),
    )
    reuse_v200 = evaluate_bidirectional_reuse(projection)
    for leg_name in ("current_leg", "next_leg"):
        leg = dict(projection.get(leg_name) or {})
        if leg:
            leg["zone_reuse_v200"] = dict(reuse_v200.get(leg_name) or {})
            projection[leg_name] = leg
    projection["zone_reuse_v200"] = reuse_v200

    current_leg = dict(projection.get("current_leg") or {})
    micro_refinement = dict(current_leg.get("micro_refinement") or {})
    atlas["micro_refinement"] = micro_refinement
    atlas["m5_path_projection"] = projection
    atlas["zone_reuse_v200"] = reuse_v200
    path_map = dict(atlas.get("path_map") or {})
    path_map["micro_refinement"] = micro_refinement
    path_map["m5_path_projection"] = projection
    path_map["zone_reuse_v200"] = reuse_v200
    atlas["path_map"] = path_map

    depth_map = build_depth_map(
        atlas_evaluation=atlas,
        history_details=history_details,
    )
    focus = str(depth_map.get("focus_direction") or "").upper()

    current_leg = dict(projection.get("current_leg") or {})
    path_direction = str(current_leg.get("direction") or focus).upper()

    pressure = evaluate_pressure_transition(
        direction=focus or path_direction,
        dom_heartbeat=_dom_heartbeat(dom_analysis, previous_dom_analysis, now=now),
        now=now,
    )
    dynamic_depth = build_dynamic_depth_hazard(
        v226_evaluation=depth_map,
        direction=focus or path_direction,
        live_price=mid,
        pressure_transition=pressure,
    )
    canonical = build_canonical_xau_decision(
        v226_evaluation=depth_map,
        atlas_evaluation=atlas,
        price_now=mid,
        path_direction=path_direction,
        v226_age_seconds=0.0,
        atlas_age_seconds=0.0,
    )

    quote_age = max(0.0, (now - quote_ts).total_seconds())
    state = "STANDALONE_READY"
    if quote_age > 15.0:
        state = "STANDALONE_QUOTE_STALE"
    if not canonical.get("direction"):
        state = "STANDALONE_WAIT_DIRECTION"

    return {
        "contract": CONTRACT,
        "state": state,
        "mode": "CTRADER_DIRECT_NO_SUPABASE",
        "as_of": now.isoformat(),
        "quote": {
            "bid": float(bid),
            "ask": float(ask),
            "mid": mid,
            "spread": max(0.0, float(ask) - float(bid)),
            "timestamp": quote_ts.isoformat(),
            "age_seconds": quote_age,
        },
        "strategic_regime": regime,
        "atlas": atlas,
        "m5_projection": projection,
        "zone_reuse_v200": reuse_v200,
        "v226_depth_map": depth_map,
        "pressure_transition": pressure,
        "dynamic_depth": dynamic_depth,
        "canonical": canonical,
        "dom_analysis": dict(dom_analysis or {}),
        "safety": {
            "manual_analysis_only": True,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "demo_auto_execution_enabled": False,
            "live_execution_enabled": False,
            "reason": "SUPABASE_RESTRICTED_STANDALONE_MODE",
        },
    }
