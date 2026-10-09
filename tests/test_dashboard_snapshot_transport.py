from datetime import UTC, datetime

from fx_scanner import dashboard_snapshot_transport as transport

NOW = datetime(2026, 10, 9, 13, tzinfo=UTC)


def payload(age=0, worker_age=0):
    from datetime import timedelta
    return {"bridge": {"fresh": age <= 180, "age_seconds": age},
            "backend": {"heartbeats": [{
                "worker_name": transport.EURUSD_WORKER,
                "observed_at": (NOW - timedelta(seconds=worker_age)).isoformat()}]}}


def test_fresh_eurusd_does_not_resolve_commit(monkeypatch):
    fresh = payload()
    monkeypatch.setattr(transport, "fetch_snapshot", lambda *a, **k: fresh)
    def unexpected(*a):
        raise AssertionError("fresh read should not query the GitHub API")
    monkeypatch.setattr(transport, "_latest_snapshot_commit", unexpected)
    assert transport.fetch_eurusd_snapshot(now=NOW) is fresh


def test_stale_worker_recovers_from_exact_commit(monkeypatch):
    rows = iter([payload(worker_age=900), payload()])
    urls = []
    def fetch(url, **kwargs):
        urls.append(url)
        return next(rows)
    monkeypatch.setattr(transport, "fetch_snapshot", fetch)
    monkeypatch.setattr(transport, "_latest_snapshot_commit", lambda *a: "a" * 40)
    result = transport.fetch_eurusd_snapshot(now=NOW)
    assert "a" * 40 in urls[-1]
    assert transport.worker_age(result, transport.EURUSD_WORKER, NOW) == 0


def test_new_publication_does_not_refresh_old_worker(monkeypatch):
    rows = iter([payload(age=600, worker_age=900), payload(worker_age=900)])
    monkeypatch.setattr(transport, "fetch_snapshot", lambda *a, **k: next(rows))
    monkeypatch.setattr(transport, "_latest_snapshot_commit", lambda *a: "a" * 40)
    result = transport.fetch_eurusd_snapshot(now=NOW)
    assert result["bridge"]["fresh"]
    assert transport.worker_age(result, transport.EURUSD_WORKER, NOW) == 900


def test_resolution_outage_preserves_degraded_snapshot(monkeypatch):
    stale = payload(age=600)
    monkeypatch.setattr(transport, "fetch_snapshot", lambda *a, **k: stale)
    def outage(*a):
        raise OSError("unavailable")
    monkeypatch.setattr(transport, "_latest_snapshot_commit", outage)
    result = transport.fetch_eurusd_snapshot(now=NOW)
    assert not result["bridge"]["fresh"]
    assert result["bridge"]["latest_read_error"] == "OSError"


def test_eurusd_resolves_cdn_lag_before_publication_becomes_stale(monkeypatch):
    rows = iter([payload(age=100, worker_age=100), payload(age=10, worker_age=20)])
    monkeypatch.setattr(transport, "fetch_snapshot", lambda *a, **k: next(rows))
    monkeypatch.setattr(transport, "_latest_snapshot_commit", lambda *a: "b" * 40)
    result = transport.fetch_eurusd_snapshot(now=NOW)
    assert result["bridge"]["age_seconds"] == 10
    assert transport.worker_age(result, transport.EURUSD_WORKER, NOW) == 20
