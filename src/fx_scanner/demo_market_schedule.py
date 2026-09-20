from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .config import PairSpec, ProjectConfig

UTC = timezone.utc
CRYPTO_WEEKEND_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD"})


def weekday_demo_pairs(cfg: ProjectConfig) -> tuple[PairSpec, ...]:
    """Return the configured 20-instrument DEMO weekday universe unchanged."""
    if len(cfg.pairs) != 20:
        raise RuntimeError(
            f"DEMO_WEEKDAY_UNIVERSE_INVALID:count={len(cfg.pairs)} expected=20"
        )
    return tuple(cfg.pairs)


def weekend_crypto_pairs(cfg: ProjectConfig) -> tuple[PairSpec, ...]:
    """Return exactly the three authorized weekend crypto instruments.

    cTrader broker-session/tradability metadata remains authoritative. A weekend
    schedule does not imply that the broker CFD market is open.
    """
    configured = {
        pair.symbol: pair
        for pair in cfg.pairs
        if pair.symbol in CRYPTO_WEEKEND_SYMBOLS
    }
    symbols = set(configured)
    if symbols != CRYPTO_WEEKEND_SYMBOLS:
        missing = ",".join(sorted(CRYPTO_WEEKEND_SYMBOLS - symbols)) or "NONE"
        raise RuntimeError(f"WEEKEND_CRYPTO_UNIVERSE_INCOMPLETE:{missing}")
    return tuple(configured[symbol] for symbol in ("BTCUSD", "ETHUSD", "SOLUSD"))


def _forex_week_open_utc(current: datetime) -> bool:
    """Return the bounded calendar window used by the active Forex DEMO lane.

    The cTrader broker session/tradability check remains authoritative. This
    calendar only prevents the execution handoff from classifying Sunday
    evening UTC as a crypto-only weekend after the forex market has reopened.
    """
    weekday = current.weekday()  # Monday=0 ... Sunday=6
    hour = current.hour
    if weekday == 6:
        return hour >= 21
    if 0 <= weekday <= 3:
        return True
    if weekday == 4:
        return hour < 22
    return False


def apply_demo_market_schedule(
    cfg: ProjectConfig,
    *,
    now: datetime | None = None,
) -> tuple[ProjectConfig, str]:
    """Apply the DEMO market calendar without changing production policy.

    Forex-week window: Sunday 21:00 UTC through Friday 22:00 UTC. During that
    window the configured 20-instrument universe is available to the executor;
    broker session/tradability checks still fail closed per symbol. Outside that
    window scanning is restricted to BTCUSD, ETHUSD and SOLUSD.
    """
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("demo market schedule requires timezone-aware datetime")
    current = current.astimezone(UTC)

    if _forex_week_open_utc(current):
        return replace(cfg, pairs=weekday_demo_pairs(cfg)), "FOREX_WEEK_FULL_24X5"

    pairs = weekend_crypto_pairs(cfg)
    return replace(cfg, pairs=pairs), "WEEKEND_CRYPTO_BROKER_GATED"
