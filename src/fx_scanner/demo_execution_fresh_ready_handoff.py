from __future__ import annotations

from . import demo_fresh_ready_handoff as base
from .demo_impulse_retest_v2 import EXECUTION_SYMBOLS


def main() -> int:
    """Execute only fresh signals belonging to the pair-specific DEMO registry."""
    original_filter = base.fresh_execution_ready_rows

    def _execution_only_rows(rows, *, now, max_age_seconds, limit):
        filtered = tuple(
            row for row in rows
            if str(row.get("symbol") or "").upper().strip() in EXECUTION_SYMBOLS
        )
        return original_filter(
            filtered,
            now=now,
            max_age_seconds=max_age_seconds,
            limit=limit,
        )

    base.fresh_execution_ready_rows = _execution_only_rows
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
