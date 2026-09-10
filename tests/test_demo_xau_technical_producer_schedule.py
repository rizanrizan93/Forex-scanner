from datetime import datetime, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.demo_xau_technical_producer import _apply_xau_only_market_schedule


def test_xau_wrapper_validates_full_weekday_universe_before_narrowing():
    cfg = load_project_config()
    scheduled, mode = _apply_xau_only_market_schedule(
        cfg,
        now=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert [pair.symbol for pair in scheduled.pairs] == ["XAUUSD"]
    assert mode == "WEEKDAY_FULL_24X5_XAUUSD_ONLY"


def test_xau_wrapper_fails_closed_when_xau_is_not_scheduled():
    cfg = load_project_config()

    with pytest.raises(SystemExit, match="XAUUSD_NOT_SCHEDULED"):
        _apply_xau_only_market_schedule(
            cfg,
            now=datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
        )
