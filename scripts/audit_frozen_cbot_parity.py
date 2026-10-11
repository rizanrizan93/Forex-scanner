#!/usr/bin/env python3
"""Static fail-closed audit for frozen XAU/EUR contracts and pinned cBot metadata.

This does not claim broker-fill equivalence and never submits orders.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "config/cbots/frozen_parity_v1.json"
SUPERVISED = ROOT / "config/frozen/xau_eur_supervised_12_5_v1.json"
FROZEN = {
    "XAUUSD": ROOT / "config/frozen/xauusd_raw_selected_v1.json",
    "EURUSD": ROOT / "config/frozen/eurusd_raw_selected_v3.json",
}


def canonical_hash(contract: dict) -> str:
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return sha256(payload).hexdigest()


def fail(code: str) -> None:
    print(f"PARITY_FAIL {code}")
    raise SystemExit(2)


def main() -> int:
    parity = json.loads(PARITY.read_text())
    supervised = json.loads(SUPERVISED.read_text())
    if parity.get("status") != "PINNED_FAIL_CLOSED":
        fail("PARITY_STATUS")
    if parity.get("execution_authority") != "NONE":
        fail("PARITY_EXECUTION_AUTHORITY")
    if supervised.get("status") != "ACTIVE_SCANNER_SUPERVISED":
        fail("SUPERVISED_STATUS")
    if supervised.get("execution_mode") != "LIVE_MANUAL_APPROVAL_ONLY":
        fail("SUPERVISED_EXECUTION_MODE")
    if supervised.get("unattended_live_execution") is not False:
        fail("SUPERVISED_UNATTENDED_LIVE")

    rows = {"XAUUSD": parity["xauusd"], "EURUSD": parity["eurusd"]}
    for symbol, path in FROZEN.items():
        frozen = json.loads(path.read_text())
        digest = canonical_hash(frozen["contract"])
        if frozen.get("contract_sha256") != digest:
            fail(f"{symbol}_FROZEN_INTERNAL_HASH")
        row = rows[symbol]
        if row.get("contract_sha256") != digest:
            fail(f"{symbol}_PARITY_HASH")
        deployed = supervised.get("symbols", {}).get(symbol, {})
        if deployed.get("source_contract_sha256") != digest:
            fail(f"{symbol}_DEPLOYMENT_HASH")
        if deployed.get("strategy_id") != frozen["contract"].get("strategy_id"):
            fail(f"{symbol}_STRATEGY_ID")

    xau = rows["XAUUSD"]
    if xau["technical"]["sell"] != {
        "source_group": 6,
        "research_id": "S10_DIRECTION_000183",
        "family": "SWEEP_CANDLE_CONFIRM",
        "confirmation": "STRICT_H1_M15",
        "parameter": 24,
        "macro": "DGS10_1D",
        "macro_rule": "ALLOW_SELL_ONLY_WHEN_LATEST_ELIGIBLE_DGS10_DELTA_GTE_0",
    }:
        fail("XAU_SELL_SIGNAL_PIN")
    if xau["technical"]["buy"] != {
        "source_group": 274,
        "research_id": "S10_DIRECTION_006616",
        "family": "REGRESSION_CHANNEL_REENTRY",
        "confirmation": "STRICT_H1_M15",
        "parameter": 48,
        "macro": "DFII10_1D",
        "macro_rule": "ALLOW_BUY_ONLY_WHEN_LATEST_ELIGIBLE_DFII10_DELTA_LTE_0",
    }:
        fail("XAU_BUY_SIGNAL_PIN")
    if xau["macro_event"]["planned_hold_intersection_window_relative_to_entry_minutes"] != [-30, 495]:
        fail("XAU_EVENT_WINDOW")
    if xau["macro_event"]["event_categories"] != ["NFP", "CPI", "PPI", "JOLTS", "ECI", "FOMC"]:
        fail("XAU_EVENT_CATEGORIES")

    eur = rows["EURUSD"]
    if eur["current_cbot"].get("execution_model") != "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1":
        fail("EUR_EXECUTION_MODEL")
    if eur["current_cbot"].get("checkpoint_schema") != 2:
        fail("EUR_CHECKPOINT_SCHEMA")

    print("PARITY_OK frozen_hashes=2 xau_macro_event=PINNED eur_batch=PINNED execution_authority=NONE")
    print(f"XAU_CBOT_EXPECTED_SHA256 {xau['current_cbot']['sha256']}")
    print(f"EUR_CBOT_EXPECTED_SHA256 {eur['current_cbot']['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
