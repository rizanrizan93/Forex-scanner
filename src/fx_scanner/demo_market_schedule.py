from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .config import PairSpec, ProjectConfig

UTC = timezone.utc
CRYPTO_WEEKEND_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "RPLUSD", "LTCUSD"})
_CRYPTO_WEEKEND_SUPPLEMENTAL = (
    PairSpec(symbol="RPLUSD", base="RPL", quote="USD", pip_size=0.0001, tier="A"),
    PairSpec(symbol="LTCUSD", base="LTC", quote="USD", pip_size=0.01, tier="A"),
)


def weekend_crypto_pairs(cfg: ProjectConfig) -> tuple[PairSpec, ...]:
    """Return the five-symbol weekend DEMO universe without changing weekdays."""
    configured = {
        pair.symbol: pair
        for pair in cfg.pairs
        if pair.symbol in CRYPTO_WEEKEND_SYMBOLS
    }
    for pair in _CRYPTO_WEEKEND_SUPPLEMENTAL:
        configured.setdefault(pair.symbol, pair)
    symbols = set(configured)
    if symbols != CRYPTO_WEEKEND_SYMBOLS:
        missing = ",".join(sorted(CRYPTO_WEEKEND_SYMBOLS - symbols)) or "NONE"
        raise RuntimeError(f"WEEKEND_CRYPTO_UNIVERSE_INCOMPLETE:{missing}")
    return tuple(configured[symbol] for symbol in ("BTCUSD", "ETHUSD", "SOLUSD", "RPLUSD", "LTCUSD"))


def apply_demo_market_schedule(
    cfg: ProjectConfig,
    *,
    now: datetime | None = None,
) -> tuple[ProjectConfig, str]:
    """Keep the proven 20-symbol weekday universe and five crypto CFDs on weekends.

    Weekend selection is evaluated in UTC so GitHub Actions and scanner telemetry
    share one deterministic clock. RPLUSD and LTCUSD are DEMO weekend overlays,
    so weekday ranking/calibration denominators stay unchanged. cTrader symbol
    trading mode and broker session schedule remain authoritative before market
    data can be used for a decision.
    """
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("demo market schedule requires timezone-aware datetime")
    current = current.astimezone(UTC)

    if current.weekday() < 5:
        return cfg, "WEEKDAY_FULL_24X5"

    pairs = weekend_crypto_pairs(cfg)
    # Keep the legacy mode identifier for downstream compatibility. The name no
    # longer grants a 24x7 assumption: broker session metadata is authoritative.
    return replace(cfg, pairs=pairs), "WEEKEND_CRYPTO_24X7"
