from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_technical_strategy import (
    _demo_directional_structure_score,
    _demo_setup_recognition_structure_valid,
    _demo_setup_type,
    _demo_structure_conflict,
    _early_structure_valid,
    _fresh_directional_fvg,
)
from fx_scanner.liquidity import FairValueGap
from fx_scanner.strategy import SetupType

UTC = timezone.utc


def _displacement(direction: str, *, valid: bool = True):
    return SimpleNamespace(direction=direction, valid=valid)


def _fvg(direction: str, *, valid: bool = True):
    return SimpleNamespace(direction=direction, valid=valid)


def _snapshot(
    trend: str,
    bos: str | None = None,
    mss: str | None = None,
    displacement=None,
    fvg=None,
    sweep=None,
):
    return SimpleNamespace(
        trend=trend,
        bos=bos,
        mss=mss,
        displacement=displacement,
        fvg=fvg,
        sweep=sweep,
    )


def test_fresh_directional_fvg_is_visible_before_chase(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_FVG_MAX_AGE_MINUTES", "90")
    now = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    gap = FairValueGap(
        "BULLISH",
        100.0,
        101.0,
        now - timedelta(minutes=45),
        "OPEN",
        0.0,
    )
    base = SimpleNamespace(
        direction="LONG",
        liquidity=SimpleNamespace(fvgs=(gap,)),
    )
    assert _fresh_directional_fvg(base, as_of=now) is True


def test_stale_directional_fvg_is_not_used_for_early_entry(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_FVG_MAX_AGE_MINUTES", "90")
    now = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    gap = FairValueGap(
        "BULLISH",
        100.0,
        101.0,
        now - timedelta(minutes=91),
        "OPEN",
        0.0,
    )
    base = SimpleNamespace(
        direction="LONG",
        liquidity=SimpleNamespace(fvgs=(gap,)),
    )
    assert _fresh_directional_fvg(base, as_of=now) is False


def test_h1_m15_structure_can_prearm_before_m5_trigger():
    base = SimpleNamespace(
        direction="LONG",
        h1=_snapshot("BULLISH"),
        m15=_snapshot("BULLISH"),
    )
    assert _early_structure_valid(base) is True


def test_lagging_m15_trend_is_not_hard_conflict_after_bullish_bos_displacement():
    base = SimpleNamespace(
        direction="LONG",
        h1=_snapshot("BULLISH"),
        m15=_snapshot(
            "BEARISH",
            bos="BULLISH",
            displacement=_displacement("BULLISH"),
        ),
    )
    assert _demo_structure_conflict(base) is False
    assert _demo_directional_structure_score(base.m15, "LONG") == 65.0
    assert _early_structure_valid(base) is True


def test_lagging_h1_trend_is_not_hard_conflict_after_bearish_bos_displacement():
    base = SimpleNamespace(
        direction="SHORT",
        h1=_snapshot(
            "BULLISH",
            bos="BEARISH",
            displacement=_displacement("BEARISH"),
        ),
        m15=_snapshot("BEARISH"),
    )
    assert _demo_structure_conflict(base) is False
    assert _demo_directional_structure_score(base.h1, "SHORT") == 65.0
    assert _early_structure_valid(base) is True


def test_opposite_trend_without_confirmed_transition_remains_diagnostic_conflict():
    base = SimpleNamespace(
        direction="LONG",
        h1=_snapshot("BULLISH"),
        m15=_snapshot("BEARISH", bos="BULLISH"),
    )
    assert _demo_structure_conflict(base) is True
    assert _early_structure_valid(base) is False


def test_invalid_or_opposite_displacement_cannot_hide_diagnostic_conflict():
    invalid = SimpleNamespace(
        direction="LONG",
        h1=_snapshot("BULLISH"),
        m15=_snapshot(
            "BEARISH",
            bos="BULLISH",
            displacement=_displacement("BULLISH", valid=False),
        ),
    )
    wrong_direction = SimpleNamespace(
        direction="LONG",
        h1=_snapshot("BULLISH"),
        m15=_snapshot(
            "BEARISH",
            bos="BULLISH",
            displacement=_displacement("BEARISH"),
        ),
    )
    assert _demo_structure_conflict(invalid) is True
    assert _demo_structure_conflict(wrong_direction) is True


def test_transition_can_name_setup_without_waiting_for_fresh_fvg():
    now = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    base = SimpleNamespace(
        direction="LONG",
        setup_type=None,
        h1=_snapshot("BULLISH"),
        m15=_snapshot(
            "RANGE",
            bos="BULLISH",
            displacement=_displacement("BULLISH"),
        ),
        liquidity=SimpleNamespace(fvgs=()),
    )
    assert _demo_setup_recognition_structure_valid(base) is True
    assert _demo_setup_type(base, as_of=now) == SetupType.TREND_CONTINUATION


def test_recognition_grade_setup_does_not_imply_execution_grade_structure(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_FVG_MAX_AGE_MINUTES", "90")
    now = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    gap = FairValueGap(
        "BULLISH",
        100.0,
        101.0,
        now - timedelta(minutes=20),
        "OPEN",
        0.0,
    )
    base = SimpleNamespace(
        direction="LONG",
        setup_type=None,
        h1=_snapshot("RANGE"),
        m15=_snapshot("RANGE"),
        liquidity=SimpleNamespace(fvgs=(gap,)),
    )
    assert _demo_setup_recognition_structure_valid(base) is True
    assert _early_structure_valid(base) is False
    assert _demo_setup_type(base, as_of=now) == SetupType.TREND_CONTINUATION


def test_setup_remains_none_below_score_policy_without_directional_pattern_evidence():
    now = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    base = SimpleNamespace(
        direction="LONG",
        setup_type=None,
        h1=_snapshot("RANGE"),
        m15=_snapshot("RANGE"),
        liquidity=SimpleNamespace(fvgs=()),
    )
    assert _demo_setup_recognition_structure_valid(base) is True
    assert _demo_setup_type(base, as_of=now) is None


def test_demo_runtime_uses_score_driven_setup_and_keeps_other_guards():
    source = Path("src/fx_scanner/demo_technical_strategy.py").read_text()
    workflow = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    strategy = Path("config/strategy.yaml").read_text()

    assert 'computed["STRUCTURE_INVALID"] = False' in source
    assert 'computed["CHASE_BLOCK"]' in source
    assert 'computed["RR_BLOCK"]' in source
    assert "score_driven_setup" in source
    assert "and score_driven_setup" in source
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in workflow
    assert "chase_block_atr: 0.50" in strategy


def test_supervisor_uses_two_minute_non_overlap_dispatch():
    text = Path(".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    assert "seq 1 30" in text
    assert "sleep 120" in text
    assert "SUPERVISOR_SKIP_BUSY" in text
    assert "overlap=DISABLED" in text


def test_pipeline_keeps_chase_limit_and_enables_fresh_fvg_profile():
    workflow = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    strategy = Path("config/strategy.yaml").read_text()
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in workflow
    assert 'CTRADER_DEMO_FVG_MAX_AGE_MINUTES: "90"' in workflow
    assert "chase_block_atr: 0.50" in strategy
