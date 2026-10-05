from __future__ import annotations

"""JSON-safe launcher for V388 execution calibration.

Keeps the V388 research logic unchanged while normalizing policy metadata from
Python sets to deterministic lists before shard/aggregate payloads are written.
"""

from xau_v388_execution_calibration import POLICIES, main


def _normalize_policy_metadata() -> None:
    for policy in POLICIES.values():
        states = policy.get("allowed_states")
        if isinstance(states, set):
            policy["allowed_states"] = sorted(str(state) for state in states)


if __name__ == "__main__":
    _normalize_policy_metadata()
    raise SystemExit(main())
