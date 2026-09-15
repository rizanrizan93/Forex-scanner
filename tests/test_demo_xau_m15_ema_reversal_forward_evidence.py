from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_xau_m15_ema_reversal_forward_evidence import (
    TP1_R,
    TP2_R,
    evaluate_paper_exit,
    summarize_forward_metrics,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(index: int, *, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, 16, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=100,
        spread_avg=0.25,
        spread_max=0.40,
    )


def test_paper_exit_uses_conservative_stop_first_on_same_bar_ambiguity():
    rows = (
        _bar(0, open_=100.0, high=104.0, low=98.0, close=101.0),
    )
    outcome = evaluate_paper_exit(
        rows,
        entry_time=rows[0].timestamp,
        entry_price=100.0,
        stop=99.0,
        target=103.0,
    )
    assert outcome is not None
    assert outcome.reason == "STOP"
    assert outcome.result_r == pytest.approx(-1.0)
    assert outcome.mfe_r >= TP2_R
    assert outcome.tp1_touched is True


def test_paper_exit_resolves_tp2_at_three_r_without_invented_time_exit():
    rows = (
        _bar(0, open_=100.0, high=101.2, low=99.4, close=100.8),
        _bar(1, open_=100.8, high=103.2, low=100.5, close=103.0),
    )
    outcome = evaluate_paper_exit(
        rows,
        entry_time=rows[0].timestamp,
        entry_price=100.0,
        stop=99.0,
        target=103.0,
    )
    assert outcome is not None
    assert outcome.reason == "TP2"
    assert outcome.result_r == pytest.approx(TP2_R)
    assert outcome.tp1_touched is True
    assert outcome.mae_r == pytest.approx(-0.6)
    assert outcome.mfe_r == pytest.approx(3.2)


def test_paper_exit_remains_open_when_neither_structural_level_is_hit():
    rows = (
        _bar(0, open_=100.0, high=101.0, low=99.2, close=100.5),
        _bar(1, open_=100.5, high=101.4, low=99.5, close=101.0),
    )
    outcome = evaluate_paper_exit(
        rows,
        entry_time=rows[0].timestamp,
        entry_price=100.0,
        stop=99.0,
        target=103.0,
    )
    assert outcome is None


def test_forward_metrics_report_expectancy_pf_drawdown_and_tp1_touch_rate():
    rows = [
        {"result_r": 3.0, "mfe_r": 3.0},
        {"result_r": -1.0, "mfe_r": 0.7},
        {"result_r": -1.0, "mfe_r": 1.6},
        {"result_r": 3.0, "mfe_r": 3.2},
    ]
    metrics = summarize_forward_metrics(rows)
    assert metrics["closed_trades"] == 4
    assert metrics["wins"] == 2
    assert metrics["losses"] == 2
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["expectancy_r"] == pytest.approx(1.0)
    assert metrics["profit_factor"] == pytest.approx(3.0)
    assert metrics["max_drawdown_r"] == pytest.approx(2.0)
    assert metrics["tp1_touch_rate"] == pytest.approx(0.75)
    assert metrics["promotion_evidence_state"] == "COLLECTING"


def test_forward_metrics_never_grant_promotion_authority():
    rows = (
        [{"result_r": 3.0, "mfe_r": 3.0} for _ in range(24)]
        + [{"result_r": -1.0, "mfe_r": 0.5} for _ in range(6)]
    )
    metrics = summarize_forward_metrics(rows)
    assert metrics["closed_trades"] == 30
    assert metrics["profit_factor"] == pytest.approx(12.0)
    assert metrics["max_drawdown_r"] == pytest.approx(6.0)
    assert metrics["promotion_evidence_state"] == "EVIDENCE_POSITIVE_REVIEW_CANDIDATE"
    assert metrics["promotion_authority"] is False
