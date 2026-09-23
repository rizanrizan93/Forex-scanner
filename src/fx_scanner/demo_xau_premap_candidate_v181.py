from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Sequence

import numpy as np

from .config import load_project_config
from .demo_xau_afic_path_shadow_observer import (
    OriginZone,
    ZONE_MAX_AGE_HOURS,
    _atr,
    _origin_zones,
    _pivots,
    _resample_completed,
    _stable_zone_id,
    _zone_touch_lifecycle,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_xau_competing_zone_v175 import _session_levels
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_premap_candidate_v181"
CONTRACT = "XAU_PREMAP_CANDIDATE_V181"
REQUEST_COUNT = 1500
LOOKBACK_DAYS = 18
MAX_CANDIDATES = 6
ROUND_STEP_USD = 10.0
LIQUIDITY_NEAR_ATR = 0.25

RESEARCH_WORKERS = {
    "v175": "ctrader_xau_competing_zone_ranker_v175",
    "v177": "ctrader_xau_h1_origin_hold_break_v177",
    "v178": "ctrader_xau_h1_origin_hold_break_m5_v178",
    "v179": "ctrader_xau_m5_touch_reaction_gate_v179",
    "v180": "ctrader_xau_htf_strategic_regime_v180",
}


@dataclass(frozen=True, slots=True)
class LiquidityEvidence:
    sources: tuple[str, ...]
    nearest_distance_atr: float | None
    confluence_count: int
    round_number: float | None
    nearby_levels: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PremapCandidate:
    zone_id: str
    direction: str
    low: float
    high: float
    available_at: datetime
    origin_at: datetime
    bos_at: datetime
    age_hours: float
    h1_atr: float
    distance_points: float
    distance_atr: float
    displacement_range_atr: float
    displacement_body_fraction: float
    touch_lifecycle: str
    zone_lifecycle: str
    first_touch_at: str | None
    strategic_alignment: str
    tactical_alignment: str
    liquidity: LiquidityEvidence
    research_score: float
    v175_touch_prior: float | None
    v175_reaction_prior: float | None
    v177_hold_prior: float | None
    v178_hold_prior: float | None
    v179_reaction_prior: float | None
    execution_authority: bool
    status: str


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _latest_worker_details(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0].get("details") or {})


def _research_priors(store: SupabaseOperationalStore) -> dict[str, Any]:
    details = {
        key: _latest_worker_details(store, worker)
        for key, worker in RESEARCH_WORKERS.items()
    }

    v175 = dict(details["v175"].get("evaluation") or {})
    v177 = dict(details["v177"].get("evaluation") or {})
    v178 = dict(details["v178"].get("evaluation") or {})
    v179 = dict(details["v179"].get("evaluation") or {})
    v180 = dict(details["v180"].get("evaluation") or {})

    def direction_summary(
        evaluation: dict[str, Any],
        direction: str,
        *,
        field: str = "untouched_holdout",
    ) -> dict[str, Any]:
        return dict(
            dict(evaluation.get("directions") or {})
            .get(direction, {})
            .get(field, {})
            or {}
        )

    priors: dict[str, Any] = {
        "v175": {},
        "v177": {},
        "v178": {},
        "v179": {},
        "v180": {
            "strategic_bias": dict(v180.get("current") or {}).get("strategic_bias"),
            "confidence": dict(v180.get("current") or {}).get("confidence"),
        },
    }
    for direction in ("LONG", "SHORT"):
        v175_dir = dict(dict(v175.get("untouched_test") or {}).get(direction) or {})
        priors["v175"][direction] = {
            "touch_precision": _safe_float(v175_dir.get("touch_precision")),
            "reaction_precision": _safe_float(
                v175_dir.get("conditional_reaction_precision")
            ),
            "path_precision": _safe_float(v175_dir.get("path_precision")),
        }
        for key, evaluation in (
            ("v177", v177),
            ("v178", v178),
            ("v179", v179),
        ):
            summary = direction_summary(evaluation, direction)
            priors[key][direction] = {
                "precision_hold": _safe_float(summary.get("precision_hold")),
                "selected": summary.get("selected"),
                "threshold": _safe_float(summary.get("threshold")),
                "decision": details[key].get("decision"),
            }
    return priors


def _last_completed_h4(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
):
    h4 = _resample_completed(rows, "4h", as_of=as_of)
    return None if h4.empty else h4.iloc[-1]


def _distance_to_zone(price: float, zone: OriginZone) -> float:
    if price < float(zone.low):
        return float(zone.low) - price
    if price > float(zone.high):
        return price - float(zone.high)
    return 0.0


def _candidate_correct_side(price: float, zone: OriginZone) -> bool:
    if zone.direction == "SHORT":
        return float(zone.low) > price
    return float(zone.high) < price


def _latest_completed_levels(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
) -> tuple[dict[str, Any], ...]:
    levels: list[dict[str, Any]] = []
    daily = _resample_completed(rows, "1D", as_of=as_of)
    weekly = _resample_completed(rows, "W-MON", as_of=as_of)

    if not daily.empty:
        row = daily.iloc[-1]
        for role, column in (("HIGH", "high"), ("LOW", "low")):
            levels.append(
                {
                    "source": f"PREVIOUS_DAY_{role}",
                    "price": float(row[column]),
                    "available_at": ensure_utc(row["time"].to_pydatetime()),
                }
            )
    if not weekly.empty:
        row = weekly.iloc[-1]
        for role, column in (("HIGH", "high"), ("LOW", "low")):
            levels.append(
                {
                    "source": f"PREVIOUS_WEEK_{role}",
                    "price": float(row[column]),
                    "available_at": ensure_utc(row["time"].to_pydatetime()),
                }
            )

    for item in _session_levels(rows):
        if ensure_utc(item["available_at"]) > ensure_utc(as_of):
            continue
        for role in ("high", "low"):
            levels.append(
                {
                    "source": f"{item['source']}_{role.upper()}",
                    "price": float(item[role]),
                    "available_at": ensure_utc(item["available_at"]),
                }
            )

    h1 = _resample_completed(rows, "1h", as_of=as_of)
    if not h1.empty:
        pivots = _pivots(h1)
        for pivot in pivots[-20:]:
            if ensure_utc(pivot.available_at) > ensure_utc(as_of):
                continue
            levels.append(
                {
                    "source": f"H1_SWING_{pivot.kind}",
                    "price": float(pivot.price),
                    "available_at": ensure_utc(pivot.available_at),
                }
            )

    return tuple(levels)


def _liquidity_evidence(
    *,
    zone: OriginZone,
    atr_points: float,
    levels: Sequence[dict[str, Any]],
) -> LiquidityEvidence:
    boundary = float(zone.low) if zone.direction == "SHORT" else float(zone.high)
    round_level = round(boundary / ROUND_STEP_USD) * ROUND_STEP_USD
    relevant_role = "HIGH" if zone.direction == "SHORT" else "LOW"
    threshold = LIQUIDITY_NEAR_ATR * atr_points

    nearby: list[dict[str, Any]] = []
    distances: list[float] = []
    for level in levels:
        source = str(level.get("source") or "")
        if (
            relevant_role not in source
            and not source.startswith("H1_SWING_")
        ):
            continue
        price = _safe_float(level.get("price"))
        if price is None:
            continue
        distance = abs(price - boundary)
        if distance <= threshold:
            distances.append(distance)
            nearby.append(
                {
                    "source": source,
                    "price": price,
                    "distance_atr": distance / atr_points,
                }
            )

    round_distance = abs(round_level - boundary)
    if round_distance <= threshold:
        distances.append(round_distance)
        nearby.append(
            {
                "source": "ROUND_NUMBER",
                "price": round_level,
                "distance_atr": round_distance / atr_points,
            }
        )

    dedup: dict[str, dict[str, Any]] = {}
    for item in nearby:
        source = str(item["source"])
        previous = dedup.get(source)
        if previous is None or float(item["distance_atr"]) < float(
            previous["distance_atr"]
        ):
            dedup[source] = item

    selected = tuple(
        sorted(dedup.values(), key=lambda item: float(item["distance_atr"]))
    )
    return LiquidityEvidence(
        sources=tuple(item["source"] for item in selected),
        nearest_distance_atr=None
        if not distances
        else min(distances) / atr_points,
        confluence_count=len(selected),
        round_number=round_level if round_distance <= threshold else None,
        nearby_levels=selected[:6],
    )


def _alignment(
    direction: str,
    *,
    strategic_bias: str,
    tactical_direction: str,
) -> tuple[str, str]:
    if strategic_bias in {"LONG", "SHORT"}:
        strategic = "SEARAH" if direction == strategic_bias else "BERLAWANAN"
    else:
        strategic = "NETRAL"

    if tactical_direction in {"LONG", "SHORT"}:
        tactical = "SEARAH" if direction == tactical_direction else "BERLAWANAN"
    else:
        tactical = "NETRAL"
    return strategic, tactical


def _research_score(
    *,
    zone: OriginZone,
    age_hours: float,
    distance_atr: float,
    liquidity: LiquidityEvidence,
    strategic_alignment: str,
    tactical_alignment: str,
) -> float:
    displacement = min(1.0, max(0.0, zone.displacement_range_atr) / 2.0) * 20.0
    body = min(1.0, max(0.0, zone.displacement_body_fraction) / 0.80) * 15.0
    freshness = max(0.0, 1.0 - age_hours / max(float(ZONE_MAX_AGE_HOURS), 1.0)) * 15.0
    liquidity_score = min(20.0, liquidity.confluence_count * 5.0)
    proximity = max(0.0, 1.0 - min(distance_atr, 2.0) / 2.0) * 15.0

    if strategic_alignment == "SEARAH":
        alignment = 15.0
    elif strategic_alignment == "NETRAL" and tactical_alignment == "SEARAH":
        alignment = 10.0
    elif strategic_alignment == "NETRAL":
        alignment = 7.5
    elif tactical_alignment == "SEARAH":
        alignment = 5.0
    else:
        alignment = 0.0

    return round(
        min(100.0, displacement + body + freshness + liquidity_score + proximity + alignment),
        2,
    )


def evaluate_premap_candidates(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    priors: dict[str, Any],
) -> dict[str, Any]:
    now = ensure_utc(as_of)
    rows = tuple(
        row
        for row in sorted(tuple(bars), key=lambda row: ensure_utc(row.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )
    if len(rows) < 200:
        return {
            "contract": CONTRACT,
            "state": "INSUFFICIENT_HISTORY",
            "execution_influence": False,
            "execution_authority": False,
            "candidates": [],
        }

    h4_row = _last_completed_h4(rows, as_of=now)
    if h4_row is None:
        return {
            "contract": CONTRACT,
            "state": "INSUFFICIENT_H4",
            "execution_influence": False,
            "execution_authority": False,
            "candidates": [],
        }

    map_at = ensure_utc(h4_row["time"].to_pydatetime())
    map_price = float(h4_row["close"])
    tactical_direction = (
        "LONG" if float(h4_row["close"]) > float(h4_row["open"]) else "SHORT"
    )
    strategic_bias = str(
        dict(priors.get("v180") or {}).get("strategic_bias") or "NEUTRAL"
    ).upper()

    levels = _latest_completed_levels(rows, as_of=now)
    zones = _origin_zones(rows, as_of=now)
    last_price = float(rows[-1].close)
    candidates: list[PremapCandidate] = []

    for zone in zones:
        available_at = ensure_utc(zone.available_at)
        if available_at <= map_at:
            continue
        age_hours = max(
            0.0,
            (now - available_at).total_seconds() / 3600.0,
        )
        if age_hours > ZONE_MAX_AGE_HOURS:
            continue
        if not _candidate_correct_side(last_price, zone):
            continue

        lifecycle = _zone_touch_lifecycle(zone, bars=rows, map_at=map_at)
        if lifecycle.get("origin_invalidated_at") is not None:
            continue

        atr_points = float(zone.h1_atr)
        if not isfinite(atr_points) or atr_points <= 0:
            continue
        distance_points = _distance_to_zone(last_price, zone)
        distance_atr = distance_points / atr_points
        liquidity = _liquidity_evidence(
            zone=zone,
            atr_points=atr_points,
            levels=levels,
        )
        strategic_alignment, tactical_alignment = _alignment(
            zone.direction,
            strategic_bias=strategic_bias,
            tactical_direction=tactical_direction,
        )
        direction_priors = {
            key: dict(dict(priors.get(key) or {}).get(zone.direction) or {})
            for key in ("v175", "v177", "v178", "v179")
        }

        first_touch_at = lifecycle.get("first_touch_at")
        status = (
            "SUDAH_DISENTUH_SEBELUM_H4_BARU"
            if first_touch_at is not None
            else "MENUNGGU_VALIDASI_H4_BARU"
        )

        candidates.append(
            PremapCandidate(
                zone_id=_stable_zone_id(zone),
                direction=zone.direction,
                low=float(zone.low),
                high=float(zone.high),
                available_at=available_at,
                origin_at=ensure_utc(zone.origin_at),
                bos_at=ensure_utc(zone.bos_at),
                age_hours=age_hours,
                h1_atr=atr_points,
                distance_points=distance_points,
                distance_atr=distance_atr,
                displacement_range_atr=float(zone.displacement_range_atr),
                displacement_body_fraction=float(
                    zone.displacement_body_fraction
                ),
                touch_lifecycle=str(lifecycle.get("touch_lifecycle") or "UNTOUCHED"),
                zone_lifecycle=str(lifecycle.get("zone_lifecycle") or "UNTOUCHED"),
                first_touch_at=first_touch_at,
                strategic_alignment=strategic_alignment,
                tactical_alignment=tactical_alignment,
                liquidity=liquidity,
                research_score=_research_score(
                    zone=zone,
                    age_hours=age_hours,
                    distance_atr=distance_atr,
                    liquidity=liquidity,
                    strategic_alignment=strategic_alignment,
                    tactical_alignment=tactical_alignment,
                ),
                v175_touch_prior=_safe_float(
                    direction_priors["v175"].get("touch_precision")
                ),
                v175_reaction_prior=_safe_float(
                    direction_priors["v175"].get("reaction_precision")
                ),
                v177_hold_prior=_safe_float(
                    direction_priors["v177"].get("precision_hold")
                ),
                v178_hold_prior=_safe_float(
                    direction_priors["v178"].get("precision_hold")
                ),
                v179_reaction_prior=_safe_float(
                    direction_priors["v179"].get("precision_hold")
                ),
                execution_authority=False,
                status=status,
            )
        )

    candidates.sort(
        key=lambda item: (
            item.first_touch_at is not None,
            -item.research_score,
            item.distance_atr,
            item.age_hours,
        )
    )
    selected = candidates[:MAX_CANDIDATES]
    return {
        "contract": CONTRACT,
        "state": "PREMAP_CANDIDATES_AVAILABLE" if selected else "NO_PREMAP_CANDIDATE",
        "map_at": map_at.isoformat(),
        "map_price": map_price,
        "last_closed_m15_price": last_price,
        "tactical_h4_direction": tactical_direction,
        "strategic_bias": strategic_bias,
        "execution_influence": False,
        "execution_authority": False,
        "candidate_count": len(selected),
        "candidates": [
            {
                **asdict(candidate),
                "available_at": candidate.available_at.isoformat(),
                "origin_at": candidate.origin_at.isoformat(),
                "bos_at": candidate.bos_at.isoformat(),
            }
            for candidate in selected
        ],
        "explanation": {
            "zone_definition": "H1_BOS_DISPLACEMENT_CAUSAL_ORIGIN_ONLY",
            "liquidity_role": "CONFLUENCE_AND_RANKING_ONLY_NOT_ZONE_AUTHORITY",
            "promotion_rule": "MUST_SURVIVE_UNTIL_NEXT_COMPLETED_H4_MAP_AND_PASS_CANONICAL_AFIC_SELECTION",
            "research_priors_are_candidate_specific": False,
            "research_prior_note": (
                "V175/V177/V178/V179 values are directional untouched-test priors, "
                "not calibrated probability for this individual candidate."
            ),
        },
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_PREMAP_V181_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_PREMAP_V181_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_PREMAP_V181_SYMBOL_NOT_CONFIGURED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {}
    error: str | None = None
    raw_count = 0
    try:
        priors = _research_priors(store)
        feed.ensure_connected()
        raw = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=now - timedelta(days=LOOKBACK_DAYS),
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
        raw_count = len(raw)
        payload = evaluate_premap_candidates(raw, as_of=now, priors=priors)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "execution_authority": False,
            "live_execution_enabled": False,
            "raw_m15_bars": raw_count,
            "evaluation": payload,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_PREMAP_V181 "
        f"healthy={int(healthy)} state={payload.get('state','ERROR')} "
        f"candidates={payload.get('candidate_count',0)} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
