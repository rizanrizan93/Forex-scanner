from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .config import ProjectConfig

UTC = timezone.utc
CRYPTO_WEEKEND_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "RPLUSD", "LTCUSD"})


def apply_demo_market_schedule(
    cfg: ProjectConfig,
    *,
    now: datetime | None = None,
) -> tuple[ProjectConfig, str]:
    """Keep the full DEMO universe on weekdays and five crypto CFDs on weekends.

    Weekend selection is evaluated in UTC so GitHub Actions and scanner telemetry
    share one deterministic clock. This function only selects the candidate
    universe; cTrader symbol trading mode and broker session schedule remain
    authoritative before market data can be used for a decision.
    """
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("demo market schedule requires timezone-aware datetime")
    current = current.astimezone(UTC)

    if current.weekday() < 5:
        return cfg, "WEEKDAY_FULL_24X5"

    pairs = tuple(pair for pair in cfg.pairs if pair.symbol in CRYPTO_WEEKEND_SYMBOLS)
    symbols = {pair.symbol for pair in pairs}
    if symbols != CRYPTO_WEEKEND_SYMBOLS:
        missing = ",".join(sorted(CRYPTO_WEEKEND_SYMBOLS - symbols)) or "NONE"
        raise RuntimeError(f"WEEKEND_CRYPTO_UNIVERSE_INCOMPLETE:{missing}")
    # Keep the legacy mode identifier for downstream compatibility. The name no
    # longer grants a 24x7 assumption: broker session metadata is authoritative.
    return replace(cfg, pairs=pairs), "WEEKEND_CRYPTO_24X7"
