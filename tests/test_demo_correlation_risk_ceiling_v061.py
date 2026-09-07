import pytest

from fx_scanner.demo_correlation_evidence import EvidenceProductionGuardResolver
from fx_scanner.producer_guards import ProductionGuardResolver


def _stub_base_init(self, *args, **kwargs):
    self.demo_max_risk_pct = 1.0


def test_demo_correlation_guard_accepts_explicit_three_percent(monkeypatch):
    monkeypatch.setattr(ProductionGuardResolver, "__init__", _stub_base_init)
    monkeypatch.setenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "3.0")

    resolver = EvidenceProductionGuardResolver()

    assert resolver.demo_max_risk_pct == 3.0


def test_demo_correlation_guard_rejects_above_three_percent(monkeypatch):
    monkeypatch.setattr(ProductionGuardResolver, "__init__", _stub_base_init)
    monkeypatch.setenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "3.01")

    with pytest.raises(
        ValueError,
        match=r"CTRADER_DEMO_RISK_PER_TRADE_PCT must be in \(0,3\]",
    ):
        EvidenceProductionGuardResolver()
