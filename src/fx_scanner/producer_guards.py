from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt
from statistics import median
from typing import Any, Mapping, Sequence

from .config import ProjectConfig
from .models import Bar, ensure_utc
from .providers.news import evaluate_news_block
from .ranking import PairRank
from .technical import atr, true_ranges


@dataclass(frozen=True, slots=True)
class GuardResolution:
    flags_by_symbol: Mapping[str, Mapping[str, bool]]
    missing_by_symbol: Mapping[str, tuple[str, ...]]
    calendar_error: str | None


def _bundle_quality_ok(
    cfg: ProjectConfig,
    symbol: str,
    bundle: Mapping[str, Sequence[Bar]],
) -> bool:
    minimum = cfg.strategy["mtf"]["minimum_bars"]
    for tf in cfg.strategy["mtf"]["required_timeframes"]:
        bars = tuple(bundle.get(tf, ()))
        if len(bars) < int(minimum[tf]):
            return False
        previous = None
        for bar in bars:
            if bar.symbol != symbol or bar.timeframe != tf:
                return False
            if previous is not None and bar.timestamp <= previous:
                return False
            previous = bar.timestamp
            values = (bar.open, bar.high, bar.low, bar.close)
            if any(not isfinite(float(value)) or float(value) <= 0 for value in values):
                return False
            if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                return False
            if bar.high < bar.low:
                return False
    return True


def _volatility_block(
    cfg: ProjectConfig,
    bundle: Mapping[str, Sequence[Bar]],
) -> bool | None:
    bars = list(bundle.get("M5", ()))
    if len(bars) < max(20, int(cfg.strategy["mtf"]["atr_period"]) + 2):
        return None
    try:
        ranges = true_ranges(bars)
        sample = ranges[-min(60, len(ranges)):]
        baseline = float(median(sample))
        current_atr = float(atr(bars, int(cfg.strategy["mtf"]["atr_period"])))
    except Exception:
        return None
    if baseline <= 0 or not isfinite(baseline) or not isfinite(current_atr):
        return None
    ratio = current_atr / baseline
    guard_cfg = cfg.strategy["guard_evidence"]
    lower = float(guard_cfg["volatility_atr_median_min"])
    upper = float(guard_cfg["volatility_atr_median_max"])
    return bool(ratio < lower or ratio > upper)


def _directional_returns(
    bars: Sequence[Bar],
    *,
    direction: str,
    lookback: int,
) -> dict[datetime, float]:
    sign = 1.0 if direction == "LONG" else -1.0
    sample = tuple(bars)[-(lookback + 1):]
    out: dict[datetime, float] = {}
    for previous, current in zip(sample, sample[1:]):
        if previous.close <= 0:
            continue
        value = sign * (float(current.close) / float(previous.close) - 1.0)
        if isfinite(value):
            out[current.timestamp] = value
    return out


def _pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) != len(b) or len(a) < 2:
        return None
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    da = [value - mean_a for value in a]
    db = [value - mean_b for value in b]
    var_a = sum(value * value for value in da)
    var_b = sum(value * value for value in db)
    if var_a <= 0 or var_b <= 0:
        return None
    covariance = sum(x * y for x, y in zip(da, db))
    value = covariance / sqrt(var_a * var_b)
    if not isfinite(value):
        return None
    return max(-1.0, min(1.0, value))


def _aligned_directional_correlation(
    candidate: PairRank,
    peer: PairRank,
    bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    *,
    lookback: int,
) -> float | None:
    candidate_bundle = bars_by_symbol.get(candidate.symbol)
    peer_bundle = bars_by_symbol.get(peer.symbol)
    if not candidate_bundle or not peer_bundle:
        return None
    candidate_returns = _directional_returns(
        candidate_bundle.get("H1", ()),
        direction=candidate.direction,
        lookback=lookback,
    )
    peer_returns = _directional_returns(
        peer_bundle.get("H1", ()),
        direction=peer.direction,
        lookback=lookback,
    )
    common = sorted(set(candidate_returns).intersection(peer_returns))
    minimum = max(20, int(lookback * 0.80))
    if len(common) < minimum:
        return None
    return _pearson(
        [candidate_returns[ts] for ts in common[-lookback:]],
        [peer_returns[ts] for ts in common[-lookback:]],
    )


class ProductionGuardResolver:
    """Resolve only hard guards backed by current evidence.

    Internal structure/stale/chase/RR guards remain owned by strategy.py.
    Any external guard that cannot be evaluated is omitted, allowing the
    existing hard-guard evaluator to emit GUARD_INPUT_MISSING:* and fail closed.
    """

    EXTERNAL_GUARDS = (
        "NEWS_BLOCK",
        "SPREAD_BLOCK",
        "VOLATILITY_BLOCK",
        "CORRELATION_BLOCK",
        "RISK_BLOCK",
        "DATA_QUALITY_BLOCK",
    )

    def __init__(
        self,
        cfg: ProjectConfig,
        feed: Any,
        *,
        calendar_provider: Any | None,
        max_quote_age_seconds: float,
        max_spread_pips: float,
        demo_max_risk_pct: float,
    ):
        if max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")
        if max_spread_pips <= 0:
            raise ValueError("max_spread_pips must be positive")
        if demo_max_risk_pct <= 0:
            raise ValueError("demo_max_risk_pct must be positive")
        self.cfg = cfg
        self.feed = feed
        self.calendar_provider = calendar_provider
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        self.max_spread_pips = float(max_spread_pips)
        self.demo_max_risk_pct = float(demo_max_risk_pct)

    def resolve(
        self,
        *,
        candidates: Sequence[PairRank],
        bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
        as_of: datetime,
    ) -> GuardResolution:
        now = ensure_utc(as_of)
        calendar = None
        calendar_error = None
        if self.calendar_provider is not None:
            try:
                calendar = self.calendar_provider.fetch(now=now)
            except Exception as exc:
                calendar_error = f"{type(exc).__name__}:{exc}"

        output: dict[str, Mapping[str, bool]] = {}
        missing: dict[str, tuple[str, ...]] = {}
        guard_cfg = self.cfg.strategy["guard_evidence"]
        correlation_lookback = int(guard_cfg["correlation_lookback_bars"])
        correlation_threshold = float(guard_cfg["correlation_threshold"])

        for index, candidate in enumerate(candidates):
            flags: dict[str, bool] = {}
            pair = self.cfg.pair_map[candidate.symbol]
            bundle = bars_by_symbol.get(candidate.symbol)

            if calendar is not None:
                news = evaluate_news_block(
                    now=now,
                    currencies=(pair.base, pair.quote),
                    events=calendar.events,
                    pre_block_minutes=int(guard_cfg["news_pre_block_minutes"]),
                    post_block_minutes=int(guard_cfg["news_post_block_minutes"]),
                )
                flags["NEWS_BLOCK"] = bool(news.blocked)

            quote_ok = False
            try:
                quote = self.feed.quote(candidate.symbol)
                age = (now - quote.timestamp).total_seconds()
                quote_ok = (
                    -1.0 <= age <= self.max_quote_age_seconds
                    and float(quote.bid) > 0
                    and float(quote.ask) >= float(quote.bid)
                )
                if quote_ok:
                    spread_pips = (
                        float(quote.ask) - float(quote.bid)
                    ) / float(pair.pip_size)
                    flags["SPREAD_BLOCK"] = bool(
                        spread_pips > self.max_spread_pips
                    )
            except Exception:
                quote_ok = False

            if bundle is not None:
                quality_ok = _bundle_quality_ok(self.cfg, candidate.symbol, bundle)
                flags["DATA_QUALITY_BLOCK"] = bool(not (quality_ok and quote_ok))
                volatility = _volatility_block(self.cfg, bundle)
                if volatility is not None:
                    flags["VOLATILITY_BLOCK"] = volatility

            risk_pct = float(self.cfg.risk["risk_per_trade_pct"])
            max_research_risk = float(self.cfg.risk["max_risk_per_trade_pct"])
            flags["RISK_BLOCK"] = bool(
                risk_pct > min(max_research_risk, self.demo_max_risk_pct)
            )

            if index == 0:
                flags["CORRELATION_BLOCK"] = False
            else:
                observed = False
                blocked = False
                for peer in candidates[:index]:
                    correlation = _aligned_directional_correlation(
                        candidate,
                        peer,
                        bars_by_symbol,
                        lookback=correlation_lookback,
                    )
                    if correlation is None:
                        continue
                    observed = True
                    if correlation >= correlation_threshold:
                        blocked = True
                        break
                if observed:
                    flags["CORRELATION_BLOCK"] = blocked

            missing_names = tuple(
                name for name in self.EXTERNAL_GUARDS if name not in flags
            )
            output[candidate.symbol] = flags
            missing[candidate.symbol] = missing_names

        return GuardResolution(
            flags_by_symbol=output,
            missing_by_symbol=missing,
            calendar_error=calendar_error,
        )
