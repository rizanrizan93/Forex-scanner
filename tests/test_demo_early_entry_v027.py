from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_technical_strategy import (
    _early_structure_valid,
    _fresh_directional_fvg,
)
from fx_scanner.liquidity import FairValueGap

UTC = timezone.utc


def _snapshot(trend: str, bos: str | None = None, mss: str | None = None):
    return SimpleNamespace(trend=trend, bos=bos, mss=mss)


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


def test_supervisor_uses_two_minute_non_overlap_dispatch():
    text = Path(".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    assert "seq 1 30" in text
    assert "sleep 120" in text
    assert "SUPERVISOR_SKIP_BUSY" in text
    assert "overlap=DISABLED" in text


def test_pipeline_keeps_chase_limit_and_enables_fresh_fvg_profile():
    workflow = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    strategy = Path("config/strategy.yaml").read_text()
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "60"' in workflow
    assert 'CTRADER_DEMO_FVG_MAX_AGE_MINUTES: "90"' in workflow
    assert "chase_block_atr: 0.50" in strategy
