"""Read-only, fail-closed acceptance gate for the USD $10B Snowball R4 target.

A passing audit verifies a RESEARCH PROTOCOL, never a strategy or profit.
Challenger claims require a matching native V1 ledger and immutable prices.
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "research/bootstrap125_10b_four_phase_objective_r4.json"

def d(v):
    return Decimal(str(v))

def check_protocol(e):
    assert e["research_only"] and e["live_permissions"] is False
    assert e["currency"] == "USD"
    assert d(e["starting_cash"]) == Decimal(100)
    assert d(e["external_contributions"]) == 0
    assert d(e["goal_terminal_cash"]) == Decimal(10_000_000_000)
    b = e["baseline"]
    assert b["continuous_account"] is True and d(b["starting_cash"]) == 100
    assert d(b["terminal_balance"]) == Decimal("1662133293.08")
    assert d(b["max_floating_dd_pct"]) == Decimal("56.67")
    assert b["basket_count"] == 1047
    assert all(len(sha) == 64 and set(sha) <= set("abcdef0123456789")
               for sha in b["source_hashes"].values())
    phases = e["phases"]
    assert len(phases) == 4
    assert [p["index"] for p in phases] == [1, 2, 3, 4]
    assert [int(p["from_usd"]) for p in phases] == [100, 125, 250, 1000]
    assert [int(p["to_usd"]) for p in phases] == [125, 250, 1000, 10_000_000_000]
    for i, p in enumerate(phases):
        assert d(p["to_usd"]) / d(p["from_usd"]) == d(p["capital_growth_multiple"])
        if i:
            assert d(phases[i-1]["to_usd"]) == d(p["from_usd"])
    assert d(phases[0]["risk_reference"]["planned_max_risk_per_trade_pct"]) <= 8
    assert phases[0]["risk_reference"]["account_max_seed_positions"] == 1
    assert all(d(p["risk_reference"]["margin_cap_pct"]) <= 50 for p in phases)
    assert all(d(p["risk_reference"]["planned_combined_portfolio_risk_pct"]) <= Decimal("20.75")
               for p in phases[1:])
    req = e["required_data_for_valid_upgrade"]
    assert all(req[x] is True for x in (
        "same_corrected_prices_and_sha256",
        "same_native_engine_and_full_ledger_parity",
        "same_price_and_macro_point_in_time_eligibility",
        "annual_resets_2019_through_2026",
        "one_continuous_account_2019_through_cutoff",
        "no_lookahead",
        "broker_min_lot_and_margin",
        "stress_2024_seed_failure_must_be_addressed"))
    assert req["intraminute_paths"] == ["A","B"] and req["cost_scenarios"] == [1,2]
    evi = e["evidence_status"]
    assert all(v is False for k,v in evi.items() if isinstance(v,bool)),         "This protocol cannot assert new results or source parity without matching receipts."
    return {
        "status":"PROTOCOL_VALID; NO_MATCHED_CANDIDATE",
        "baseline_model_usd":b["terminal_balance"],
        "required_multiplier_to_goal":str(d(e["goal_terminal_cash"])/d(b["terminal_balance"])),
        "tier_labels":[f"${p['from_usd']:,} to ${p['to_usd']:,}" for p in phases],
        "tier_first_passage_results_available":False,
        "native_parity":False,"candidate_proven":False,"live_permission":False,
        "reason":"Missing exact source and native replay parity; rejected off-policy R3 cannot prove improvement."
    }

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--protocol",default=str(PATH))
    args=parser.parse_args()
    e=json.loads(Path(args.protocol).read_text())
    result=check_protocol(e)
    out=ROOT/"artifacts/bootstrap125_10b_r4_protocol_gate.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result,indent=2,allow_nan=False))
