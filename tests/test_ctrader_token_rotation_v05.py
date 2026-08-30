from types import SimpleNamespace

from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
from fx_scanner.execution.ctrader_tokens import CTraderTokenStateStore


class RefreshReq:
    def __init__(self):
        self.refreshToken = ""


def test_ctrader_refresh_rotates_and_persists_both_tokens(tmp_path):
    store = CTraderTokenStateStore(tmp_path / "tokens.json")
    session = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    session.refresh_token = "old-refresh"
    session.access_token = "old-access"
    session.token_update_callback = store.save
    session.msg = {"RefreshTokenReq": RefreshReq}
    captured = {}

    def send(req, **kwargs):
        captured["refresh"] = req.refreshToken
        return SimpleNamespace(accessToken="new-access", refreshToken="new-refresh")

    session._send_sync = send
    session._refresh_tokens()

    assert captured["refresh"] == "old-refresh"
    assert session.access_token == "new-access"
    assert session.refresh_token == "new-refresh"

    loaded = store.load(fallback_access="bad", fallback_refresh="bad")
    assert loaded.access_token == "new-access"
    assert loaded.refresh_token == "new-refresh"


def test_ctrader_token_store_falls_back_to_environment_values(tmp_path):
    store = CTraderTokenStateStore(tmp_path / "missing.json")
    loaded = store.load(fallback_access="env-access", fallback_refresh="env-refresh")
    assert loaded.access_token == "env-access"
    assert loaded.refresh_token == "env-refresh"


def test_ctrader_token_store_rotated_state_overrides_stale_env(tmp_path):
    store = CTraderTokenStateStore(tmp_path / "tokens.json")
    store.save("rotated-access", "rotated-refresh")
    loaded = store.load(fallback_access="stale-access", fallback_refresh="stale-refresh")
    assert loaded.access_token == "rotated-access"
    assert loaded.refresh_token == "rotated-refresh"
