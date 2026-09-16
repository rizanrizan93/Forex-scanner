from __future__ import annotations

from . import demo_fresh_ready_handoff as base
from .demo_euraud_gbpaud_forward_evidence import EURAUD_STRATEGY_ID, GBPAUD_STRATEGY_ID
from .demo_five_core_authority import EXECUTION_SYMBOLS
from .demo_five_core_router import PAIR_STRATEGY_IDS
from .demo_xau_expansion_v42 import STRATEGY_ID as XAU_EXPANSION_V42_STRATEGY_ID
from .demo_xau_m15_ema_reversal_recovery import STRATEGY_ID as XAU_M15_EMA_REVERSAL_STRATEGY_ID
from .demo_xau_m15_liquidity_sweep_fade import STRATEGY_ID as XAU_M15_SWEEP_FADE_STRATEGY_ID
from .storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)

_ORIGINAL_INSTALL_FRESH = base.install_fresh_execution_ready_handoff
_ALLOWED_STRATEGIES_BY_SYMBOL = {
    "XAUUSD": frozenset(
        {
            PAIR_STRATEGY_IDS["XAUUSD"],
            XAU_EXPANSION_V42_STRATEGY_ID,
            XAU_M15_EMA_REVERSAL_STRATEGY_ID,
            XAU_M15_SWEEP_FADE_STRATEGY_ID,
        }
    ),
    "USDJPY": frozenset({PAIR_STRATEGY_IDS["USDJPY"]}),
    "GBPUSD": frozenset({PAIR_STRATEGY_IDS["GBPUSD"]}),
    "EURAUD": frozenset({EURAUD_STRATEGY_ID}),
    "GBPAUD": frozenset({GBPAUD_STRATEGY_ID}),
}

# Backward-compatible XAU-only aliases retained for existing observers/tests.
# Runtime filtering below uses the pair-specific map instead.
_ALLOWED_SYMBOL = "XAUUSD"
_ALLOWED_STRATEGIES = _ALLOWED_STRATEGIES_BY_SYMBOL[_ALLOWED_SYMBOL]


def _install_five_core_identity_filter(*, max_age_seconds: float) -> None:
    """Install freshness, then fail-closed exact symbol/strategy filtering."""
    _ORIGINAL_INSTALL_FRESH(max_age_seconds=max_age_seconds)
    original_list = SupabaseOperationalStore.list_execution_ready_signals

    def _promoted_pair_rows(self, *, limit: int = 10):
        requested = max(1, int(limit))
        rows = tuple(original_list(self, limit=max(50, requested * 10)))
        candidate_ids = [
            str(row.get("id"))
            for row in rows
            if str(row.get("symbol") or "").upper().strip() in EXECUTION_SYMBOLS
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
                f"promoted strategy identity read failed: {exc}"
            ) from exc

        code_by_signal = {
            str(row.get("signal_key")): str(row.get("code") or "")
            for row in (response.data or [])
            if row.get("signal_key")
        }
        filtered = []
        for row in rows:
            signal_id = str(row.get("id") or "")
            symbol = str(row.get("symbol") or "").upper().strip()
            if not signal_id or symbol not in EXECUTION_SYMBOLS:
                continue
            allowed = _ALLOWED_STRATEGIES_BY_SYMBOL.get(symbol, frozenset())
            if code_by_signal.get(signal_id) in allowed:
                filtered.append(row)
        return tuple(filtered[:requested])

    SupabaseOperationalStore.list_execution_ready_signals = _promoted_pair_rows


def main() -> int:
    """Execute only fresh, exact authorized pair-specific DEMO strategy signals."""
    base.install_fresh_execution_ready_handoff = _install_five_core_identity_filter
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
