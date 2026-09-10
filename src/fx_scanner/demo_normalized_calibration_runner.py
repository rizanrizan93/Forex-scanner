from __future__ import annotations

import argparse
from typing import Callable

from .demo_outcome_normalization import normalize_adaptive_profit_lock_outcomes


def _install_incremental_overlay():
    from . import demo_incremental_calibration as incremental

    original = incremental._closed_events

    def normalized(store, *, account_id: str | None, limit: int = 500):
        rows = original(store, account_id=account_id, limit=limit)
        return normalize_adaptive_profit_lock_outcomes(store, rows)

    incremental._closed_events = normalized
    return incremental


def _install_adaptive_overlay():
    from . import demo_adaptive_calibration_v2_runtime as runtime

    original = runtime._closed_rows

    def normalized(store, *, account_ids: tuple[str, ...]):
        rows = original(store, account_ids=account_ids)
        return normalize_adaptive_profit_lock_outcomes(store, rows)

    runtime._closed_rows = normalized
    return runtime


def run_target(target: str) -> int:
    target = str(target).strip().lower()
    if target == "incremental":
        module = _install_incremental_overlay()
        return int(module.run())

    runtime = _install_adaptive_overlay()
    if target == "adaptive-v2":
        return int(runtime.run())
    if target == "comparison":
        # Import only after the shared runtime reader has been normalized so its
        # `from ... import _closed_rows` binding captures the normalized reader.
        from . import demo_strategy_outcome_comparison as comparison

        return int(comparison.run())
    if target == "loss-attribution":
        from . import demo_loss_attribution_v2_runtime as loss_attribution

        return int(loss_attribution.run())
    raise SystemExit(f"UNKNOWN_NORMALIZED_CALIBRATION_TARGET:{target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "target",
        choices=("incremental", "adaptive-v2", "comparison", "loss-attribution"),
    )
    args = parser.parse_args()
    return run_target(args.target)


if __name__ == "__main__":
    raise SystemExit(main())
