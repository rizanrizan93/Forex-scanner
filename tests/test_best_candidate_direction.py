"""Primary best-side board must remain causal, side-specific and read-only."""
from datetime import UTC, datetime, timedelta

from fx_scanner.best_candidate_direction import VERSIONS, select


NOW = datetime(2026, 11, 23, 12, 40, tzinfo=UTC)


def source(direction, *, tf="H4", hours=4, state="RESEARCH_SHADOW"):
    return {
        "direction": direction, "state": state, "execution_authority": False,
        "issued": (NOW - timedelta(minutes=2)).isoformat(),
        "target": (NOW + timedelta(hours=hours)).isoformat(),
        "buy_active": direction == "BUY",
        "sell_active": direction == "SELL",
    }


def packet():
    best = {"H1": source("BUY", tf="H1", hours=1), "H4": source("SELL")}
    r294 = source("WAIT", state="MODEL_ABSTAIN")
    r281 = {"D1": source("SELL", hours=24, state="RECONSTRUCTED_SHADOW")}
    return best, r294, r281


def test_best_h1_h4_independent_and_d1_w1_never_use_r281_sell():
    best, r294, r281 = packet()
    out = select(best, r294, r281, now=NOW)
    assert out["H1"]["direction"] == "BUY"
    assert out["H4"]["direction"] == "SELL"
    assert out["H4"]["sources"] == {"BUY": "R29.2", "SELL": "R11"}
    assert out["D1"]["direction"] == "WAIT"  # R18 not inferred
    assert out["W1"]["direction"] == "WAIT"  # R27/R24 not inferred
    assert all(row["execution_authority"] is False for row in out.values())
    assert VERSIONS["H1"] == {"BUY": "R25", "SELL": "R11"}


def test_r292_h4_buy_is_preferred_to_r25_when_current():
    best, r294, r281 = packet()
    best["H4"]["direction"] = "WAIT"
    best["H4"]["sell_active"] = False
    best["H4"]["buy_active"] = False
    r294["direction"] = "BUY"
    r294["state"] = "RESEARCH_SHADOW"
    out = select(best, r294, r281, now=NOW)
    assert out["H4"]["direction"] == "BUY"
    assert out["H4"]["status"] == "ACTIVE_SHADOW"


def test_h4_buy_sell_conflict_is_wait_not_chosen_by_accuracy():
    best, r294, r281 = packet()
    r294["direction"] = "BUY"
    r294["state"] = "RESEARCH_SHADOW"
    out = select(best, r294, r281, now=NOW)
    assert out["H4"]["direction"] == "WAIT"
    assert out["H4"]["reason"] == "SIDE_CONFLICT"


def test_missing_or_expired_opposing_h4_head_is_fail_closed():
    best, r294, r281 = packet()
    assert select(best, {}, r281, now=NOW)["H4"]["status"] == "WAIT_DATA"
    r294["target"] = NOW.isoformat()
    assert select(best, r294, r281, now=NOW)["H4"]["direction"] == "WAIT"
    best["H4"]["target"] = NOW.isoformat()
    r294["target"] = (NOW + timedelta(hours=4)).isoformat()
    assert select(best, r294, r281, now=NOW)["H4"]["direction"] == "WAIT"


def test_h1_expired_does_not_fallback_to_r281_signal():
    best, r294, r281 = packet()
    best["H1"]["target"] = NOW.isoformat()
    r281["H1"] = source("BUY", hours=1, state="RECONSTRUCTED_SHADOW")
    assert select(best, r294, r281, now=NOW)["H1"]["direction"] == "WAIT"


def test_only_proven_d1_buy_is_research_partial_head():
    best, r294, r281 = packet()
    r281["D1"]["direction"] = "BUY"
    out = select(best, r294, r281, now=NOW)
    assert out["D1"]["direction"] == "BUY"
    assert out["D1"]["status"] == "PARTIAL_HEAD"
    assert "R18" in out["D1"]["reason"]
    r281["D1"]["execution_authority"] = True
    assert select(best, r294, r281, now=NOW)["D1"]["direction"] == "WAIT"


def test_unvalidated_d1_w1_are_not_auto_filled_by_historical_winrates():
    best, r294, r281 = packet()
    r281["W1"] = source("BUY", hours=168, state="RECONSTRUCTED_SHADOW")
    out = select(best, r294, r281, now=NOW)
    assert out["W1"]["status"] == "NOT_INFERENCED"
    assert out["W1"]["direction"] == "WAIT"


def test_best_side_dashboard_renders_primary_first():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "src/fx_scanner/frozen_direction_research_dashboard.py"
    content = path.read_text()
    assert "select_best_candidate_direction" in content
    assert content.index("### Direction utama · kandidat terbaik") < content.index("### R28.1 baseline")
