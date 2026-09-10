from copy import deepcopy
from pathlib import Path

from fx_scanner.demo_adaptive_calibration_v2 import (
    SYSTEM_BREAKEVENS,
    SYSTEM_LOSSES,
    SYSTEM_WINS,
    build_adaptive_calibration_v2_report,
)
from fx_scanner.demo_incremental_calibration import summarize_closed_events
from fx_scanner.demo_outcome_normalization import normalize_adaptive_profit_lock_outcomes

ROOT = Path(__file__).resolve().parents[1]
SIGNAL = "cfcf8d12-b72e-40a3-80f4-b772df8c1c73"


def _closed(*, signal=SIGNAL, position="41459318", observed="2026-09-10T09:46:30+00:00", net=0.20):
    return {
        "observed_at": observed,
        "signal_key": signal,
        "code": "SL_HIT",
        "payload": {
            "signal_id": signal,
            "position_id": position,
            "exit_type": "SL_HIT",
            "net_pnl_estimate": net,
            "symbol": "XAUUSD",
            "direction": "SHORT",
            "setup_type": "TREND_CONTINUATION",
            "entry_mode": "LEGACY",
            "confirmation": "LEGACY",
            "regime": "TRANSITION",
        },
    }


def _advanced(*, signal=SIGNAL, position="41459318", observed="2026-09-10T09:38:30+00:00"):
    return {
        "observed_at": observed,
        "signal_key": signal,
        "accepted": True,
        "payload": {
            "position_id": position,
            "execution": "ACKNOWLEDGED",
        },
    }


def test_exact_historical_adaptive_lock_is_overlaid_as_profit_without_mutating_source():
    source = _closed()
    original = deepcopy(source)
    rows = normalize_adaptive_profit_lock_outcomes(None, [source], adaptive_rows=[_advanced()])
    payload = rows[0]["payload"]

    assert source == original
    assert payload["historical_exit_type_original"] == "SL_HIT"
    assert payload["exit_type"] == "ADAPTIVE_PROFIT_LOCK_PROFIT"
    assert payload["trade_management_exit"] == "ADAPTIVE_PROFIT_LOCK"
    assert payload["outcome_normalized_for_calibration"] is True
    assert rows[0]["code"] == "ADAPTIVE_PROFIT_LOCK_PROFIT"


def test_wrong_position_or_post_close_advance_does_not_rewrite_history():
    wrong_position = normalize_adaptive_profit_lock_outcomes(
        None, [_closed()], adaptive_rows=[_advanced(position="999")]
    )
    late = normalize_adaptive_profit_lock_outcomes(
        None,
        [_closed()],
        adaptive_rows=[_advanced(observed="2026-09-10T10:00:00+00:00")],
    )
    assert wrong_position[0]["payload"]["exit_type"] == "SL_HIT"
    assert late[0]["payload"]["exit_type"] == "SL_HIT"


def test_overlay_changes_calibration_bucket_but_preserves_realized_net_pnl():
    rows = normalize_adaptive_profit_lock_outcomes(None, [_closed()], adaptive_rows=[_advanced()])
    summary = summarize_closed_events(rows)
    assert summary.overall.wins == 1
    assert summary.overall.losses == 0
    assert summary.overall.adaptive_lock_wins == 1
    assert summary.overall.sl_losses == 0
    assert summary.overall.net_pnl == 0.20


def test_adaptive_v2_recognizes_all_adaptive_lock_outcomes():
    assert "ADAPTIVE_PROFIT_LOCK_PROFIT" in SYSTEM_WINS
    assert "ADAPTIVE_PROFIT_LOCK_LOSS" in SYSTEM_LOSSES
    assert "ADAPTIVE_PROFIT_LOCK_BREAKEVEN" in SYSTEM_BREAKEVENS
    rows = normalize_adaptive_profit_lock_outcomes(None, [_closed()], adaptive_rows=[_advanced()])
    report = build_adaptive_calibration_v2_report(rows)
    assert report.decisive == 1
    assert sum(item.wins for item in report.cohorts.values()) == 1
    assert sum(item.losses for item in report.cohorts.values()) == 0


def test_discovery_uses_one_normalized_reader_for_all_calibration_reports():
    workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text(encoding="utf-8")
    assert "demo_normalized_calibration_runner incremental" in workflow
    assert "demo_normalized_calibration_runner adaptive-v2" in workflow
    assert "demo_normalized_calibration_runner comparison" in workflow
    assert "demo_normalized_calibration_runner loss-attribution" in workflow
    assert "python -m fx_scanner.demo_incremental_calibration\n" not in workflow
