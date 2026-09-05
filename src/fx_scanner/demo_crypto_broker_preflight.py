from __future__ import annotations

from datetime import datetime, timezone
from math import isclose

from .config import load_project_config
from .demo_market_schedule import CRYPTO_WEEKEND_SYMBOLS, weekend_crypto_pairs
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy

UTC = timezone.utc


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_CRYPTO_PREFLIGHT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_CRYPTO_PREFLIGHT_REQUIRE_DEMO")

    pairs = weekend_crypto_pairs(cfg)
    symbols = tuple(pair.symbol for pair in pairs)
    if set(symbols) != set(CRYPTO_WEEKEND_SYMBOLS):
        raise SystemExit("CTRADER_DEMO_CRYPTO_PREFLIGHT_UNIVERSE_INCOMPLETE")

    feed = build_ctrader_research_feed(policy, symbols)
    mismatches: list[str] = []
    try:
        now = datetime.now(tz=UTC)
        for pair in pairs:
            status = feed.market_status(pair.symbol, at=now)
            broker_pip = status.broker_pip_size
            pip_match = broker_pip is not None and isclose(
                float(pair.pip_size),
                float(broker_pip),
                rel_tol=0.0,
                abs_tol=max(1e-12, float(broker_pip) * 1e-9),
            )
            print(
                "CTRADER_DEMO_CRYPTO_CONTRACT "
                f"symbol={pair.symbol} configured_pip={float(pair.pip_size):.10g} "
                f"broker_pip={'NONE' if broker_pip is None else f'{float(broker_pip):.10g}'} "
                f"pip_match={int(pip_match)} digits={status.digits if status.digits is not None else 'NONE'} "
                f"trading_mode={status.trading_mode} schedule_tz={status.schedule_timezone or 'NONE'} "
                f"intervals={status.configured_intervals} open_now={int(status.open_for_new_positions)} "
                f"reason={status.reason}"
            )
            if not pip_match:
                mismatches.append(pair.symbol)
    finally:
        feed.close()

    if mismatches:
        raise SystemExit(
            "CTRADER_DEMO_CRYPTO_PIP_CONTRACT_MISMATCH:" + ",".join(sorted(mismatches))
        )
    print(
        "CTRADER_DEMO_CRYPTO_PREFLIGHT_OK "
        f"symbols={','.join(symbols)} broker_schedule=AUTHORITATIVE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
