from __future__ import annotations

from dataclasses import replace

from . import demo_fresh_ready_handoff as base


def _xau_demo_policy(root=None):
    policy = base.load_demo_execution_policy(root)
    demo = dict(policy.demo_safety)
    demo["max_same_symbol_lots"] = min(
        1.50,
        float(demo["max_order_lots"]) * int(demo["max_same_symbol_positions"]),
    )
    return replace(policy, demo_safety=demo)


def main() -> int:
    """Run fresh DEMO handoff with a 0.50-lot ceiling; broker risk may only reduce it."""
    base.DEMO_ORDER_LOT_CAP_CEILING = 0.50
    original = base.load_demo_execution_policy

    def load_policy(root=None):
        policy = original(root)
        demo = dict(policy.demo_safety)
        demo["max_same_symbol_lots"] = min(
            1.50,
            float(demo["max_order_lots"]) * int(demo["max_same_symbol_positions"]),
        )
        return replace(policy, demo_safety=demo)

    base.load_demo_execution_policy = load_policy
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
