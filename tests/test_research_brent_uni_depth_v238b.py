from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fx_scanner.research_brent_uni_depth_v238b_aggregate import ERAS
from fx_scanner.research_brent_uni_depth_v238b_metrics import (
    build_excursion_metrics,
    summarize_excursions,
)
from fx_scanner.research_xau_zone_reversal_depth_v225 import DepthEpisode

ROOT = Path(__file__).resolve().parents[1]


def _episode() -> DepthEpisode:
    at = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    return DepthEpisode(
        zone_id="z1",
        timeframe="M15",
        zone_class="IMBALANCE",
        pattern="DBR",
        direction="LONG",
        available_at=at,
        touch_at=at,
        outcome_at=at,
        zone_low=99.0,
        zone_high=100.0,
        proximal=100.0,
        distal=99.0,
        atr_points=1.0,
        zone_width=1.0,
        outcome="STALL",
        reaction_hit=False,
        break_hit=False,
        max_depth_reached=0.2,
        turning_depth=None,
        turning_price=None,
        minutes_to_outcome=0.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.7,
        base_range_atr=0.8,
        structural_bos=False,
    )


def test_v238b_stop_first_same_bar_target_and_break() -> None:
    frame = pd.DataFrame(
        [
            {"timestamp": "2026-01-05T00:00:00Z", "open": 100.0, "high": 100.1, "low": 99.8, "close": 100.0},
            {"timestamp": "2026-01-05T00:01:00Z", "open": 100.0, "high": 101.2, "low": 98.8, "close": 98.9},
            {"timestamp": "2026-01-05T00:02:00Z", "open": 98.9, "high": 99.2, "low": 98.7, "close": 99.0},
        ]
    )
    row = build_excursion_metrics(frame, [_episode()])[0]
    assert row["break_before_horizon"] is True
    assert row["reaction_hits"]["0.25"] is False
    assert row["reaction_hits"]["0.50"] is False
    assert row["reaction_hits"]["1.00"] is False


def test_v238b_reaction_ladder_is_monotonic() -> None:
    frame = pd.DataFrame(
        [
            {"timestamp": "2026-01-05T00:00:00Z", "open": 100.0, "high": 100.1, "low": 99.8, "close": 100.0},
            {"timestamp": "2026-01-05T00:01:00Z", "open": 100.0, "high": 100.6, "low": 99.9, "close": 100.4},
            {"timestamp": "2026-01-05T00:02:00Z", "open": 100.4, "high": 100.9, "low": 100.2, "close": 100.8},
            {"timestamp": "2026-01-05T00:03:00Z", "open": 100.8, "high": 101.1, "low": 100.7, "close": 101.0},
            {"timestamp": "2026-01-05T04:00:00Z", "open": 101.0, "high": 101.0, "low": 101.0, "close": 101.0},
        ]
    )
    row = build_excursion_metrics(frame, [_episode()])[0]
    assert row["reaction_hits"] == {
        "0.25": True,
        "0.50": True,
        "0.75": True,
        "1.00": True,
    }
    summary = summarize_excursions([row])
    assert summary["reaction_rates"]["0.25"] >= summary["reaction_rates"]["0.50"]
    assert summary["reaction_rates"]["0.50"] >= summary["reaction_rates"]["0.75"]
    assert summary["reaction_rates"]["0.75"] >= summary["reaction_rates"]["1.00"]


def test_v238b_era_contract_and_shadow_only_source() -> None:
    assert ERAS == {
        "2012_2018": (2012, 2018),
        "2019_2024": (2019, 2024),
        "2025_2026": (2025, 2026),
    }
    source = (
        ROOT / "src/fx_scanner/research_brent_uni_depth_v238b_aggregate.py"
    ).read_text(encoding="utf-8")
    assert '"broker_symbol_status": "UNRESOLVED_FP_MARKETS_CTRADER"' in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_authority": False' in source
    assert '"live_execution_enabled": False' in source


def test_v238b_histdata_symbol_is_bco_usd() -> None:
    source = (
        ROOT / "src/fx_scanner/research_brent_histdata_download_v238b.py"
    ).read_text(encoding="utf-8")
    assert 'PAIR = "BCOUSD"' in source
    assert 'DISPLAY_INSTRUMENT = "BRENT"' in source


def test_v238b_truncated_horizon_is_censored_not_failed() -> None:
    frame = pd.DataFrame(
        [
            {"timestamp": "2026-01-05T00:00:00Z", "open": 100.0, "high": 100.1, "low": 99.8, "close": 100.0},
            {"timestamp": "2026-01-05T00:01:00Z", "open": 100.0, "high": 100.6, "low": 99.9, "close": 100.4},
        ]
    )
    row = build_excursion_metrics(frame, [_episode()])[0]
    assert row["complete"] is False
    assert row["censored"] is True
    assert summarize_excursions([row])["episodes"] == 0


def test_v238b_touch_bar_favorable_excursion_is_not_counted() -> None:
    frame = pd.DataFrame(
        [
            {"timestamp": "2026-01-05T00:00:00Z", "open": 100.0, "high": 101.2, "low": 99.8, "close": 100.0},
            {"timestamp": "2026-01-05T00:01:00Z", "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"timestamp": "2026-01-05T04:00:00Z", "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
        ]
    )
    row = build_excursion_metrics(frame, [_episode()])[0]
    assert row["complete"] is True
    assert row["reaction_hits"] == {
        "0.25": False,
        "0.50": False,
        "0.75": False,
        "1.00": False,
    }
    assert row["mfe_atr"] <= 0.1000000001
