"""RIZAN R6.2 — immutable, audited FOMC D1-vs-D5 research evidence.

NOT a live trading classifier. D1/D5 outcome counts taken from
the sealed 2019–2026 GitHub research reports, not fabricated
probabilities or a new optimized model. These are FOMC-event-conditioned
EX-POST historical association results, NOT a causal head-to-head
ranking across all trading dates.

Sources in research/fed_expectation_r1:
- FED_R4_REAL_YIELD_OIS_INFORMATION_SHOCK_RESULTS_2019_2026_ID.md
- FED_R3_80PCT_REAL_XAU_RESULTS_2019_2026_ID.md
Both use 69 FOMC events, shared cohorts, no as-of vendor quote archive.
"""
from __future__ import annotations

CONTRACT="RIZAN_R62_AUDITED_HORIZON_RESEARCH_ONLY_V1"
_REPLAY={
    "FOMC_OIS1Y_TIPS10_SP500_POLICY_LIKE":{
        "source":"R4_REPLAY_2019_2026_69_FOMC_EVENTS",
        "D1":{"BUY":(9,13),"SELL":(9,11)},
        "D5":{"BUY":(6,12),"SELL":(5,8)},
    },
    "FOMC_WINDOW_UST2Y_UST10Y_DXY":{
        "source":"R3_REPLAY_2019_2026_69_FOMC_EVENTS",
        "D1":{"BUY":(13,21),"SELL":(10,15)},
        "D5":{"BUY":(6,18),"SELL":(6,12)},
    },
}

def audited_horizon_context(*, market_direction="WAIT",daily_direction="WAIT",
                            fed_r4_direction="WAIT"):
    """Read-only UI evidence: do not promote a D1 signal to a D5 trade."""
    if any(x not in ("BUY","SELL","WAIT") for x in
           (market_direction,daily_direction,fed_r4_direction)):
        raise ValueError("UNRECOGNIZED_DIRECTION")
    rows=[]
    for model,entry in _REPLAY.items():
        for h in ("D1","D5"):
            for side in ("BUY","SELL"):
                wins,n=entry[h][side]
                rows.append({
                    "model":model,
                    "horizon":h,"side":side,
                    "wins":wins,"n_evaluable":n,
                    "direction_accuracy_pct":round(100*wins/n,2),
                    "dataset":entry["source"],
                    "genuine_point_in_time_tested":False,
                    "independent_prospective_validated":False,
                    "production_order_authority":False,
                })
    return {
        "contract":CONTRACT,
        "evidence":rows,
        "market_context_direction":market_direction,
        "daily_yield_lean":daily_direction,
        "verified_event_r4_watch":fed_r4_direction,
        "d1_event_research_watch":(
            fed_r4_direction if fed_r4_direction in ("BUY","SELL") else "WAIT"),
        "d1_context_only_not_backtest_approved":market_direction,
        "d3": "WAIT_NO_VERIFIED_THREE_DAY_MODEL",
        "d5": "WAIT_NO_VALIDATED_WEEK_LONG_DIRECTION",
        "daily_revalidation_required":True,
        "causal_winner_between_fed_and_yield_dxy":"UNDETERMINED",
        "event_calendar_scope":"ONLY_69_FOMC_EVENT_WINDOWS_NOT_ALL_DAYS",
        "market_context_model_was_historically_replayed":False,
        "status":"AUDITED_DESCRIPTIVE_ONLY",
        "bidirectional_80pct_validated":False,
        "execution_authority":False,
        "entry_permission":False,
        "note":"Event surprise can lead D1 context; yield and DXY are state checks, not a verified D5 directional forecast.",
    }
