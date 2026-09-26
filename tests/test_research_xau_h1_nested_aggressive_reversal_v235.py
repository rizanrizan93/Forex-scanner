from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.research_xau_h1_nested_aggressive_reversal_v235_aggregate import (
    _select,
    _variant_rows,
)
from fx_scanner.research_xau_h1_nested_aggressive_reversal_v235_year import (
    _eligible_episode,
)


def _order(
    *,
    variant_id: str,
    year: int,
    pnl: float,
    index: int,
    episode: int,
    slot: str = "MID",
    target_atr: float = 0.5,
) -> dict:
    fill = datetime(year, 1, 2, tzinfo=UTC) + timedelta(hours=index * 3)
    return {
        "variant_id": variant_id,
        "year": year,
        "gross_points": pnl,
        "fill_at": fill.isoformat(),
        "exit_at": (fill + timedelta(minutes=30)).isoformat(),
        "entry": 2000.0,
        "margin_usd_1_to_100": 20.0,
        "direction": "LONG",
        "trade_key": f"{variant_id}-{year}-{index}",
        "episode_key": f"{year}-{episode}",
        "slot": slot,
        "target_atr": target_atr,
        "exit_reason": "TP" if pnl > 0 else "SL",
    }


def test_v235_episode_gate_is_exact_h1_long_multi_htf_aggressive() -> None:
    good = SimpleNamespace(
        timeframe="H1",
        direction="LONG",
        nesting_bucket="MULTI_HTF_NESTING",
        approach_state="AGGRESSIVE_APPROACH",
        touch_at=datetime(2025, 1, 3, tzinfo=UTC),
    )
    assert _eligible_episode(good, year=2025) is True

    for field, value in (
        ("timeframe", "H4"),
        ("direction", "SHORT"),
        ("nesting_bucket", "ONE_HTF_PARENT"),
        ("approach_state", "CONTROLLED_APPROACH"),
    ):
        bad = SimpleNamespace(**good.__dict__)
        setattr(bad, field, value)
        assert _eligible_episode(bad, year=2025) is False


def test_v235_selection_cannot_use_later_eras() -> None:
    rows = []
    # Train winner A: passes 2012-2018 and loses catastrophically later.
    for year in range(2012, 2019):
        for idx in range(12):
            rows.append(
                _order(
                    variant_id="V235_MID_T050",
                    year=year,
                    pnl=2.0 if idx < 8 else -1.0,
                    index=idx,
                    episode=idx,
                )
            )
    for year in range(2019, 2027):
        for idx in range(12):
            rows.append(
                _order(
                    variant_id="V235_MID_T050",
                    year=year,
                    pnl=-5.0,
                    index=idx,
                    episode=idx,
                )
            )

    # B is wonderful only after the train period and must not be selected.
    for year in range(2012, 2019):
        for idx in range(12):
            rows.append(
                _order(
                    variant_id="V235_PROXIMAL_T050",
                    year=year,
                    pnl=1.0 if idx < 3 else -1.0,
                    index=idx,
                    episode=idx,
                    slot="PROXIMAL",
                )
            )
    for year in range(2019, 2027):
        for idx in range(12):
            rows.append(
                _order(
                    variant_id="V235_PROXIMAL_T050",
                    year=year,
                    pnl=10.0,
                    index=idx,
                    episode=idx,
                    slot="PROXIMAL",
                )
            )

    selected, evidence = _select(rows)
    assert selected == "V235_MID_T050"
    assert evidence["V235_MID_T050"]["selection_passed"] is True
    assert evidence["V235_PROXIMAL_T050"]["selection_passed"] is False


def test_v235_ladder_contains_both_entry_slots_only_for_same_target() -> None:
    rows = [
        _order(
            variant_id="V235_PROXIMAL_T050",
            year=2020,
            pnl=1.0,
            index=0,
            episode=1,
            slot="PROXIMAL",
            target_atr=0.5,
        ),
        _order(
            variant_id="V235_MID_T050",
            year=2020,
            pnl=2.0,
            index=1,
            episode=1,
            slot="MID",
            target_atr=0.5,
        ),
        _order(
            variant_id="V235_MID_T075",
            year=2020,
            pnl=3.0,
            index=2,
            episode=1,
            slot="MID",
            target_atr=0.75,
        ),
    ]
    selected = _variant_rows(rows, "LADDER_T050")
    assert len(selected) == 2
    assert {row["slot"] for row in selected} == {"PROXIMAL", "MID"}
    assert all(abs(float(row["target_atr"]) - 0.5) < 1e-12 for row in selected)
