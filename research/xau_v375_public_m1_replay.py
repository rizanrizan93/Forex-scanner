from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from bisect import bisect_right
from dataclasses import dataclass, asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from fx_scanner.demo_xau_v375_reaction_executor import _candidate as v375_candidate
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity


SOURCE_REPO = "nousx/xauusd-data"
SOURCE_TEMPLATE = (
    "https://raw.githubusercontent.com/nousx/xauusd-data/main/"
    "DAT_ASCII_XAUUSD_M1_{token}.csv"
)


@dataclass(slots=True, frozen=True)
class ReplayBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(slots=True)
class Trade:
    signal_id: str
    direction: str
    execution_lane: str
    entry_mode: str
    confirmation_tier: str
    parent_zone_id: str | None
    entry_time: datetime
    entry: float
    stop_loss: float
    take_profit: float
    planned_rr: float
    risk: float
    mae_r: float = 0.0
    mfe_r: float = 0.0
    exit_time: datetime | None = None
    exit: float | None = None
    exit_reason: str | None = None
    realized_r: float | None = None


@dataclass(slots=True, frozen=True)
class ReplayConfig:
    start: datetime
    end: datetime
    step_minutes: int
    spread: float
    entry_slippage: float
    stop_slippage: float
    h4_bars: int = 650
    h1_bars: int = 2200
    m15_bars: int = 800
    m5_bars: int = 2400
    max_open_positions: int = 10
    max_open_per_parent: int = 4
    lookback_days: int = 100
    forward_days: int = 90


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _download(url: str, path: Path) -> bool:
    if path.exists() and path.stat().st_size > 1000:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=90) as response:
        if response.status_code == 404:
            return False
        response.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        tmp.replace(path)
    return True


def _tokens_for_range(start: datetime, end: datetime) -> list[str]:
    years = range(start.year, end.year + 1)
    tokens: list[str] = []
    for year in years:
        if year <= 2025:
            tokens.append(str(year))
        elif year == 2026:
            # Public mirror is presently partial for 2026. Probe all months and
            # use those that exist, while reporting actual coverage explicitly.
            tokens.extend(f"2026{month:02d}" for month in range(1, 13))
        else:
            tokens.append(str(year))
    return tokens


def _read_histdata_file(path: Path) -> pd.DataFrame:
    names = ["datetime", "open", "high", "low", "close", "volume"]
    frame = pd.read_csv(
        path,
        sep=";",
        header=None,
        names=names,
        usecols=range(6),
        dtype={
            "datetime": "string",
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "float64",
        },
        engine="c",
    )
    ts = pd.to_datetime(frame["datetime"], format="%Y%m%d %H%M%S", errors="coerce")
    good = ts.notna()
    frame = frame.loc[good, ["open", "high", "low", "close", "volume"]].copy()
    ts = ts.loc[good]
    # HistData Generic ASCII specification uses fixed EST (UTC-5) without DST.
    frame.index = ts.dt.tz_localize("Etc/GMT+5").dt.tz_convert("UTC")
    frame.index.name = "timestamp"
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


def load_public_m1(config: ReplayConfig, cache_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    load_start = config.start - timedelta(days=config.lookback_days)
    load_end = config.end + timedelta(days=config.forward_days)
    frames: list[pd.DataFrame] = []
    used: list[str] = []
    for token in _tokens_for_range(load_start, load_end):
        url = SOURCE_TEMPLATE.format(token=token)
        path = cache_dir / f"DAT_ASCII_XAUUSD_M1_{token}.csv"
        try:
            exists = _download(url, path)
        except requests.RequestException as exc:
            print(f"DATA_DOWNLOAD_ERROR token={token} error={exc}", file=sys.stderr)
            continue
        if not exists:
            continue
        frame = _read_histdata_file(path)
        frames.append(frame)
        used.append(token)
        print(
            f"DATA_LOADED token={token} rows={len(frame)} "
            f"first={frame.index.min()} last={frame.index.max()}",
            flush=True,
        )
    if not frames:
        raise RuntimeError("no public XAUUSD M1 files could be loaded")
    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.loc[
        (combined.index >= pd.Timestamp(load_start))
        & (combined.index <= pd.Timestamp(load_end))
    ].copy()
    return combined, used


def _resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = frame.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        count=("close", "count"),
    )
    return out[out["count"] > 0].drop(columns="count")


def _bars(frame: pd.DataFrame) -> tuple[list[ReplayBar], list[datetime]]:
    bars: list[ReplayBar] = []
    times: list[datetime] = []
    for row in frame.itertuples():
        ts = row.Index.to_pydatetime().astimezone(UTC)
        bars.append(
            ReplayBar(
                timestamp=ts,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
            )
        )
        times.append(ts)
    return bars, times


def _window(
    bars: list[ReplayBar],
    times: list[datetime],
    *,
    as_of: datetime,
    timeframe_minutes: int,
    count: int,
) -> list[ReplayBar]:
    cutoff = as_of - timedelta(minutes=timeframe_minutes)
    right = bisect_right(times, cutoff)
    left = max(0, right - count)
    return bars[left:right]


def _completed_m1_index(times: list[datetime], as_of: datetime) -> int:
    return bisect_right(times, as_of - timedelta(minutes=1)) - 1


def _pf(values: Iterable[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses <= 1e-12:
        return math.inf if gains > 0 else None
    return gains / losses


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _max_consecutive_losses(values: list[float]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _close_trade(trade: Trade, *, ts: datetime, price: float, reason: str) -> None:
    trade.exit_time = ts
    trade.exit = price
    trade.exit_reason = reason
    if trade.direction == "LONG":
        trade.realized_r = (price - trade.entry) / trade.risk
    else:
        trade.realized_r = (trade.entry - price) / trade.risk


def _process_bar(
    trade: Trade,
    bar: ReplayBar,
    *,
    spread: float,
    stop_slippage: float,
) -> bool:
    if trade.exit_time is not None:
        return True
    risk = max(trade.risk, 1e-12)
    if trade.direction == "LONG":
        adverse = min(0.0, (bar.low - trade.entry) / risk)
        favorable = max(0.0, (bar.high - trade.entry) / risk)
        trade.mae_r = min(trade.mae_r, adverse)
        trade.mfe_r = max(trade.mfe_r, favorable)

        stop_hit = bar.low <= trade.stop_loss
        tp_hit = bar.high >= trade.take_profit
        if stop_hit:  # STOP_FIRST if both are inside the same M1 bar.
            gap_fill = bar.open - stop_slippage if bar.open <= trade.stop_loss else trade.stop_loss - stop_slippage
            _close_trade(trade, ts=bar.timestamp + timedelta(minutes=1), price=gap_fill, reason="SL")
            return True
        if tp_hit:
            _close_trade(trade, ts=bar.timestamp + timedelta(minutes=1), price=trade.take_profit, reason="TP")
            return True
        return False

    ask_open = bar.open + spread
    ask_high = bar.high + spread
    ask_low = bar.low + spread
    adverse = min(0.0, (trade.entry - ask_high) / risk)
    favorable = max(0.0, (trade.entry - ask_low) / risk)
    trade.mae_r = min(trade.mae_r, adverse)
    trade.mfe_r = max(trade.mfe_r, favorable)

    stop_hit = ask_high >= trade.stop_loss
    tp_hit = ask_low <= trade.take_profit
    if stop_hit:
        gap_fill = ask_open + stop_slippage if ask_open >= trade.stop_loss else trade.stop_loss + stop_slippage
        _close_trade(trade, ts=bar.timestamp + timedelta(minutes=1), price=gap_fill, reason="SL")
        return True
    if tp_hit:
        _close_trade(trade, ts=bar.timestamp + timedelta(minutes=1), price=trade.take_profit, reason="TP")
        return True
    return False


def _metrics(trades: list[Trade]) -> dict[str, object]:
    closed = [t for t in trades if t.realized_r is not None]
    values = [float(t.realized_r) for t in closed]
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    durations = [
        (t.exit_time - t.entry_time).total_seconds() / 3600.0
        for t in closed
        if t.exit_time is not None
    ]
    lane_counts: dict[str, int] = {}
    exit_counts: dict[str, int] = {}
    for t in closed:
        lane_counts[t.execution_lane] = lane_counts.get(t.execution_lane, 0) + 1
        exit_counts[str(t.exit_reason)] = exit_counts.get(str(t.exit_reason), 0) + 1
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(closed)) if closed else None,
        "profit_factor": _pf(values),
        "expectancy_r": statistics.fmean(values) if values else None,
        "avg_win_r": statistics.fmean(wins) if wins else None,
        "avg_loss_r": statistics.fmean(losses) if losses else None,
        "net_r": sum(values),
        "max_drawdown_r": _max_drawdown(values),
        "max_consecutive_losses": _max_consecutive_losses(values),
        "median_hold_hours": statistics.median(durations) if durations else None,
        "median_mae_r": statistics.median([t.mae_r for t in closed]) if closed else None,
        "median_mfe_r": statistics.median([t.mfe_r for t in closed]) if closed else None,
        "lane_counts": lane_counts,
        "exit_counts": exit_counts,
    }


def run_replay(config: ReplayConfig, *, cache_dir: Path) -> tuple[dict[str, object], list[Trade]]:
    m1, source_tokens = load_public_m1(config, cache_dir)
    if m1.empty:
        raise RuntimeError("M1 dataset empty after requested date filtering")

    m5 = _resample(m1, "5min")
    m15 = _resample(m1, "15min")
    h1 = _resample(m1, "1h")
    h4 = _resample(m1, "4h")

    m1_bars, m1_times = _bars(m1[["open", "high", "low", "close"]])
    m5_bars, m5_times = _bars(m5)
    m15_bars, m15_times = _bars(m15)
    h1_bars, h1_times = _bars(h1)
    h4_bars, h4_times = _bars(h4)

    evaluation_times: list[datetime] = []
    for bar in m15_bars:
        as_of = bar.timestamp + timedelta(minutes=15)
        if not (config.start <= as_of <= config.end):
            continue
        if config.step_minutes > 15:
            minutes_from_midnight = as_of.hour * 60 + as_of.minute
            if minutes_from_midnight % config.step_minutes != 0:
                continue
        evaluation_times.append(as_of)

    print(
        f"REPLAY_START start={config.start.isoformat()} end={config.end.isoformat()} "
        f"step={config.step_minutes}m evaluations={len(evaluation_times)} "
        f"spread={config.spread:.3f} entry_slip={config.entry_slippage:.3f} "
        f"stop_slip={config.stop_slippage:.3f}",
        flush=True,
    )

    accepted_signals: set[str] = set()
    active: list[Trade] = []
    completed: list[Trade] = []
    scan_reason_counts: dict[str, int] = {}
    lane_signal_counts: dict[str, int] = {}
    next_m1_to_process = max(0, bisect_right(m1_times, config.start) - 1)

    for seq, as_of in enumerate(evaluation_times, start=1):
        # First resolve all minute bars completed since the previous scanner cycle.
        completed_idx = _completed_m1_index(m1_times, as_of)
        while next_m1_to_process <= completed_idx and next_m1_to_process < len(m1_bars):
            bar = m1_bars[next_m1_to_process]
            survivors: list[Trade] = []
            for trade in active:
                if _process_bar(
                    trade,
                    bar,
                    spread=config.spread,
                    stop_slippage=config.stop_slippage,
                ):
                    completed.append(trade)
                else:
                    survivors.append(trade)
            active = survivors
            next_m1_to_process += 1

        price_idx = _completed_m1_index(m1_times, as_of)
        if price_idx < 0:
            continue
        bid = float(m1_bars[price_idx].close)
        ask = bid + config.spread

        bars_h4 = _window(
            h4_bars,
            h4_times,
            as_of=as_of,
            timeframe_minutes=240,
            count=config.h4_bars,
        )
        bars_h1 = _window(
            h1_bars,
            h1_times,
            as_of=as_of,
            timeframe_minutes=60,
            count=config.h1_bars,
        )
        bars_m15 = _window(
            m15_bars,
            m15_times,
            as_of=as_of,
            timeframe_minutes=15,
            count=config.m15_bars,
        )
        bars_m5 = _window(
            m5_bars,
            m5_times,
            as_of=as_of,
            timeframe_minutes=5,
            count=config.m5_bars,
        )
        if len(bars_h4) < 24 or len(bars_h1) < 24:
            continue

        evaluation = evaluate_sd_liquidity(
            bars_h1=bars_h1,
            bars_h4=bars_h4,
            bars_m15=bars_m15,
            bars_m5=bars_m5,
            as_of=as_of,
            price_now=bid,
        )
        guide_state = str(dict(evaluation.get("entry_guide") or {}).get("state") or "WAIT_CONFIRMATION")
        evaluation["news_zone"] = {
            "risk_state": "CLEAR",
            "execution_risk_state": "CLEAR",
            "effective_entry_state": guide_state,
            "historical_replay_note": "NO_HISTORICAL_EVENT_CALENDAR_GATE",
        }
        heartbeat = {
            "healthy": True,
            "observed_at": as_of.isoformat(),
            "details": {"evaluation": evaluation},
        }
        candidate, reason = v375_candidate(
            heartbeat=heartbeat,
            bid=bid,
            ask=ask,
            now=as_of,
        )
        scan_reason_counts[reason] = scan_reason_counts.get(reason, 0) + 1
        if candidate is None:
            if seq % 1000 == 0:
                print(
                    f"REPLAY_PROGRESS scans={seq}/{len(evaluation_times)} "
                    f"closed={len(completed)} active={len(active)} accepted={len(accepted_signals)}",
                    flush=True,
                )
            continue

        signal_id = str(candidate["signal_id"])
        if signal_id in accepted_signals:
            continue
        parent_zone_id = candidate.get("parent_zone_id")
        parent_open = sum(
            1 for trade in active
            if parent_zone_id and trade.parent_zone_id == parent_zone_id
        )
        if len(active) >= config.max_open_positions or parent_open >= config.max_open_per_parent:
            continue

        direction = str(candidate["direction"])
        raw_entry = float(candidate["entry"])
        entry = (
            raw_entry + config.entry_slippage
            if direction == "LONG"
            else raw_entry - config.entry_slippage
        )
        stop = float(candidate["stop_loss"])
        target = float(candidate["take_profit"])
        if direction == "LONG":
            if not stop < entry < target:
                continue
            risk = entry - stop
            actual_rr = (target - entry) / risk
        else:
            if not target < entry < stop:
                continue
            risk = stop - entry
            actual_rr = (entry - target) / risk
        if risk <= 0:
            continue

        trade = Trade(
            signal_id=signal_id,
            direction=direction,
            execution_lane=str(candidate.get("execution_lane") or "UNKNOWN"),
            entry_mode=str(candidate.get("entry_mode") or "UNKNOWN"),
            confirmation_tier=str(candidate.get("confirmation_tier") or "UNKNOWN"),
            parent_zone_id=None if parent_zone_id is None else str(parent_zone_id),
            entry_time=as_of,
            entry=entry,
            stop_loss=stop,
            take_profit=target,
            planned_rr=actual_rr,
            risk=risk,
        )
        active.append(trade)
        accepted_signals.add(signal_id)
        lane_signal_counts[trade.execution_lane] = lane_signal_counts.get(trade.execution_lane, 0) + 1
        print(
            "SIGNAL_ACCEPTED "
            f"at={as_of.isoformat()} lane={trade.execution_lane} direction={direction} "
            f"entry={entry:.3f} sl={stop:.3f} tp={target:.3f} rr={actual_rr:.3f} "
            f"signal={signal_id}",
            flush=True,
        )

    # Resolve open trades through the configured forward-data buffer.
    final_limit = config.end + timedelta(days=config.forward_days)
    final_idx = bisect_right(m1_times, final_limit - timedelta(minutes=1)) - 1
    while next_m1_to_process <= final_idx and next_m1_to_process < len(m1_bars) and active:
        bar = m1_bars[next_m1_to_process]
        survivors = []
        for trade in active:
            if _process_bar(
                trade,
                bar,
                spread=config.spread,
                stop_slippage=config.stop_slippage,
            ):
                completed.append(trade)
            else:
                survivors.append(trade)
        active = survivors
        next_m1_to_process += 1

    # Mark residual positions to market so signal-level PF is not biased upward by
    # silently dropping losing open positions.
    if active:
        final_bar = m1_bars[min(max(0, final_idx), len(m1_bars) - 1)]
        for trade in active:
            mark = (
                final_bar.close
                if trade.direction == "LONG"
                else final_bar.close + config.spread
            )
            _close_trade(
                trade,
                ts=final_bar.timestamp + timedelta(minutes=1),
                price=float(mark),
                reason="FORWARD_BUFFER_MARK",
            )
            completed.append(trade)
        active = []

    completed.sort(key=lambda trade: trade.entry_time)
    metrics = _metrics(completed)
    metrics.update(
        {
            "schema": "XAU_V375_PUBLIC_M1_CAUSAL_REPLAY_V1",
            "source_repo": SOURCE_REPO,
            "source_tokens": source_tokens,
            "source_format": "HISTDATA_GENERIC_ASCII_STYLE_BID_M1_FIXED_EST_NO_DST",
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "step_minutes": config.step_minutes,
            "spread_points": config.spread,
            "entry_slippage_points": config.entry_slippage,
            "stop_slippage_points": config.stop_slippage,
            "news_calendar_gate": "NOT_REPLAYED_PRICE_ONLY_CLEAR_ASSUMPTION",
            "macro_context": "V375_REACTION_LANE_USES_UNAVAILABLE_CONTEXT_IN_PRODUCTION",
            "accepted_signals": len(accepted_signals),
            "lane_signal_counts": lane_signal_counts,
            "scanner_reason_top": sorted(
                scan_reason_counts.items(), key=lambda item: item[1], reverse=True
            )[:20],
        }
    )
    return metrics, completed


def _parse_datetime(value: str, *, end: bool = False) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if len(value) == 10 and end:
        parsed = parsed + timedelta(days=1) - timedelta(seconds=1)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Causal price-only replay of the production V375 XAU DEMO entry selector on public M1 bid data.")
    parser.add_argument("--start", required=True, help="ISO date/datetime, e.g. 2025-01-01")
    parser.add_argument("--end", required=True, help="ISO date/datetime, e.g. 2025-12-31")
    parser.add_argument("--step-minutes", type=int, default=15, choices=[15, 30, 60, 120, 240])
    parser.add_argument("--spread", type=float, default=0.30, help="Fixed XAUUSD bid/ask spread in price points.")
    parser.add_argument("--entry-slippage", type=float, default=0.05)
    parser.add_argument("--stop-slippage", type=float, default=0.10)
    parser.add_argument("--cache-dir", default=".cache/xau_public_m1")
    parser.add_argument("--output", default="research/results/xau_v375_public_m1_replay.json")
    parser.add_argument("--trades-output", default="research/results/xau_v375_public_m1_trades.csv")
    args = parser.parse_args()

    start = _parse_datetime(args.start)
    end = _parse_datetime(args.end, end=True)
    if end <= start:
        raise SystemExit("--end must be after --start")
    config = ReplayConfig(
        start=start,
        end=end,
        step_minutes=args.step_minutes,
        spread=float(args.spread),
        entry_slippage=float(args.entry_slippage),
        stop_slippage=float(args.stop_slippage),
    )
    metrics, trades = run_replay(config, cache_dir=Path(args.cache_dir))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2, sort_keys=True, default=str) + "\n")

    trades_output = Path(args.trades_output)
    trades_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(trade) for trade in trades]).to_csv(trades_output, index=False)

    print("V375_PUBLIC_REPLAY_RESULT=" + json.dumps(metrics, sort_keys=True, default=str), flush=True)
    print(f"RESULT_JSON={output}", flush=True)
    print(f"TRADES_CSV={trades_output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
