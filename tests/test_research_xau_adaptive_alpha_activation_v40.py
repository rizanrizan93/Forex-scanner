from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.demo_donchian_adaptive_tournament import TournamentTrade
from fx_scanner.research_xau_adaptive_alpha_activation_v40 import (
    EXECUTION_INFLUENCE,
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    SATELLITE_FAMILIES,
    gate_family_causally,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _trade(day: int, *, net_r: float = 0.20, exit_delay_hours: int = 1):
    signal = datetime(2025, 1, 1, 12, 0, tzinfo=UTC) + timedelta(days=day)
    exit_at = signal + timedelta(hours=exit_delay_hours)
    gross = net_r + 0.01
    return TournamentTrade(
        "TEST",
        "XAUUSD",
        "LONG",
        signal,
        signal,
        exit_at,
        day,
        day,
        2000.0,
        2001.0,
        10.0,
        1990.0,
        2100.0,
        gross,
        0.01,
        net_r,
        1,
        "TIME_EXIT",
    )


def test_v40_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v40_gate_contract_is_bounded():
    assert LOOKBACK_TRADING_DAYS == 126
    assert MIN_COMPLETED_TRADES == 30
    assert set(SATELLITE_FAMILIES) == {
        "M15_L12",
        "M15_L20",
        "XAG_D1",
        "EUR_D1",
        "AGREE_D1",
    }


def test_gate_uses_only_prior_completed_trades():
    trades = tuple(_trade(i) for i in range(45))
    dates = tuple(
        (datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i)).date()
        for i in range(60)
    )
    kept, payload = gate_family_causally(trades, trading_dates=dates)
    # The first 30 signals cannot be active because fewer than 30 earlier
    # completed trades exist. Subsequent signals can activate.
    assert payload["suppressed_trades"] >= 30
    assert len(kept) > 0
    assert min(x.signal_at for x in kept) > trades[29].exit_at


def test_unfinished_future_trade_cannot_activate_gate():
    history = tuple(_trade(i) for i in range(29))
    delayed = _trade(29, exit_delay_hours=48)
    current = _trade(30)
    dates = tuple(
        (datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i)).date()
        for i in range(60)
    )
    kept, _ = gate_family_causally((*history, delayed, current), trading_dates=dates)
    assert current not in kept


def test_v40_source_has_no_execution_or_era_hardcode():
    src = (ROOT / "src/fx_scanner/research_xau_adaptive_alpha_activation_v40.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_adaptive_alpha_activation_v40_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"era_or_calendar_year_feature_used": False' in src
    assert '"threshold_grid_search": False' in src
    assert "selection_uses_future_outcomes" in src
    assert "exit_at" in src
