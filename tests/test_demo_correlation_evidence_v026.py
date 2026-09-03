from fx_scanner.demo_correlation_evidence import CorrelationEvidence


def test_correlation_evidence_is_observability_only_value_object():
    row = CorrelationEvidence(
        symbol="USDJPY",
        peer_symbol="GBPJPY",
        correlation=0.91,
        threshold=0.85,
        lookback_bars=30,
        blocked=True,
    )

    assert row.symbol == "USDJPY"
    assert row.peer_symbol == "GBPJPY"
    assert row.correlation == 0.91
    assert row.threshold == 0.85
    assert row.lookback_bars == 30
    assert row.blocked is True
