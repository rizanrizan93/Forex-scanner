from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .research_xau_pressure_depth_v246 import _bar_force, condition_depth_episodes
from .research_xau_zone_reversal_depth_v225 import DepthEpisode

RESEARCH_VERSION = "XAU_PRESSURE_TRANSITION_DEPTH_V250_1"
ARTIFACT_CONTRACT = "XAU_PRESSURE_TRANSITION_DEPTH_V250_1_EVIDENCE_1"
PRE_TOUCH_BARS = 12
MIN_PRE_TOUCH_BARS = 8


@dataclass(frozen=True, slots=True)
class TransitionDepthEpisode:
    zone_id: str
    timeframe: str
    direction: str
    touch_at: str
    year: int
    session: str
    reaction_hit: bool
    break_hit: bool
    turning_depth: float | None
    max_depth_reached: float
    zone_width: float
    atr_points: float
    atr_pct: float
    level_opposing_pressure: float
    early_opposing_pressure: float
    late_opposing_pressure: float
    fade_delta: float
    transition_state: str
    approach_progress_atr: float
    late_progress_atr: float
    range_compression_ratio: float
    mean_body_efficiency: float
    mean_close_location: float


def _session(ts: pd.Timestamp) -> str:
    dt = ts.to_pydatetime()
    syd = dt.astimezone(ZoneInfo("Australia/Sydney"))
    tok = dt.astimezone(ZoneInfo("Asia/Tokyo"))
    lon = dt.astimezone(ZoneInfo("Europe/London"))
    ny = dt.astimezone(ZoneInfo("America/New_York"))
    flags = []
    if 8 <= syd.hour < 17: flags.append("SYDNEY")
    if 9 <= tok.hour < 18: flags.append("TOKYO")
    if 8 <= lon.hour < 17: flags.append("LONDON")
    if 8 <= ny.hour < 17: flags.append("NEW_YORK")
    if "LONDON" in flags and "NEW_YORK" in flags: return "LONDON_NY_OVERLAP"
    if "SYDNEY" in flags and "TOKYO" in flags: return "SYDNEY_TOKYO_OVERLAP"
    if "LONDON" in flags: return "LONDON"
    if "NEW_YORK" in flags: return "NEW_YORK"
    if "TOKYO" in flags: return "TOKYO"
    if "SYDNEY" in flags: return "SYDNEY"
    return "OFF_SESSION"


def _transition_state(early: float, late: float, fade: float) -> str:
    if early >= 40.0 and fade >= 15.0:
        return "STRONG_FADE"
    if early >= 15.0 and fade >= 10.0:
        return "FADE"
    if late <= 15.0 and fade > 0.0:
        return "BALANCE_OR_CONTROL_FLIP"
    if fade <= -10.0:
        return "REACCELERATION"
    return "STABLE"


def transition_features_before_touch(
    price_m1: pd.DataFrame,
    *,
    episode: DepthEpisode,
) -> dict[str, Any] | None:
    ts = pd.to_datetime(price_m1["timestamp"], utc=True, errors="coerce")
    touch = pd.Timestamp(episode.touch_at)
    idx = int(ts.searchsorted(touch, side="left"))
    start = max(0, idx - PRE_TOUCH_BARS)
    window = price_m1.iloc[start:idx].copy()
    if len(window) < MIN_PRE_TOUCH_BARS:
        return None

    forces = []
    body_eff = []
    close_loc = []
    for _, row in window.iterrows():
        force, body, close = _bar_force(row)
        forces.append(float(force))
        body_eff.append(float(body))
        close_loc.append(float(close))

    half = max(3, len(forces) // 2)
    early_signed = float(np.mean(forces[:half]) * 100.0)
    late_signed = float(np.mean(forces[-half:]) * 100.0)
    if episode.direction == "LONG":
        early_opp = -early_signed
        late_opp = -late_signed
    else:
        early_opp = early_signed
        late_opp = late_signed
    fade = early_opp - late_opp

    atr = max(float(episode.atr_points), 1e-12)
    first_open = float(window.iloc[0]["open"])
    last_close = float(window.iloc[-1]["close"])
    progress = (first_open - last_close) / atr if episode.direction == "LONG" else (last_close - first_open) / atr
    late_open = float(window.iloc[-half]["open"])
    late_progress = (late_open - last_close) / atr if episode.direction == "LONG" else (last_close - late_open) / atr
    ranges = (window["high"].astype(float) - window["low"].astype(float)).to_numpy(dtype=float)
    early_range = float(np.mean(ranges[:half])) if len(ranges) else 0.0
    late_range = float(np.mean(ranges[-half:])) if len(ranges) else 0.0
    compression = 1.0 if early_range <= 1e-12 else late_range / early_range

    return {
        "session": _session(touch),
        "early_opposing_pressure": early_opp,
        "late_opposing_pressure": late_opp,
        "fade_delta": fade,
        "transition_state": _transition_state(early_opp, late_opp, fade),
        "approach_progress_atr": progress,
        "late_progress_atr": late_progress,
        "range_compression_ratio": compression,
        "mean_body_efficiency": float(np.mean(body_eff)),
        "mean_close_location": float(np.mean(close_loc)),
    }


def build_transition_depth_rows(
    price_m1: pd.DataFrame,
    episodes: Sequence[DepthEpisode],
) -> tuple[TransitionDepthEpisode, ...]:
    level_rows = condition_depth_episodes(price_m1, episodes)
    level_map = {
        (r.zone_id, r.timeframe, r.direction, r.touch_at): r
        for r in level_rows
    }
    out = []
    for ep in episodes:
        key = (ep.zone_id, ep.timeframe, ep.direction, ep.touch_at.isoformat())
        level = level_map.get(key)
        features = transition_features_before_touch(price_m1, episode=ep)
        if level is None or features is None:
            continue
        zone_mid = (float(ep.zone_low) + float(ep.zone_high)) / 2.0
        atr_pct = (
            float(ep.atr_points) / zone_mid
            if zone_mid > 0.0
            else 0.0
        )
        out.append(
            TransitionDepthEpisode(
                zone_id=ep.zone_id,
                timeframe=ep.timeframe,
                direction=ep.direction,
                touch_at=ep.touch_at.isoformat(),
                year=int(ep.touch_at.year),
                session=str(features["session"]),
                reaction_hit=bool(ep.reaction_hit),
                break_hit=bool(ep.break_hit),
                turning_depth=None if ep.turning_depth is None else float(ep.turning_depth),
                max_depth_reached=float(ep.max_depth_reached),
                zone_width=float(ep.zone_width),
                atr_points=float(ep.atr_points),
                atr_pct=float(atr_pct),
                level_opposing_pressure=float(level.opposing_pressure_score),
                early_opposing_pressure=float(features["early_opposing_pressure"]),
                late_opposing_pressure=float(features["late_opposing_pressure"]),
                fade_delta=float(features["fade_delta"]),
                transition_state=str(features["transition_state"]),
                approach_progress_atr=float(features["approach_progress_atr"]),
                late_progress_atr=float(features["late_progress_atr"]),
                range_compression_ratio=float(features["range_compression_ratio"]),
                mean_body_efficiency=float(features["mean_body_efficiency"]),
                mean_close_location=float(features["mean_close_location"]),
            )
        )
    return tuple(out)


def serialize_row(row: TransitionDepthEpisode) -> dict[str, Any]:
    return asdict(row)