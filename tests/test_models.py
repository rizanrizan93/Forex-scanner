from datetime import datetime, timezone

import pytest

from fx_scanner.exceptions import DataContractError
from fx_scanner.models import Tick


UTC = timezone.utc


def test_tick_contract_and_mid():
    t = Tick("eurusd", datetime(2026, 8, 29, 12, tzinfo=UTC), 1.1000, 1.1002)
    assert t.symbol == "EURUSD"
    assert round(t.mid, 5) == 1.1001
    assert round(t.spread, 5) == 0.0002


def test_crossed_quote_rejected():
    with pytest.raises(DataContractError):
        Tick("EURUSD", datetime(2026, 8, 29, 12, tzinfo=UTC), 1.1002, 1.1000)


def test_naive_timestamp_rejected():
    with pytest.raises(DataContractError):
        Tick("EURUSD", datetime(2026, 8, 29, 12), 1.1000, 1.1002)
