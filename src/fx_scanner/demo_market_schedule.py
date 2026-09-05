from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .config import PairSpec, ProjectConfig

UTC = timezone.utc
CRYPTO_WEEKEND_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD"})
DEMO_WEEKDAY_SUPPLEMENTAL_SYMBOLS = frozenset(
    {"EURCAD", "GBPCAD", "GBPCHF", "AUDCAD", "NZDJPY"}
)
_DEMO_WEEKDAY_SUPPLEMENTAL = (
    PairSpec(symbol="EURCAD", base="EUR", quote="CAD", pip_size=0.0001, tier="B"),
    PairSpec(symbol="GBPCAD", base="GBP", quote="CAD", pip_size=0.0001, tier="B"),
    PairSpec(symbol="GBPCHF", base="GBP", quote="CHF", pip_size=0.0001, tier="B"),
    PairSpec(symbol="AUDCAD", base="AUD", quote="CAD", pip_size=0.0001, tier="B"),
    PairSpec(symbol="NZDJPY", base="NZD", quote="JPY", pip_size=0.01, tier="B"),
)


def weekday_demo_pairs(cfg: ProjectConfig) -> tuple[PairSpec, ...]:
    """Return the frozen 25-instrument DEMO calibration universe.

    The five supplemental FX crosses are DEMO-only. Canonical production config
    remains unchanged until the user-authorized 100-trade calibration checkpoint.
    """
    configured = {pair.symbol: pair for pair in cfg.pairs}
    for pair in _DEMO_WEEKDAY_SUPPLEMENTAL:
        configured.setdefault(pair.symbol, pair)

    expected = {pair.symbol for pair in cfg.pairs} | DEMO_WEEKDAY_SUPPLEMENTAL_SYMBOLS
    symbols = set(configured)
    if symbols != expected or len(configured) != 25:
        raise RuntimeError(
            f"DEMO_WEEKDAY_UNIVERSE_INVALID:count={len(configured)} expected=25"
        )
    return tuple(configured[symbol] for symbol in configured)


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

    Monday-Friday UTC uses 25 DEMO instruments (canonical 20 plus five FX
    crosses). Saturday-Sunday UTC restricts scanning to BTCUSD, ETHUSD and
    SOLUSD, with broker session/tradability checks remaining fail-closed.
    """
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("demo market schedule requires timezone-aware datetime")
    current = current.astimezone(UTC)

    if current.weekday() < 5:
        return replace(cfg, pairs=weekday_demo_pairs(cfg)), "WEEKDAY_FULL_25_DEMO"

    pairs = weekend_crypto_pairs(cfg)
    return replace(cfg, pairs=pairs), "WEEKEND_CRYPTO_BROKER_GATED"
