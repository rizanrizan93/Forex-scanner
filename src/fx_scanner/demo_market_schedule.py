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


def apply_demo_market_schedule(
    cfg: ProjectConfig,
    *,
    now: datetime | None = None,
) -> tuple[ProjectConfig, str]:
    """Apply the frozen DEMO calibration calendar without changing production.

    Monday-Friday UTC uses the configured 20-instrument discovery universe.
    Saturday-Sunday UTC restricts scanning to BTCUSD, ETHUSD and SOLUSD.
    Broker session/tradability checks remain authoritative and fail closed, so
    this calendar never forces an order into a closed market.
    """
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("demo market schedule requires timezone-aware datetime")
    current = current.astimezone(UTC)

    if current.weekday() < 5:
        return replace(cfg, pairs=weekday_demo_pairs(cfg)), "WEEKDAY_FULL_24X5"

    pairs = weekend_crypto_pairs(cfg)
    return replace(cfg, pairs=pairs), "WEEKEND_CRYPTO_BROKER_GATED"
