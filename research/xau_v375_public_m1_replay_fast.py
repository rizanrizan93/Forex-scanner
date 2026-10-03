from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from datetime import timedelta
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

import xau_v375_public_m1_replay as base
from fx_scanner import xau_sd_liquidity_engine_v342 as sd_engine


FRAME_CACHE_SIZE = 20


def _install_replay_acceleration(
    config: base.ReplayConfig,
    *,
    cache_dir: Path,
) -> dict[str, int]:
    """Install replay-only caches without changing production engine semantics.

    Two hotspots dominate the historical matrix:
    1. rebuilding identical pandas OHLC frames many times inside one evaluation;
    2. redetecting every causal H1/H4 zone from scratch on every hourly scan.

    Zone formation is causal and immutable after its departure candle closes, so
    we can build a year index once, then return exactly the subset that was
    available inside the rolling production window at each historical as_of.
    """

    m1, _ = base.load_public_m1(config, cache_dir)
    h1 = base._resample(m1, "1h")
    h4 = base._resample(m1, "4h")
    h1_bars, _ = base._bars(h1)
    h4_bars, _ = base._bars(h4)

    original_detect_zones = sd_engine.detect_zones
    original_bar_frame = sd_engine._bar_frame

    precomputed: dict[str, tuple[Any, ...]] = {
        "H1": tuple(
            sorted(
                original_detect_zones(h1_bars, timeframe="H1", as_of=config.end),
                key=lambda zone: zone.available_at,
            )
        ),
        "H4": tuple(
            sorted(
                original_detect_zones(h4_bars, timeframe="H4", as_of=config.end),
                key=lambda zone: zone.available_at,
            )
        ),
    }
    available_times = {
        tf: [zone.available_at for zone in zones]
        for tf, zones in precomputed.items()
    }

    frame_cache: OrderedDict[int, tuple[object, pd.DataFrame]] = OrderedDict()

    def cached_bar_frame(bars: Iterable[Any]) -> pd.DataFrame:
        key = id(bars)
        hit = frame_cache.get(key)
        if hit is not None and hit[0] is bars:
            frame_cache.move_to_end(key)
            # Callers may add columns; give each caller an isolated frame while
            # avoiding the expensive Python object -> DataFrame reconstruction.
            return hit[1].copy(deep=True)

        frame = original_bar_frame(bars)
        frame_cache[key] = (bars, frame)
        frame_cache.move_to_end(key)
        while len(frame_cache) > FRAME_CACHE_SIZE:
            frame_cache.popitem(last=False)
        return frame.copy(deep=True)

    def cached_detect_zones(
        bars: Iterable[Any],
        *,
        timeframe: str,
        as_of,
    ) -> tuple[Any, ...]:
        tf = str(timeframe).upper()
        if tf not in precomputed:
            return original_detect_zones(bars, timeframe=timeframe, as_of=as_of)

        seq = bars if isinstance(bars, list) else list(bars)
        if len(seq) < 24:
            return ()

        now = sd_engine.ensure_utc(as_of)
        delta = timedelta(minutes=int(sd_engine.TF_MINUTES[tf]))
        completed = [
            bar
            for bar in seq
            if sd_engine.ensure_utc(bar.timestamp) + delta <= now
        ]
        if len(completed) < 24:
            return ()

        # detect_zones() starts the departure scan at frame index 18. Using the
        # 19th completed candle reproduces the oldest zone that the same rolling
        # window could have discovered, including weekend/session gaps.
        oldest_available = sd_engine.ensure_utc(completed[18].timestamp) + delta
        times = available_times[tf]
        left = bisect_left(times, oldest_available)
        right = bisect_right(times, now)
        return precomputed[tf][left:right]

    def fast_lifecycle(
        zone: Any,
        bars: Iterable[Any],
        *,
        as_of,
    ) -> dict[str, Any]:
        """Vectorized equivalent of V342 lifecycle accounting for replay."""
        frame = cached_bar_frame(bars)
        if frame.empty:
            return {"active": True, "touch_count": 0, "freshness": "UNKNOWN"}

        known_delta = pd.Timedelta(minutes=sd_engine.TF_MINUTES[zone.timeframe])
        work = frame.copy(deep=False)
        work["known_at"] = work["timestamp"] + known_delta
        available = pd.Timestamp(zone.available_at)
        now = pd.Timestamp(sd_engine.ensure_utc(as_of))
        future = work[
            (work["known_at"] > available)
            & (work["known_at"] <= now)
        ].copy()

        width = max(float(zone.high - zone.low), 1e-9)
        invalidated_at: str | None = None
        max_mitigation = 0.0
        touch_count = 0
        first_touch_at: str | None = None
        last_touch_at: str | None = None

        if not future.empty:
            close = future["close"].astype(float)
            if zone.direction == "LONG":
                invalid_mask = close < float(zone.distal) - 0.05 * float(zone.atr)
            else:
                invalid_mask = close > float(zone.distal) + 0.05 * float(zone.atr)

            if bool(invalid_mask.any()):
                invalid_label = invalid_mask[invalid_mask].index[0]
                invalid_pos = int(future.index.get_loc(invalid_label))
                future = future.iloc[: invalid_pos + 1].copy()
                invalidated_at = sd_engine.ensure_utc(
                    future.iloc[-1]["known_at"].to_pydatetime()
                ).isoformat()

            inside = (
                (future["high"].astype(float) >= float(zone.low))
                & (future["low"].astype(float) <= float(zone.high))
            )
            starts = inside & ~inside.shift(1, fill_value=False)
            touch_count = int(starts.sum())

            if bool(inside.any()):
                touched = future.loc[inside]
                first_touch_at = sd_engine.ensure_utc(
                    touched.iloc[0]["known_at"].to_pydatetime()
                ).isoformat()
                last_touch_at = sd_engine.ensure_utc(
                    touched.iloc[-1]["known_at"].to_pydatetime()
                ).isoformat()

                if zone.direction == "LONG":
                    adverse = touched["low"].astype(float).clip(lower=float(zone.low))
                    depth = (float(zone.high) - adverse) / width
                else:
                    adverse = touched["high"].astype(float).clip(upper=float(zone.high))
                    depth = (adverse - float(zone.low)) / width
                if not depth.empty:
                    max_mitigation = float(
                        depth.clip(lower=0.0, upper=1.5).max()
                    )

        if invalidated_at:
            freshness = "BROKEN"
        elif touch_count == 0:
            freshness = "FRESH"
        elif max_mitigation >= 0.75:
            freshness = "DEEPLY_MITIGATED"
        elif max_mitigation >= 0.35:
            freshness = "PARTIALLY_MITIGATED"
        elif touch_count == 1:
            freshness = "FIRST_TEST"
        else:
            freshness = "RETESTED"

        age_hours = max(
            0.0,
            (
                sd_engine.ensure_utc(as_of)
                - sd_engine.ensure_utc(zone.available_at)
            ).total_seconds()
            / 3600.0,
        )
        expired = age_hours > float(
            sd_engine.TF_PARAMS[zone.timeframe]["lifecycle_hours"]
        )
        return {
            "active": bool(not invalidated_at and not expired),
            "touch_count": touch_count,
            "first_touch_at": first_touch_at,
            "last_touch_at": last_touch_at,
            "invalidated_at": invalidated_at,
            "mitigation_depth": round(max_mitigation, 4),
            "freshness": "EXPIRED" if expired and not invalidated_at else freshness,
            "age_hours": round(age_hours, 2),
        }

    sd_engine._bar_frame = cached_bar_frame
    sd_engine.detect_zones = cached_detect_zones
    sd_engine._lifecycle = fast_lifecycle

    stats = {
        "precomputed_h1_zones": len(precomputed["H1"]),
        "precomputed_h4_zones": len(precomputed["H4"]),
        "frame_cache_size": FRAME_CACHE_SIZE,
    }
    print(
        "FAST_REPLAY_ACCELERATOR "
        + " ".join(f"{key}={value}" for key, value in stats.items()),
        flush=True,
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Accelerated causal replay of production V375 using replay-only "
            "zone indexing and OHLC frame caching."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument(
        "--step-minutes",
        type=int,
        default=60,
        choices=[15, 30, 60, 120, 240],
    )
    parser.add_argument("--spread", type=float, default=0.30)
    parser.add_argument("--entry-slippage", type=float, default=0.05)
    parser.add_argument("--stop-slippage", type=float, default=0.10)
    parser.add_argument("--cache-dir", default=".cache/xau_public_m1")
    parser.add_argument(
        "--output",
        default="research/results/xau_v375_public_m1_replay.json",
    )
    parser.add_argument(
        "--trades-output",
        default="research/results/xau_v375_public_m1_trades.csv",
    )
    args = parser.parse_args()

    start = base._parse_datetime(args.start)
    end = base._parse_datetime(args.end, end=True)
    if end <= start:
        raise SystemExit("--end must be after --start")

    config = base.ReplayConfig(
        start=start,
        end=end,
        step_minutes=int(args.step_minutes),
        spread=float(args.spread),
        entry_slippage=float(args.entry_slippage),
        stop_slippage=float(args.stop_slippage),
    )
    cache_dir = Path(args.cache_dir)
    acceleration = _install_replay_acceleration(config, cache_dir=cache_dir)
    metrics, trades = base.run_replay(config, cache_dir=cache_dir)
    metrics["replay_acceleration"] = {
        "mode": "CAUSAL_ZONE_INDEX_PLUS_FRAME_CACHE",
        **acceleration,
        "production_logic_changed": False,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(metrics, indent=2, sort_keys=True, default=str) + "\n"
    )

    trades_output = Path(args.trades_output)
    trades_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([base.asdict(trade) for trade in trades]).to_csv(
        trades_output,
        index=False,
    )

    print(
        "V375_PUBLIC_REPLAY_RESULT="
        + json.dumps(metrics, sort_keys=True, default=str),
        flush=True,
    )
    print(f"RESULT_JSON={output}", flush=True)
    print(f"TRADES_CSV={trades_output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
