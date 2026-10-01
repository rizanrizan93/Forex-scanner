from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import pandas as pd

from . import research_eurusd_v229_historical_v236 as engine

RESEARCH_VERSION = "BRENT_V229_HISTORICAL_EXECUTION_V238E_1"
ARTIFACT_CONTRACT = "BRENT_V229_HISTORICAL_EXECUTION_V238E_1_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "BRENT"
HISTDATA_PAIR = "BCOUSD"
BROKER_SHADOW_REFERENCE = "BRENT"

PIP_SIZE = 0.01
CHILD_LOT = 0.01
CONTRACT_UNITS_PER_LOT = 1_000.0
CHILD_UNITS = CHILD_LOT * CONTRACT_UNITS_PER_LOT
MAX_CHILDREN = 4

# FP Markets published average BRENT futures spread is 0.04 USD.
# With pipPosition=2 from cTrader DEMO metadata this is 4 pips.
BASE_SPREAD_PIPS = 4.0

# Research assumptions, not broker guarantees.
BASE_SLIPPAGE_PIPS = 1.0
COMMISSION_PIPS_ROUND_TRIP = 0.0
STRESS_SPREAD_MULTIPLIER = 1.50
STRESS_SLIPPAGE_MULTIPLIER = 2.00
MIN_STOP_PIPS = 5.0

OVERRIDES: dict[str, Any] = {
    "RESEARCH_VERSION": RESEARCH_VERSION,
    "ARTIFACT_CONTRACT": ARTIFACT_CONTRACT,
    "SYMBOL": SYMBOL,
    "PIP_SIZE": PIP_SIZE,
    "CHILD_LOT": CHILD_LOT,
    "CONTRACT_UNITS_PER_LOT": CONTRACT_UNITS_PER_LOT,
    "CHILD_UNITS": CHILD_UNITS,
    "MAX_CHILDREN": MAX_CHILDREN,
    "BASE_SPREAD_PIPS": BASE_SPREAD_PIPS,
    "BASE_SLIPPAGE_PIPS": BASE_SLIPPAGE_PIPS,
    "COMMISSION_PIPS_ROUND_TRIP": COMMISSION_PIPS_ROUND_TRIP,
    "STRESS_SPREAD_MULTIPLIER": STRESS_SPREAD_MULTIPLIER,
    "STRESS_SLIPPAGE_MULTIPLIER": STRESS_SLIPPAGE_MULTIPLIER,
    "MIN_STOP_PIPS": MIN_STOP_PIPS,
    "POLICY_EFFECT": POLICY_EFFECT,
    "EXECUTION_INFLUENCE": EXECUTION_INFLUENCE,
    "EXECUTION_AUTHORITY": EXECUTION_AUTHORITY,
    "LIVE_EXECUTION_ENABLED": LIVE_EXECUTION_ENABLED,
}


@contextmanager
def brent_engine_config() -> Iterator[None]:
    previous = {name: getattr(engine, name) for name in OVERRIDES}
    try:
        for name, value in OVERRIDES.items():
            setattr(engine, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(engine, name, value)


def _remap_plan_ids(payload: dict[str, Any]) -> dict[str, Any]:
    output = dict(payload)
    mapping: dict[str, str] = {}
    plans: list[dict[str, Any]] = []
    for raw in list(output.get("plans") or []):
        row = dict(raw)
        old = str(row.get("plan_id") or "")
        new = old.replace("V236:", "V238E:", 1) if old.startswith("V236:") else old
        mapping[old] = new
        row["plan_id"] = new
        plans.append(row)

    trades: list[dict[str, Any]] = []
    for raw in list(output.get("trades") or []):
        row = dict(raw)
        old = str(row.get("plan_id") or "")
        row["plan_id"] = mapping.get(
            old,
            old.replace("V236:", "V238E:", 1) if old.startswith("V236:") else old,
        )
        trades.append(row)

    output["plans"] = plans
    output["trades"] = trades
    return output


def simulate_year(price_m1: pd.DataFrame, *, target_year: int) -> dict[str, Any]:
    with brent_engine_config():
        raw = engine.simulate_year(price_m1, target_year=target_year)
    payload = _remap_plan_ids(raw)
    payload.update(
        {
            "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
            "research_version": RESEARCH_VERSION,
            "pair": SYMBOL,
            "historical_pair": HISTDATA_PAIR,
            "broker_shadow_reference": BROKER_SHADOW_REFERENCE,
            "source_identity_evidence": "V238D_3_WINDOW_CONSENSUS",
            "policy_effect": POLICY_EFFECT,
            "execution_influence": EXECUTION_INFLUENCE,
            "execution_authority": EXECUTION_AUTHORITY,
            "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        }
    )
    contract = dict(payload.get("execution_contract") or {})
    contract.update(
        {
            "child_lot": CHILD_LOT,
            "contract_units_per_lot": CONTRACT_UNITS_PER_LOT,
            "child_units": CHILD_UNITS,
            "max_children": MAX_CHILDREN,
            "frozen_prior": "XAU_V225_2",
            "brent_full_sample_calibration_used": False,
            "engine_source": "EURUSD_V236_REUSED_WITH_ISOLATED_BRENT_ECONOMICS",
        }
    )
    contract.pop("eurusd_full_sample_calibration_used", None)
    payload["execution_contract"] = contract
    payload["cost_contract"] = {
        "base_spread_pips": BASE_SPREAD_PIPS,
        "base_spread_usd": BASE_SPREAD_PIPS * PIP_SIZE,
        "base_slippage_pips": BASE_SLIPPAGE_PIPS,
        "base_slippage_usd": BASE_SLIPPAGE_PIPS * PIP_SIZE,
        "commission_pips_round_trip": COMMISSION_PIPS_ROUND_TRIP,
        "stress_spread_multiplier": STRESS_SPREAD_MULTIPLIER,
        "stress_slippage_multiplier": STRESS_SLIPPAGE_MULTIPLIER,
        "ambiguous_bar_policy": "STOP_FIRST",
        "cost_note": (
            "Spread is the FP Markets published BRENT futures average used as a "
            "historical research proxy. Slippage is a conservative V238E assumption. "
            "Commission=0 follows observed FP Markets cTrader DEMO symbol metadata."
        ),
    }
    return payload


def effective_trades(
    plans: Sequence[dict[str, Any]],
    trades: Sequence[dict[str, Any]],
):
    return engine.effective_trades(plans, trades)


def summarize_trades(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return engine.summarize_trades(rows)


def account_ledger(
    rows: Sequence[dict[str, Any]],
    *,
    initial_balance: float = 100.0,
    leverage: float = 100.0,
    margin_cap_fraction: float | None = None,
) -> dict[str, Any]:
    with brent_engine_config():
        return engine.account_ledger(
            rows,
            initial_balance=initial_balance,
            leverage=leverage,
            margin_cap_fraction=margin_cap_fraction,
        )


def simulate_limit_trade(**kwargs: Any) -> dict[str, Any]:
    with brent_engine_config():
        return engine._simulate_limit_trade(
            **kwargs,
            commission_pips=COMMISSION_PIPS_ROUND_TRIP,
        )


def price_arrays(frame: pd.DataFrame):
    return engine.price_arrays(frame)
