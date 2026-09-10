from datetime import datetime, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_xau_technical_producer import _apply_xau_only_market_schedule

UTC = timezone.utc


def test_weekday_validates_full_universe_then_returns_xau_only():
    cfg = load_project_config(None)
    assert len(cfg.pairs) == 20
    scheduled, mode = _apply_xau_only_market_schedule(
        cfg,
        now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    assert mode == "WEEKDAY_FULL_24X5_XAUUSD_ONLY"
    assert [pair.symbol for pair in scheduled.pairs] == ["XAUUSD"]


def test_weekend_xau_only_exits_cleanly_instead_of_reenabling_crypto():
    cfg = load_project_config(None)
    with pytest.raises(SystemExit, match="XAUUSD_MARKET_SCHEDULE_CLOSED:WEEKEND_CRYPTO_BROKER_GATED"):
        _apply_xau_only_market_schedule(
            cfg,
            now=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        )


def test_wrapper_does_not_replace_load_project_config_before_schedule():
    source = __import__("pathlib").Path("src/fx_scanner/demo_xau_technical_producer.py").read_text(encoding="utf-8")
    assert "base.load_project_config =" not in source
    assert "base.apply_demo_market_schedule = _apply_xau_only_market_schedule" in source
