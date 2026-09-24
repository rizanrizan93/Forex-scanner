from datetime import UTC, datetime, timedelta

from fx_scanner.research_xau_event_finalize_v193 import finalize
from fx_scanner.research_xau_event_supply_demand_post_v193 import (
    oos_signal_rows,
)


def _reaction(year: int, index: int, *, up: bool = True):
    at = datetime(year, 1, 1, 13, 30, tzinfo=UTC) + timedelta(days=index)
    return {
        "cluster_id": f"{year}-{index}",
        "scheduled_at": at.isoformat(),
        "family": "CPI",
        "attribution": "SINGLE_EVENT",
        "r15m_atr": 0.6 if up else -0.4,
        "surprise": {"sign": "POSITIVE"},
        "conditioning_key": "H4:BULL_STACK/HH_HL|H1:BULL_STACK/HH_HL",
        "conditioning": {
            "mtf": {
                "H1": {"market_structure": "HH_HL"},
                "H4": {"ema_stack": "BULL_STACK"},
            },
            "supply_demand": {
                "active_reaction_direction": None,
            },
        },
    }


def _full_reactions():
    rows = []
    for year in range(2012, 2027):
        for i in range(30):
            rows.append(_reaction(year, i, up=(i % 4 != 0)))
    return rows


def test_oos_signals_start_only_after_training_window():
    rows = _full_reactions()
    signals = oos_signal_rows(rows)
    assert signals
    assert min(int(row["test_year"]) for row in signals) == 2017
    assert max(int(row["test_year"]) for row in signals) == 2026
    assert all(row["predicted_direction"] in {"UP", "DOWN"} for row in signals)


def test_final_gate_requires_sd_coverage_and_parity():
    reactions = _full_reactions()
    signals = oos_signal_rows(reactions)
    sd_rows = [
        {
            **signal,
            "sd_alignment": "ALIGNED",
            "prediction_correct": signal.get("actual_direction")
            == signal.get("predicted_direction"),
        }
        for signal in signals
    ]
    base = {
        "decision": "REACTION_BACKFILL_WALKFORWARD_READY",
        "year_min": 2012,
        "year_max": 2026,
        "reaction_count": len(reactions),
        "reactions": reactions,
        "walk_forward": [],
        "eras": [],
        "execution_authority": False,
        "execution_influence": False,
        "promotion_authority": False,
    }
    shards = [
        {
            "year": year,
            "signal_count": sum(
                1 for row in signals if int(row["test_year"]) == year
            ),
            "evaluated_count": sum(
                1 for row in sd_rows if int(row["test_year"]) == year
            ),
            "coverage": 1.0,
        }
        for year in range(2017, 2027)
    ]

    passed = finalize(
        base=base,
        sd_rows=sd_rows,
        shards=shards,
        parity_gate={
            "passed": True,
            "decision": "PARITY_DESCRIPTIVE_AVAILABLE",
        },
    )
    assert passed["decision"] == "FULL_BACKFILL_RESEARCH_READY"
    assert passed["execution_authority"] is False
    assert passed["promotion_authority"] is False

    blocked = finalize(
        base=base,
        sd_rows=sd_rows,
        shards=shards,
        parity_gate={
            "passed": False,
            "decision": "PARITY_INSUFFICIENT",
        },
    )
    assert blocked["decision"] == "POST_WALKFORWARD_SD_OR_PARITY_INCOMPLETE"


def test_final_gate_blocks_low_sd_coverage():
    reactions = _full_reactions()
    signals = oos_signal_rows(reactions)
    sd_rows = [
        {
            **signal,
            "sd_alignment": "NO_ACTIVE_SD_DIRECTION",
            "prediction_correct": True,
        }
        for signal in signals[:50]
    ]
    base = {
        "decision": "REACTION_BACKFILL_WALKFORWARD_READY",
        "year_min": 2012,
        "year_max": 2026,
        "reaction_count": len(reactions),
        "reactions": reactions,
    }
    out = finalize(
        base=base,
        sd_rows=sd_rows,
        shards=[],
        parity_gate={
            "passed": True,
            "decision": "PARITY_DESCRIPTIVE_AVAILABLE",
        },
    )
    assert out["decision"] == "POST_WALKFORWARD_SD_OR_PARITY_INCOMPLETE"
