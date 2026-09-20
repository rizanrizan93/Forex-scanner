from datetime import datetime, timedelta, timezone

from fx_scanner.demo_fresh_ready_handoff import fresh_execution_ready_rows

UTC = timezone.utc


def _row(signal_id, *, state="EXECUTION_READY", observed_at, expires_at):
    return {
        "id": signal_id,
        "state": state,
        "observed_at": observed_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def test_fresh_handoff_drops_stale_ready_backlog_and_keeps_newest_fresh_rows():
    now = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    rows = [
        _row("stale-1", observed_at=now - timedelta(minutes=20), expires_at=now - timedelta(minutes=15)),
        _row("fresh-older", observed_at=now - timedelta(seconds=120), expires_at=now + timedelta(seconds=180)),
        _row("fresh-newer", observed_at=now - timedelta(seconds=15), expires_at=now + timedelta(seconds=285)),
        _row("forming", state="SETUP_FORMING", observed_at=now - timedelta(seconds=5), expires_at=now + timedelta(seconds=295)),
    ]
    selected = fresh_execution_ready_rows(rows, now=now, max_age_seconds=300, limit=10)
    assert [row["id"] for row in selected] == ["fresh-newer", "fresh-older"]


def test_fresh_handoff_never_promotes_nonready_or_future_signal():
    now = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    rows = [
        _row("armed", state="ARMED", observed_at=now - timedelta(seconds=10), expires_at=now + timedelta(seconds=290)),
        _row("future", observed_at=now + timedelta(seconds=5), expires_at=now + timedelta(seconds=305)),
    ]
    assert fresh_execution_ready_rows(rows, now=now, max_age_seconds=300, limit=10) == ()


def test_auto_workflow_uses_pair_specific_fresh_handoff_wrapper():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_execution_fresh_ready_handoff --limit 10" in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in text
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in text


def test_xau_demo_handoff_exactly_allows_m15_and_v24_champion():
    from fx_scanner.demo_execution_fresh_ready_handoff import (
        _ALLOWED_STRATEGIES_BY_SYMBOL,
        _XAU_CHAMPION_STRATEGY,
        _XAU_D1_TSMOM_STRATEGY,
        _XAU_SHADOW_STRATEGIES,
    )
    from fx_scanner.demo_xau_m15_ema_smc_reclaim import STRATEGY_ID as m15_strategy
    from fx_scanner.demo_xau_v24_champion_candidate_producer import STRATEGY_ID as champion_strategy

    allowed = _ALLOWED_STRATEGIES_BY_SYMBOL["XAUUSD"]
    assert _XAU_CHAMPION_STRATEGY == champion_strategy
    assert _XAU_D1_TSMOM_STRATEGY == "D1_TSMOM_60_200"
    assert allowed == frozenset({champion_strategy, m15_strategy})
    assert _XAU_D1_TSMOM_STRATEGY in _XAU_SHADOW_STRATEGIES
