from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.demo_xau_v375_reaction_executor import _behavioral_block_reason
from fx_scanner.xau_afiq_behavioral_layer_v376 import evaluate_afiq_behavioral_layer


def bar(ts: datetime, o: float, h: float, l: float, c: float) -> SimpleNamespace:
    return SimpleNamespace(timestamp=ts, open=o, high=h, low=l, close=c)


def base_sd(*, direction: str = "LONG", early: bool = False, reclaim_at: datetime | None = None) -> dict:
    zone = {
        "zone_id": "MAIN",
        "timeframe": "H4",
        "direction": direction,
        "low": 100.0,
        "high": 102.0,
        "proximal": 101.5 if direction == "LONG" else 100.5,
        "distal": 100.0 if direction == "LONG" else 102.0,
        "atr": 2.0,
        "condition": "FRESH",
        "main_reversal_eligible": True,
        "main_reversal_score": 92.0,
        "score": 92.0,
        "lifecycle": {"freshness": "FRESH"},
    }
    micro = {
        "early_confirmed": early,
        "confirmed": False,
        "reclaim_at": reclaim_at.isoformat() if reclaim_at else None,
        "confirmation_close": 101.6 if direction == "LONG" else 100.4,
        "local_atr": 0.5,
    }
    return {
        "price_now": 101.0,
        "market_structure": {
            "H4": {"state": "BULLISH_BREAK" if direction == "LONG" else "BEARISH_BREAK"},
            "H1": {"state": "BULLISH_RANGE" if direction == "LONG" else "BEARISH_RANGE"},
        },
        "expected_reversal_direction": direction,
        "decision_zone": zone,
        "main_reversal_zone": zone,
        "refinement_zone": {},
        "active_zones": [zone],
        "structural_path": {"checkpoints": []},
        "liquidity_map": {"liquidity_candidates": []},
        "structural_destination": {
            "zone_id": "DEST",
            "timeframe": "H4",
            "direction": "SHORT" if direction == "LONG" else "LONG",
            "low": 110.0 if direction == "LONG" else 90.0,
            "high": 112.0 if direction == "LONG" else 92.0,
            "price": 110.0 if direction == "LONG" else 92.0,
        },
        "nearest_roadblock": {},
        "micro_confirmation": micro,
    }


def test_acceptance_beyond_distal_blocks_demo() -> None:
    now = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    m15 = []
    for i in range(30):
        ts = now - timedelta(minutes=15 * (30 - i))
        if i < 26:
            m15.append(bar(ts, 103.0, 103.4, 102.4, 103.0))
        elif i == 26:
            m15.append(bar(ts, 101.0, 102.0, 99.7, 100.2))
        else:
            m15.append(bar(ts, 99.8, 100.1, 99.0, 99.4))

    payload = evaluate_afiq_behavioral_layer(
        sd_evaluation=base_sd(),
        bars_m15=m15,
        bars_m5=(),
        as_of=now,
        price_now=99.4,
    )

    assert payload["acceptance_rejection"]["state"] == "ACCEPTANCE_AGAINST_THESIS"
    assert payload["demo_entry_gate"] == "BLOCK_BEHAVIORAL_FAILURE"
    assert payload["hard_block_reason"] == "ACTIVE_ZONE_ACCEPTED_BEYOND_DISTAL"


def test_main_zone_is_classified_as_main_reversal() -> None:
    now = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    m15 = []
    start = now - timedelta(minutes=15 * 60)
    price = 99.0
    for i in range(60):
        ts = start + timedelta(minutes=15 * i)
        price += 0.08
        m15.append(bar(ts, price - 0.05, price + 0.15, price - 0.15, price))

    payload = evaluate_afiq_behavioral_layer(
        sd_evaluation=base_sd(),
        bars_m15=m15,
        bars_m5=(),
        as_of=now,
        price_now=103.0,
    )

    assert payload["active_zone_role"]["role"] == "MAIN_REVERSAL"
    assert payload["regime"]["state"] in {"TREND_EXPANSION_UP", "CLIMAX_EXHAUSTION_UP"}
    assert payload["demo_entry_gate"] in {
        "ALLOW_WITH_EXISTING_GATES",
        "WATCH_M30_CONFLICT",
        "WATCH_REACTION_STALLED",
    }


def test_response_timer_failure_blocks_demo() -> None:
    now = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    reclaim_at = now - timedelta(minutes=40)
    sd = base_sd(early=True, reclaim_at=reclaim_at)

    m15 = []
    for i in range(30):
        ts = now - timedelta(minutes=15 * (30 - i))
        m15.append(bar(ts, 101.0, 102.0, 100.2, 101.2))

    m5 = []
    for i in range(12):
        ts = reclaim_at - timedelta(minutes=5) + timedelta(minutes=5 * i)
        # Adverse move >0.75 local ATR from 101.6 confirmation close.
        m5.append(bar(ts, 101.4, 101.5, 100.9, 101.0))

    payload = evaluate_afiq_behavioral_layer(
        sd_evaluation=sd,
        bars_m15=m15,
        bars_m5=m5,
        as_of=now,
        price_now=101.0,
    )

    assert payload["response_timer"]["state"] == "REACTION_FAILED"
    assert payload["demo_entry_gate"] == "BLOCK_BEHAVIORAL_FAILURE"
    assert payload["hard_block_reason"] == "EARLY_REACTION_FAILED_RESPONSE_TIMER"


def test_v375_reads_v376_hard_block() -> None:
    heartbeat = {
        "details": {
            "evaluation": {
                "afiq_behavioral": {
                    "demo_entry_gate": "BLOCK_BEHAVIORAL_FAILURE",
                    "hard_block_reason": "ACTIVE_ZONE_ACCEPTED_BEYOND_DISTAL",
                }
            }
        }
    }
    assert _behavioral_block_reason(heartbeat) == (
        "AFIQ_BEHAVIOR_BLOCK:ACTIVE_ZONE_ACCEPTED_BEYOND_DISTAL"
    )


def test_v375_defaults_to_existing_gates_when_behavior_layer_missing() -> None:
    assert _behavioral_block_reason({"details": {"evaluation": {}}}) is None
