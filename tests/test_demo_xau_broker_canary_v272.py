from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_xau_broker_canary_v272 import (
    EVENT_TYPE,
    SIGNAL_ID,
    _already_verified,
    _canary_prices,
    _pending_canaries,
)


def test_v272_canary_geometry_is_far_away_sell_limit_with_valid_protection() -> None:
    entry, stop, target = _canary_prices(bid=4155.0, ask=4155.2)
    assert entry > 4155.2 + 100.0
    assert target < entry < stop
    assert round(stop - entry, 2) == round(entry - target, 2)


def test_v272_pending_canary_match_is_exact_client_id() -> None:
    reconcile = SimpleNamespace(
        order=[
            SimpleNamespace(clientOrderId=SIGNAL_ID, orderId=11),
            SimpleNamespace(clientOrderId=SIGNAL_ID + ":OTHER", orderId=12),
            SimpleNamespace(clientOrderId="OTHER", orderId=13),
        ]
    )
    pending = _pending_canaries(reconcile)
    assert len(pending) == 1
    assert pending[0].orderId == 11


class _Query:
    def __init__(self, rows):
        self.rows = rows
    def select(self, *_args, **_kwargs):
        return self
    def eq(self, *_args, **_kwargs):
        return self
    def order(self, *_args, **_kwargs):
        return self
    def limit(self, *_args, **_kwargs):
        return self
    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Client:
    def __init__(self, rows):
        self.rows = rows
    def table(self, _name):
        return _Query(self.rows)


class _Store:
    def __init__(self, rows):
        self.client = _Client(rows)


def test_v272_canary_verification_is_persistent_and_one_time() -> None:
    assert _already_verified(
        _Store([
            {
                "accepted": True,
                "code": "CANARY_CANCELLED_CONFIRMED",
                "event_type": EVENT_TYPE,
            }
        ])
    ) is True
    assert _already_verified(_Store([])) is False


def test_v272_workflow_enables_diagnostic_canary_without_making_it_critical() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    assert 'CTRADER_DEMO_BROKER_CANARY_ENABLED: "1"' in workflow
    assert "python -m fx_scanner.demo_xau_broker_canary_v272" in workflow
    assert "DEMO_BROKER_CANARY" in workflow
    assert "diagnostic_only=1" in workflow


def test_v272_canary_is_excluded_from_strategy_statistics_by_contract() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_broker_canary_v272.py"
    ).read_text()
    assert '"diagnostic_only": True' in source
    assert '"exclude_from_strategy_stats": True' in source
    assert 'EVENT_TYPE = "DEMO_XAU_BROKER_CANARY"' in source
    assert "CANARY_CANCELLED_CONFIRMED" in source
