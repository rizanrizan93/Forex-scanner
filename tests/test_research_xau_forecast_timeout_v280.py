from fx_scanner.research_xau_forecast_ensemble_v171 import build_forecast_ensemble
from fx_scanner.research_xau_forecast_ensemble_v171_runtime import (
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
