from fx_scanner.research_xau_forecast_ensemble_v171 import build_forecast_ensemble
from fx_scanner.research_xau_forecast_ensemble_v171_runtime import (
    _build_shadow_feed,
    _reference_components,
    _transient_db_unavailable,
)


class Postgrest522(Exception):
    pass


def test_522_falls_back_to_unavailable_structure_and_non_actionable_forecast(monkeypatch):
    import fx_scanner.research_xau_forecast_ensemble_v171_runtime as runtime

    def fail(_client):
        raise Postgrest522({"code": 522, "message": "JSON could not be generated"})

    monkeypatch.setattr(runtime, "_load_afic_component", fail)
    afic, v170, status = _reference_components(object())
    ensemble = build_forecast_ensemble(
        afic=afic, expected_move=v170,
        conditional={"available": True, "direction": "LONG", "probability": 0.7},
        acd={}, cot={},
    )
    assert status == "TRANSIENT_DB_UNAVAILABLE"
    assert afic["available"] is False
    assert ensemble["primary_scenario"]["direction"] == "WAIT_H4_MAP"
    assert ensemble["execution_influence"] is False


def test_schema_failure_is_not_misclassified_as_transient(monkeypatch):
    import fx_scanner.research_xau_forecast_ensemble_v171_runtime as runtime

    def fail(_client):
        raise ValueError("missing column")

    monkeypatch.setattr(runtime, "_load_afic_component", fail)
    try:
        _reference_components(object())
    except ValueError as exc:
        assert str(exc) == "missing column"
    else:
        raise AssertionError("schema error was swallowed")
    assert _transient_db_unavailable(ValueError("bad query")) is False
    assert _transient_db_unavailable(TimeoutError("connect")) is True


def test_runner_postgrest_stringified_522_is_recognized_without_swallowing_400():
    ApiError = type("APIError", (Exception,), {"__module__": "postgrest.exceptions"})
    assert _transient_db_unavailable(ApiError("{'message': 'JSON could not be generated', 'code': 522, 'details': 'Cloudflare'}"))
    assert not _transient_db_unavailable(ApiError("{'message': 'missing column', 'code': 400}"))
    actual_shape = ApiError("{'message': 'JSON could not be generated', 'code': 522}")
    actual_shape.code = 522
    assert _transient_db_unavailable(actual_shape)


def test_database_outage_uses_read_only_standalone_feed_only_for_shadow(monkeypatch):
    import fx_scanner.research_xau_forecast_ensemble_v171_runtime as runtime

    keys = {name: f"test_{name}" for name in (
        "client_id_env", "client_secret_env", "access_token_env",
        "refresh_token_env", "trader_login_env", "account_id_env",
    )}
    values = {"client_id_env": "id", "client_secret_env": "secret",
              "access_token_env": "access", "refresh_token_env": "refresh",
              "trader_login_env": "123", "account_id_env": ""}
    for name, key in keys.items():
        monkeypatch.setenv(key, values[name])
    policy = type("Policy", (), {"ctrader": keys})()
    called = []
    monkeypatch.setattr(runtime, "build_standalone_ctrader_feed", lambda **kw: called.append(kw) or "standalone")
    monkeypatch.setattr(runtime, "build_ctrader_research_feed", lambda *_args: "durable")
    assert _build_shadow_feed(policy, "OK") == "durable"
    assert _build_shadow_feed(policy, "TRANSIENT_DB_UNAVAILABLE") == "standalone"
    assert called[0]["trader_login"] == 123
    assert called[0]["account_id"] is None
