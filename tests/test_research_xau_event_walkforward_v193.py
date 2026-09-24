from datetime import UTC, datetime

from fx_scanner.research_xau_event_walkforward_v193 import (
    build_full_artifact,
    era_label,
    walk_forward,
)


def _row(year: int, i: int, *, up: bool, surprise: str = "POSITIVE"):
    return {
        "scheduled_at": datetime(year, 1, min(28, i + 1), 13, 30, tzinfo=UTC).isoformat(),
        "family": "CPI",
        "attribution": "SINGLE_EVENT",
        "r5m_atr": 0.3 if up else -0.2,
        "r15m_atr": 0.6 if up else -0.5,
        "whipsaw15m": False,
        "surprise": {"sign": surprise},
        "pre_context": {"trend": "BULL_STACK"},
        "conditioning": {
            "mtf": {
                "H1": {"market_structure": "HH_HL"},
                "H4": {"ema_stack": "BULL_STACK"},
            },
            "supply_demand": {"active_reaction_direction": "LONG"},
        },
    }


def test_era_labels_are_stable():
    assert era_label(2012) == "ERA_2012_2015"
    assert era_label(2018) == "ERA_2016_2019"
    assert era_label(2021) == "ERA_2020_2022"
    assert era_label(2026) == "ERA_2023_CURRENT"


def test_walk_forward_uses_only_prior_years():
    rows = []
    for year in range(2012, 2020):
        for i in range(25):
            rows.append(_row(year, i, up=True))
        for i in range(5):
            rows.append(_row(year, i + 10, up=False))
    result = walk_forward(rows, scheme="FAMILY", first_test_year=2017)
    assert result["folds"]
    first = result["folds"][0]
    assert first["test_year"] == 2017
    assert first["train_end"] == 2016
    assert first["eligible_predictions"] > 0
    assert first["directional_accuracy"] > 0.5


def test_structure_scheme_abstains_without_enough_matching_history():
    rows = [_row(2016, i, up=True) for i in range(10)]
    rows += [_row(2017, i, up=True) for i in range(10)]
    result = walk_forward(
        rows,
        scheme="FAMILY_SURPRISE_MARKET_STRUCTURE",
        first_test_year=2017,
    )
    assert result["folds"][0]["eligible_predictions"] == 0


def test_full_artifact_never_promotes_execution():
    rows = []
    for year in range(2012, 2027):
        for i in range(80):
            rows.append(_row(year, i % 28, up=(i % 4 != 0)))
    artifact = build_full_artifact(
        rows,
        [{"year": year, "reaction_count": 80} for year in range(2012, 2027)],
    )
    assert artifact["execution_authority"] is False
    assert artifact["promotion_authority"] is False
    assert artifact["year_min"] == 2012
    assert artifact["year_max"] == 2026
    assert artifact["decision"] == "REACTION_BACKFILL_WALKFORWARD_READY"
    assert artifact["supply_demand_conditioning"] == "PENDING_POST_WALK_FORWARD_STAGE"
