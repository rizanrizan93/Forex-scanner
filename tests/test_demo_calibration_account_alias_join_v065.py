from fx_scanner.demo_adaptive_calibration_v2_runtime import (
    _account_ids,
    _account_scoped,
    _enrich_rows,
)


class _Query:
    def __init__(self):
        self.calls = []

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.calls.append(("in", column, tuple(values)))
        return self


def test_account_ids_keep_both_ctrader_demo_aliases(monkeypatch):
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "account-alias")
    monkeypatch.setenv("CTRADER_TRADER_LOGIN", "login-alias")

    assert _account_ids() == ("account-alias", "login-alias")


def test_account_ids_deduplicate_same_identifier(monkeypatch):
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "same")
    monkeypatch.setenv("CTRADER_TRADER_LOGIN", "same")

    assert _account_ids() == ("same",)


def test_account_scoped_uses_in_filter_for_two_aliases():
    query = _Query()

    result = _account_scoped(query, ("account-alias", "login-alias"))

    assert result is query
    assert query.calls == [("in", "account_id", ("account-alias", "login-alias"))]


def test_account_scoped_uses_exact_filter_for_single_alias():
    query = _Query()

    result = _account_scoped(query, ("account-alias",))

    assert result is query
    assert query.calls == [("eq", "account_id", "account-alias")]


def test_geometry_join_restores_wave_entry_mode_without_overriding_closed_truth():
    rows = (
        {
            "signal_key": "signal-1",
            "code": "SL_HIT",
            "payload": {
                "symbol": "EURGBP",
                "direction": "LONG",
                "exit_type": "SL_HIT",
                "net_pnl_estimate": -0.47,
            },
        },
    )
    geometries = {
        "signal-1": {
            "entry_mode": "HL_PULLBACK",
            "confirmation": "M5_STRUCTURE_BREAK",
            "symbol": "SHOULD_NOT_OVERRIDE",
            "pullback_atr": 1.03,
        }
    }

    enriched = _enrich_rows(rows, {}, geometries)
    payload = enriched[0]["payload"]

    assert payload["symbol"] == "EURGBP"
    assert payload["entry_mode"] == "HL_PULLBACK"
    assert payload["confirmation"] == "M5_STRUCTURE_BREAK"
    assert payload["pullback_atr"] == 1.03
    assert payload["v2_context_source"] == "DEMO_TRADE_CLOSED+DEMO_SIGNAL_GEOMETRY"
