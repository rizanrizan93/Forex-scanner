from pathlib import Path

from fx_scanner.research_xau_h1_event_stability_v61 import (
    DIAGNOSTIC_ONLY,
    EVENTS,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
)
from fx_scanner.research_xau_v47_frozen_validation_v48 import FROZEN_ROUTE

ROOT = Path(__file__).resolve().parents[1]


def test_v61_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v61_reports_all_break_events_without_preselection():
    assert FROZEN_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert EVENTS == ("BULL_MSS", "BULL_BOS", "BEAR_MSS", "BEAR_BOS")


def test_v61_does_not_filter_or_execute():
    src = (ROOT / "src/fx_scanner/research_xau_h1_event_stability_v61.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_h1_event_stability_v61_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"event_filter_applied": False' in src
    assert '"event_threshold_tuning": False' in src
    assert '"selection_uses_future_outcomes": False' in src
