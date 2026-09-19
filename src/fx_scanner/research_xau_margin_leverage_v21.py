from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any, Sequence

RESEARCH_VERSION = "XAU_MARGIN_LEVERAGE_V21"
ARTIFACT_CONTRACT = "XAU_MARGIN_LEVERAGE_V21_EVIDENCE_1"
SYMBOL = "XAUUSD"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
STARTING_BALANCE_USD = 100.0
LOT = 0.01


@dataclass(frozen=True, slots=True)
class LeverageTier:
    max_usd_volume: float
    leverage: float


@dataclass(frozen=True, slots=True)
class MarginSnapshot:
    reference_price: float
    contract_units_per_lot: float
    min_lot: float
    step_lot: float
    account_leverage: float | None
    max_account_leverage: float | None
    leverage_id: int | None
    dynamic_tiers: tuple[LeverageTier, ...]
    expected_margin_001_usd: float
    expected_margin_buy_001_usd: float
    expected_margin_sell_001_usd: float


def _effective_symbol_leverage(
    tiers: Sequence[LeverageTier],
    *,
    notional_usd: float,
) -> float | None:
    if not tiers:
        return None
    # Tiers are broker-provided and sorted by max USD exposure.
    for tier in tiers:
        if notional_usd <= float(tier.max_usd_volume):
            return float(tier.leverage)
    return float(tiers[-1].leverage)


def evaluate_margin(snapshot: MarginSnapshot) -> dict[str, Any]:
    notional = (
        float(snapshot.reference_price)
        * float(snapshot.contract_units_per_lot)
        * LOT
    )
    inferred_effective = (
        None
        if snapshot.expected_margin_001_usd <= 0
        else notional / float(snapshot.expected_margin_001_usd)
    )
    symbol_lev = _effective_symbol_leverage(
        snapshot.dynamic_tiers,
        notional_usd=notional,
    )
    reported_effective = None
    if snapshot.account_leverage and symbol_lev:
        reported_effective = min(snapshot.account_leverage, symbol_lev)
    elif snapshot.account_leverage:
        reported_effective = snapshot.account_leverage
    elif symbol_lev:
        reported_effective = symbol_lev

    required_for_open = notional / STARTING_BALANCE_USD
    required_for_20_free = notional / (STARTING_BALANCE_USD * 0.80)
    required_for_50_free = notional / (STARTING_BALANCE_USD * 0.50)

    hypothetical = {}
    for account_leverage in (30.0, 50.0, 100.0, 200.0, 500.0):
        effective = (
            account_leverage
            if symbol_lev is None
            else min(account_leverage, symbol_lev)
        )
        margin = notional / effective
        hypothetical[str(int(account_leverage))] = {
            "account_leverage": account_leverage,
            "symbol_leverage": symbol_lev,
            "effective_leverage": effective,
            "estimated_margin_usd": margin,
            "can_open_with_100": margin < STARTING_BALANCE_USD,
            "free_margin_before_pnl_usd": STARTING_BALANCE_USD - margin,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "symbol": SYMBOL,
        "lot": LOT,
        "starting_balance_usd": STARTING_BALANCE_USD,
        "snapshot": {
            **asdict(snapshot),
            "dynamic_tiers": [asdict(x) for x in snapshot.dynamic_tiers],
        },
        "notional_001_usd": notional,
        "inferred_effective_leverage_from_margin": inferred_effective,
        "symbol_leverage_for_001": symbol_lev,
        "reported_effective_leverage": reported_effective,
        "hard_feasibility": {
            "can_open_001_with_100_current": (
                snapshot.expected_margin_001_usd < STARTING_BALANCE_USD
            ),
            "free_margin_current_usd": (
                STARTING_BALANCE_USD - snapshot.expected_margin_001_usd
            ),
            "required_effective_leverage_to_open": required_for_open,
            "required_effective_leverage_for_20pct_free_margin": required_for_20_free,
            "required_effective_leverage_for_50pct_free_margin": required_for_50_free,
            "ceil_leverage_to_open": int(ceil(required_for_open)),
            "ceil_leverage_for_20pct_free_margin": int(ceil(required_for_20_free)),
            "ceil_leverage_for_50pct_free_margin": int(ceil(required_for_50_free)),
        },
        "hypothetical_account_leverage": hypothetical,
        "conclusion_code": (
            "CURRENT_ACCOUNT_001_FEASIBLE"
            if snapshot.expected_margin_001_usd < STARTING_BALANCE_USD
            else "CURRENT_ACCOUNT_001_MARGIN_BLOCKED"
        ),
        "note": (
            "This is a read-only DEMO margin diagnostic. Changing account leverage "
            "cannot exceed a lower symbol/dynamic-leverage cap. No order is submitted."
        ),
    }
