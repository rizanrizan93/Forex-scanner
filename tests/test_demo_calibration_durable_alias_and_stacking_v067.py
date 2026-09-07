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


def test_fast_handoff_does_not_install_same_symbol_stacking_policy():
    source = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")

    assert "install_demo_position_policy" not in source
    assert "demo_position_reversal" not in source
