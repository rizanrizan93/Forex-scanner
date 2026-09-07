from fx_scanner import demo_adaptive_gate_v2_runtime as runtime


def test_resolved_account_ids_deduplicates_runtime_and_configured_aliases(monkeypatch):
    monkeypatch.setattr(runtime, "_account_ids", lambda: ("acct-1", "login-1"))

    assert runtime._resolved_account_ids("acct-1") == ("acct-1", "login-1")


def test_load_adaptive_gate_v2_policy_uses_account_ids_contract(monkeypatch):
    seen = []
    monkeypatch.setattr(runtime, "_account_ids", lambda: ("acct-1", "login-1"))

    def scoped(name, value):
        def inner(store, *, account_ids):
            seen.append((name, account_ids))
            return value
        return inner

    monkeypatch.setattr(runtime, "_closed_rows", scoped("closed", ()))
    monkeypatch.setattr(runtime, "_geometry_context", scoped("geometry", {}))
    monkeypatch.setattr(runtime, "_trajectory_context", scoped("trajectory", {}))
    monkeypatch.setattr(runtime, "_feature_snapshot_context", scoped("snapshot", {}))
    monkeypatch.setattr(runtime, "_signal_context", lambda store: {})
    monkeypatch.setattr(runtime, "_enrich_rows", lambda rows, signals, geometries, trajectories, snapshots: ())

    sentinel = object()
    monkeypatch.setattr(runtime, "build_adaptive_gate_v2_policy", lambda rows, *, signal_context, base_floor, enabled: sentinel)

    result = runtime.load_adaptive_gate_v2_policy(
        object(),
        account_id="acct-1",
        base_floor=50.01,
        enabled=True,
    )

    assert result is sentinel
    assert seen == [
        ("closed", ("acct-1", "login-1")),
        ("geometry", ("acct-1", "login-1")),
        ("trajectory", ("acct-1", "login-1")),
        ("snapshot", ("acct-1", "login-1")),
    ]
