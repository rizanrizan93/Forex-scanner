"""Frozen V1 primary consensus: aligned read-only candles, never cBot authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fx_scanner.xau_v1_primary_consensus import evaluate_consensus, _compare_candles

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def _bar_series(now, count, minutes, v1=False):
    rows = []
    for i in range(count):
        close_at = now - timedelta(minutes=(count - 1 - i) * minutes)
        start_at = close_at - timedelta(minutes=minutes)
        item = {
            "open": 3900., "high": 3901., "low": 3899.,
            "close": 3900., "volume": 1.,
        }
        if v1:
            item["timestamp"] = start_at.isoformat()
        else:
            item["closed_at"] = close_at.isoformat()
        rows.append(item)
    return rows


def _v1_market(now=NOW):
    return {
        "contract": "RIZAN_BOOTSTRAP125_MARKET_READONLY_V1",
        "account_suffix": "7903",
        "execution_authority": False, "read_only": True,
        "observed_at": now.isoformat(),
        "bars": {"XAUUSD": {
            "H1": _bar_series(now, 11, 60, True),
            "M5": _bar_series(now, 7, 5, True),
        }},
    }


def _research_market(now=NOW):
    return {
        "contract": "RIZAN_XAU_CLOSED_CANDLES_READONLY_V1",
        "account_suffix": "7903", "symbol": "XAUUSD",
        "source": "CTRADER_MARKET_DATA_READ_ONLY",
        "execution_authority": False, "execution_influence": False,
        "as_of": now.isoformat(),
        "bars": {"H1": _bar_series(now, 210, 60),
                 "M15": _bar_series(now, 70, 15),
                 "M5": _bar_series(now, 30, 5)},
    }


def _v1_report(direction="BUY", family="XAU compression M5"):
    return {"symbols": {"XAUUSD": {
        "market_valid": True, "phase": "GROWTH",
        "bias": direction + " LEBIH KUAT" if direction else "NETRAL / SETUP BELUM JELAS",
        "BUY": {"score": 100 if direction == "BUY" else 0, "family": family},
        "SELL": {"score": 100 if direction == "SELL" else 0, "family": family},
    }}}


def _research_report(direction="BUY"):
    return {
        "execution_authority": False, "order_enabled": False,
        "preferred": direction if direction else "WAIT",
        "BUY": {"score": 78, "state": "ARMED_SHADOW" if direction == "BUY" else "NO_SETUP"},
        "SELL": {"score": 72, "state": "ARMED_SHADOW" if direction == "SELL" else "NO_SETUP"},
    }


def _eval(direction="BUY", research_direction="BUY", *, market=None, candles=None,
          now=NOW, phase="GROWTH", family="XAU compression M5", connected=True):
    return evaluate_consensus(
        v1_report=_v1_report(direction, family),
        research_report=_research_report(research_direction),
        v1_market=market if market is not None else _v1_market(now),
        research_candles=candles if candles is not None else _research_market(now),
        phase=phase, now=now, bridge_ready=connected,
    )


def test_concordant_buy_and_sell_research_aligned_with_frozen_v1():
    for direction in ("BUY", "SELL"):
        result = _eval(direction, direction)
        assert result["state"] == "SELARAS_" + direction
        assert result["alignment"] == "ALIGNED"
        assert result["v1_direction"] == direction
        assert result["research_direction"] == direction
        assert set(result["candle_comparison"]) == {"H1", "M5"}
        assert result["scores_comparable"] is False
        assert result["native_entry_readiness"] == "UNKNOWN"
        assert result["execution_authority"] is False
        assert result["order_enabled"] is False
        assert result["native_signal"] == "NOT_EVALUATED"
        assert result["missed_order_verdict"] == "NOT_EVALUATED"


def test_opposing_direction_explains_conflict_but_cannot_override_v1():
    result = _eval("BUY", "SELL")
    assert result["state"] == "KONFLIK"
    assert result["v1_direction"] == "BUY"
    assert result["research_direction"] == "SELL"
    assert result["primary_strategy"] == "RIZAN_BOOTSTRAP125_V1_FROZEN_20261114"
    assert result["native_entry_readiness"] == "UNKNOWN"


def test_research_wait_is_not_relabelled_conflict():
    result = _eval("BUY", None)
    assert result["state"] == "V1_BIAS_ONLY"
    assert result["research_direction"] == "WAIT"


def test_research_only_does_not_promote_frozen_strategy():
    result = _eval(None, "SELL")
    assert result["state"] == "RESEARCH_ONLY"
    assert result["v1_direction"] == "WAIT"
    assert result["native_entry_readiness"] == "UNKNOWN"


def test_stale_original_market_blocks_consensus_not_frozen_positions():
    market = _v1_market(NOW - timedelta(minutes=5))
    result = _eval("BUY", "BUY", market=market)
    assert result["state"] == "WAIT_ALIGNMENT"
    assert result["alignment"] == "WAIT_V1_MARKET"


def test_m5_timestamp_mismatch_blocks_consensus_even_with_matching_scores():
    market = _research_market()
    # Replace last closed bar timestamp with a later close; original validity fails.
    market["bars"]["M5"][-1]["closed_at"] = (NOW + timedelta(minutes=5)).isoformat()
    result = _eval("BUY", "BUY", candles=market)
    assert result["state"] == "WAIT_ALIGNMENT"
    assert result["alignment"] == "WAIT_CANDLE"


def test_price_mismatch_no_false_consensus():
    market = _research_market()
    bar = market["bars"]["M5"][-1]
    bar.update(open=3915., high=3925., low=3905., close=3920.)
    result = _eval("BUY", "BUY", candles=market)
    assert result["state"] == "WAIT_ALIGNMENT"
    assert result["alignment"] == "WAIT_PRICE_MISMATCH"


def test_wrong_account_untrusted_or_execution_authority_rejected():
    for mutate in ("account", "authority", "source"):
        market = _research_market()
        if mutate == "account":
            market["account_suffix"] = "4480"
        elif mutate == "authority":
            market["execution_authority"] = True
        else:
            market["source"] = "UNVERIFIED"
        result = _eval("BUY", "BUY", candles=market)
        assert result["state"] == "WAIT_ALIGNMENT"


def test_seed_xau_is_inactive_even_when_candle_patterns_are_ideal():
    result = _eval("BUY", "BUY", phase="SEED")
    assert result["state"] == "V1_PHASE_NOT_GROWTH"
    assert result["order_enabled"] is False


def test_out_of_window_v1_family_never_called_entry_ready():
    early = datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)
    result = _eval("BUY", "BUY", now=early, family="XAU compression M5")
    assert result["state"] == "V1_OUTSIDE_SESSION"
    assert result["v1_session"] == "CLOSED"


def test_research_authority_or_weak_state_never_creates_direction():
    research = _research_report("BUY")
    research["execution_authority"] = True
    result = evaluate_consensus(
        v1_report=_v1_report("BUY"), research_report=research,
        v1_market=_v1_market(), research_candles=_research_market(),
        phase="GROWTH", now=NOW,
    )
    assert result["state"] == "V1_BIAS_ONLY"
    assert result["research_direction"] == "WAIT"
