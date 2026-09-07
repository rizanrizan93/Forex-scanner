import fx_scanner.demo_loss_attribution_v2_runtime as runtime


class _Store:
    def __init__(self):
        self.heartbeat = None

    def write_heartbeat(self, worker_name, *, healthy, lag_seconds, details):
        self.heartbeat = (worker_name, healthy, lag_seconds, details)


def test_loss_attribution_uses_same_bounded_account_aliases_as_adaptive_v2(monkeypatch):
    store = _Store()
    aliases = ("configured-alias", "broker-native-account")
    seen = {}

    monkeypatch.setattr(runtime.SupabaseOperationalStore, "from_env", lambda: store)
    monkeypatch.setattr(runtime, "_account_ids", lambda current_store: aliases)

    def closed(current_store, *, account_ids):
        assert current_store is store
        seen["closed"] = account_ids
        return ({"signal_key": "signal-1", "payload": {"exit_type": "SL_HIT"}},)

    def context(name):
        def loader(current_store, *, account_ids):
            assert current_store is store
            seen[name] = account_ids
            return {}
        return loader

    monkeypatch.setattr(runtime, "_closed_rows", closed)
    monkeypatch.setattr(runtime, "_signal_context", lambda current_store: {})
    monkeypatch.setattr(runtime, "_geometry_context", context("geometry"))
    monkeypatch.setattr(runtime, "_trajectory_context", context("trajectory"))
    monkeypatch.setattr(runtime, "_feature_snapshot_context", context("snapshot"))
    monkeypatch.setattr(runtime, "_enrich_rows", lambda rows, *args: rows)
    monkeypatch.setattr(runtime, "build_loss_attribution_v2", lambda rows: ())

    assert runtime.run() == 0
    assert seen == {
        "closed": aliases,
        "geometry": aliases,
        "trajectory": aliases,
        "snapshot": aliases,
    }
    assert store.heartbeat is not None
    worker_name, healthy, lag_seconds, details = store.heartbeat
    assert worker_name == runtime.WORKER
    assert healthy is True
    assert lag_seconds == 0.0
    assert details["closed_rows_scanned"] == 1
    assert details["account_identifier_alias_count"] == 2
    assert details["policy_effect"] == "SHADOW_ONLY"
    assert details["risk_mutation"] is False
    assert details["sltp_mutation"] is False
    assert details["production_mutation"] is False
