from __future__ import annotations

import os

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_structural_profit_protector import _close_full_position, _raw_volume_by_position
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy


def run() -> int:
    """Close every currently open position on the configured cTrader DEMO account.

    This module is intentionally DEMO-only and is meant for an explicit one-shot
    liquidation request. It does not open, reverse, resize, or retry uncertain
    submissions.
    """
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CLOSE_ALL_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CLOSE_ALL_REQUIRE_DEMO")

    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("CLOSE_ALL_KILL_SWITCH_BLOCK")

    cfg = load_project_config(None)
    symbols = [pair.symbol for pair in cfg.pairs]
    _gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    closed = rejected = uncertain = skipped = 0
    try:
        before = capture_ctrader_demo_snapshot(session=session, store=None, phase="CLOSE_ALL_BEFORE")
        raw_volumes = _raw_volume_by_position(session)
        print(f"CTRADER_DEMO_CLOSE_ALL_START open_positions={len(before.positions)}")

        for position in before.positions:
            position_id = int(position.position_id)
            raw_volume = int(raw_volumes.get(position_id, 0) or 0)
            if raw_volume <= 0:
                skipped += 1
                print(
                    "CTRADER_DEMO_CLOSE_ALL_SKIP "
                    f"position_id={position_id} symbol={position.symbol} reason=RAW_VOLUME_UNAVAILABLE"
                )
                continue

            status, detail = _close_full_position(
                session,
                position_id=position_id,
                raw_volume=raw_volume,
            )
            print(
                "CTRADER_DEMO_CLOSE_ALL_RESULT "
                f"position_id={position_id} symbol={position.symbol} side={position.side} "
                f"raw_volume={raw_volume} status={status} detail={detail}"
            )
            if status == "CLOSED":
                closed += 1
            elif status == "REJECTED":
                rejected += 1
            else:
                uncertain += 1

        after = capture_ctrader_demo_snapshot(session=session, store=None, phase="CLOSE_ALL_AFTER")
        remaining = len(after.positions)
        print(
            "CTRADER_DEMO_CLOSE_ALL_DONE "
            f"closed={closed} rejected={rejected} uncertain={uncertain} "
            f"skipped={skipped} remaining={remaining}"
        )
        return 0 if remaining == 0 and rejected == 0 and uncertain == 0 and skipped == 0 else 2
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())
