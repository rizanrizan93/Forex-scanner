from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .config import PairSpec, ProjectConfig

UTC = timezone.utc
CRYPTO_WEEKEND_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "RPLUSD", "LTCUSD"})
_CRYPTO_WEEKEND_SUPPLEMENTAL = (
    PairSpec(symbol="RPLUSD", base="RPL", quote="USD", pip_size=0.001, tier="A"),
    PairSpec(symbol="LTCUSD", base="LTC", quote="USD", pip_size=0.1, tier="A"),
)


def weekend_crypto_pairs(cfg: ProjectConfig) -> tuple[PairSpec, ...]:
    """Return the five-symbol crypto contract-check universe.

    This is only a candidate/preflight universe. It does not imply that any
    crypto CFD is tradable on Saturday or Sunday; cTrader broker-session
    metadata is authoritative for actual market availability.
    """
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
    """Keep weekdays unchanged and make weekend crypto explicitly broker-gated.

    Scheduled automation is restricted to broker weekdays by GitHub Actions.
    A manual weekend run may still inspect the five crypto CFD contracts, but
    it must not treat them as open merely because the underlying spot crypto
    market trades continuously. cTrader symbol trading mode and broker session
    schedule remain authoritative before market data or a decision can be used.
    """
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("demo market schedule requires timezone-aware datetime")
    current = current.astimezone(UTC)

    if current.weekday() < 5:
        return cfg, "WEEKDAY_FULL_24X5"

    pairs = weekend_crypto_pairs(cfg)
    return replace(cfg, pairs=pairs), "WEEKEND_CRYPTO_BROKER_GATED"
