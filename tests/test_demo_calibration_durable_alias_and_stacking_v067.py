from pathlib import Path

from fx_scanner.demo_adaptive_calibration_v2_runtime import _account_ids


class _Response:
    data = [{"account_id": "broker-native-account"}]


class _Query:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Response()


class _Client:
    def table(self, name):
        assert name == "broker_account_state"
        return _Query()


class _Store:
    client = _Client()


def test_account_ids_include_latest_durable_ctrader_account(monkeypatch):
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "configured-alias")
    monkeypatch.delenv("CTRADER_TRADER_LOGIN", raising=False)

    assert _account_ids(_Store()) == ("configured-alias", "broker-native-account")


def test_fast_handoff_installs_conditional_stacking_after_conviction_sizing():
    source = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")

    sizing = source.index("install_demo_conviction_sizing()")
    stacking = source.index("install_demo_conditional_stacking()")
    assert sizing < stacking
    assert "CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING" in source
    assert "max_same_symbol_positions" in source
    assert "DEMO_ORDER_LOT_CAP_CEILING = 0.50" in source
    assert "broker-native" in source
