from pathlib import Path

from fx_scanner.storage.transient_supabase import is_transient_supabase_unavailable
from fx_scanner.demo_xau_dom_v191 import (
    _latest_previous_safe,
    _write_heartbeat_safe,
)


ApiError = type("APIError", (Exception,), {"__module__": "postgrest.exceptions"})


class _Query522:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        err = ApiError("{'message': 'JSON could not be generated', 'code': 522}")
        err.code = 522
        raise err


class _Client522:
    def table(self, _name):
        return _Query522()


class _DomReadStore522:
    client = _Client522()


class _DomWriteStore522:
    def write_heartbeat(self, *_args, **_kwargs):
        api = ApiError("{'code': 522, 'message': 'Cloudflare timeout'}")
        api.code = 522
        wrapped = RuntimeError("heartbeat write failed")
        wrapped.__cause__ = api
        raise wrapped


def test_v283_transient_supabase_classifier_handles_wrapped_522_only() -> None:
    api = ApiError("{'code': 522, 'message': 'Cloudflare timeout'}")
    api.code = 522
    wrapper = RuntimeError("durable backend probe failed")
    wrapper.__cause__ = api
    assert is_transient_supabase_unavailable(wrapper) is True

    schema = ApiError("{'code': 400, 'message': 'missing column'}")
    schema.code = 400
    assert is_transient_supabase_unavailable(schema) is False
    assert is_transient_supabase_unavailable(ValueError("logic bug")) is False


def test_v283_dom_previous_read_and_heartbeat_write_fail_soft_on_522() -> None:
    previous, read_status = _latest_previous_safe(_DomReadStore522())
    assert previous == {}
    assert read_status == "TRANSIENT_DB_UNAVAILABLE"

    write_status = _write_heartbeat_safe(
        _DomWriteStore522(),
        healthy=True,
        details={"analysis": {"state": "BALANCED_OR_CONTESTED"}},
    )
    assert write_status == "TRANSIENT_DB_UNAVAILABLE"


def test_v283_dom_and_forecast_remain_observability_only_during_db_outage() -> None:
    root = Path(__file__).resolve().parents[1]
    dom = (root / "src/fx_scanner/demo_xau_dom_v191.py").read_text()
    forecast = (
        root / "src/fx_scanner/research_xau_forecast_ensemble_v171_runtime.py"
    ).read_text()
    assert "execution_authority=0" in dom
    assert "Execution consumers still fail closed on stale/missing DB state." in dom
    assert "degraded_shadow=1" in forecast
    assert "This worker is SHADOW_ONLY" in forecast


def test_v283_token_maintainer_defer_is_before_ctrader_session_creation() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/fx_scanner/demo_ctrader_token_maintainer.py").read_text()
    defer = source.index("CTRADER_DEMO_TOKEN_MAINTAINER_DEFERRED")
    session = source.index("session = CTraderOpenApiSession(")
    assert defer < session
    assert "token_refresh_attempted=0" in source
    assert "if not is_transient_supabase_unavailable(exc):" in source
