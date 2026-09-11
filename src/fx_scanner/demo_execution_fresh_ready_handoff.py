from __future__ import annotations

from . import demo_fresh_ready_handoff as base
from .demo_five_core_router import PAIR_STRATEGY_IDS
from .storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)

_ORIGINAL_INSTALL_FRESH = base.install_fresh_execution_ready_handoff
_ALLOWED_SYMBOL = "XAUUSD"
_ALLOWED_STRATEGY = PAIR_STRATEGY_IDS[_ALLOWED_SYMBOL]


def _install_five_core_identity_filter(*, max_age_seconds: float) -> None:
    """Install freshness first, then fail-closed immutable strategy identity filtering."""
    _ORIGINAL_INSTALL_FRESH(max_age_seconds=max_age_seconds)
    original_list = SupabaseOperationalStore.list_execution_ready_signals

    def _five_core_rows(self, *, limit: int = 10):
        requested = max(1, int(limit))
        rows = tuple(original_list(self, limit=max(50, requested * 10)))
        candidate_ids = [
            str(row.get("id"))
            for row in rows
            if str(row.get("symbol") or "").upper().strip() == _ALLOWED_SYMBOL
            and row.get("id")
        ]
        if not candidate_ids:
            return ()

        try:
            response = (
                self.client.table("broker_order_events")
                .select("signal_key,code,event_type")
                .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
                .in_("signal_key", candidate_ids)
                .execute()
            )
        except Exception as exc:
            raise OperationalStoreUnavailable(
                f"five-core strategy identity read failed: {exc}"
            ) from exc

        allowed_ids = {
            str(row.get("signal_key"))
            for row in (response.data or [])
            if str(row.get("code") or "") == _ALLOWED_STRATEGY
        }
        filtered = tuple(
            row for row in rows
            if str(row.get("id")) in allowed_ids
            and str(row.get("symbol") or "").upper().strip() == _ALLOWED_SYMBOL
        )
        return filtered[:requested]

    SupabaseOperationalStore.list_execution_ready_signals = _five_core_rows


def main() -> int:
    """Execute only fresh XAUUSD D1_TSMOM_60_200 DEMO signals."""
    base.install_fresh_execution_ready_handoff = _install_five_core_identity_filter
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
