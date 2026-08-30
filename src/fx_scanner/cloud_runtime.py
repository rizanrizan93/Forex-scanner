from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic, sleep
from typing import Callable

from .config import ProjectConfig
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class CloudResearchReport:
    observed_at: datetime
    quotes_ok: int
    quotes_total: int
    mtf_ok: int
    mtf_total: int
    failures: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return self.quotes_ok == self.quotes_total and self.mtf_ok == self.mtf_total


class CTraderCloudResearchRuntime:
    """Linux-safe FP Markets cTrader research runtime; no MT5/order dependency."""

    def __init__(
        self, cfg: ProjectConfig, feed, store: SupabaseOperationalStore, *,
        historical_request_delay_seconds: float = 0.25,
        sleeper: Callable[[float], None] = sleep,
    ):
        if historical_request_delay_seconds < 0.20:
            raise ValueError("historical request pacing must stay <=5 requests/second")
        self.cfg = cfg
        self.feed = feed
        self.store = store
        self.historical_request_delay_seconds = historical_request_delay_seconds
        self.sleeper = sleeper

    def _bar_window(self, timeframe: str, count: int, as_of: datetime):
        seconds = int(self.cfg.timeframes[timeframe])
        lookback = timedelta(seconds=seconds * count * 3) + timedelta(days=2)
        return as_of - lookback, as_of

    def probe(self, *, include_mtf: bool) -> CloudResearchReport:
        observed_at = datetime.now(tz=UTC)
        failures: list[str] = []
        quotes_ok = 0
        mtf_ok = 0
        required = tuple(self.cfg.strategy["mtf"]["required_timeframes"])
        minimum = self.cfg.strategy["mtf"]["minimum_bars"]
        mtf_total = len(self.cfg.pairs) * len(required) if include_mtf else 0

        try:
            self.feed.heartbeat()
        except Exception as exc:
            failures.append(f"HEARTBEAT:{type(exc).__name__}:{exc}")

        for pair in self.cfg.pairs:
            try:
                self.feed.quote(pair.symbol)
                quotes_ok += 1
            except Exception as exc:
                failures.append(f"QUOTE:{pair.symbol}:{type(exc).__name__}:{exc}")

        if include_mtf:
            for pair in self.cfg.pairs:
                for timeframe in required:
                    count = int(minimum[timeframe]) + 12
                    start, end = self._bar_window(timeframe, count, observed_at)
                    try:
                        bars = self.feed.historical_bars(
                            pair.symbol, timeframe, from_time=start, to_time=end, count=count
                        )
                        if len(bars) < int(minimum[timeframe]):
                            failures.append(
                                f"BARS:{pair.symbol}:{timeframe}:{len(bars)}<{int(minimum[timeframe])}"
                            )
                        else:
                            mtf_ok += 1
                    except Exception as exc:
                        failures.append(
                            f"BARS:{pair.symbol}:{timeframe}:{type(exc).__name__}:{exc}"
                        )
                    self.sleeper(self.historical_request_delay_seconds)

        report = CloudResearchReport(
            observed_at, quotes_ok, len(self.cfg.pairs), mtf_ok, mtf_total, tuple(failures)
        )
        self.store.write_heartbeat(
            "ctrader_research_cloud", healthy=report.healthy, lag_seconds=0.0,
            details={
                "broker": "FP_MARKETS", "backend": "CTRADER", "role": "RESEARCH_ONLY",
                "quotes_ok": report.quotes_ok, "quotes_total": report.quotes_total,
                "mtf_ok": report.mtf_ok, "mtf_total": report.mtf_total,
                "failures": list(report.failures[:20]),
            },
        )
        return report

    def run_forever(self, *, heartbeat_seconds: float = 8.0, mtf_refresh_seconds: float = 900.0):
        if heartbeat_seconds <= 0 or heartbeat_seconds > 10:
            raise ValueError("heartbeat_seconds must be in (0,10]")
        if mtf_refresh_seconds < 60:
            raise ValueError("mtf_refresh_seconds must be >=60")
        next_mtf = 0.0
        while True:
            now = monotonic()
            include_mtf = now >= next_mtf
            report = self.probe(include_mtf=include_mtf)
            if include_mtf:
                next_mtf = monotonic() + mtf_refresh_seconds
            print(
                "CTRADER_CLOUD_OK "
                f"healthy={report.healthy} quotes={report.quotes_ok}/{report.quotes_total} "
                f"mtf={report.mtf_ok}/{report.mtf_total} failures={len(report.failures)}"
            )
            self.sleeper(heartbeat_seconds)
