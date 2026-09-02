from __future__ import annotations

import sys

from . import strategy
from .cli import main


_original_choose_scalp_setup = strategy._choose_scalp_setup


def _choose_scalp_setup_with_liquidity_fvg(direction, h1, m15, liquidity):
    """DEMO-only compatibility fix for technical scalping.

    The canonical scalp selector historically required the *current* M15 FVG,
    while the trade-plan builder intentionally accepts still-open/partial FVGs
    from the durable liquidity map.  That mismatch can produce a valid plan and
    high technical conviction while leaving setup_type=NONE.  Preserve the
    original selector first, then allow the same durable FVG evidence already
    accepted by the trade-plan builder.
    """
    selected = _original_choose_scalp_setup(direction, h1, m15, liquidity)
    if selected is not None:
        return selected

    if strategy._htf_conflict(direction, h1, m15):
        return None
    if (strategy._directional_structure_score(h1, direction) or 0.0) < 55.0:
        return None
    if (strategy._directional_structure_score(m15, direction) or 0.0) < 55.0:
        return None

    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    durable_fvg = any(
        gap.direction == wanted and gap.status in {"OPEN", "PARTIAL"}
        for gap in liquidity.fvgs
    )
    if durable_fvg:
        return strategy.SetupType.TREND_CONTINUATION
    return None


def run() -> int:
    strategy._choose_scalp_setup = _choose_scalp_setup_with_liquidity_fvg
    sys.argv = [sys.argv[0], "ctrader-signal-producer"]
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
