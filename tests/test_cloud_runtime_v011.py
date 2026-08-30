from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.cloud_runtime import CTraderCloudResearchRuntime
from fx_scanner.config import load_project_config

UTC = timezone.utc

class FakeFeed:
    def __init__(self):
        self.heartbeat_calls = 0
        self.bar_calls = 0
    def heartbeat(self):
        self.heartbeat_calls += 1
    def quote(self, symbol):
        return SimpleNamespace(bid=1.1, ask=1.1002, timestamp=datetime.now(tz=UTC))
    def historical_bars(self, symbol, timeframe, *, from_time, to_time, count):
        self.bar_calls += 1
        return tuple(range(count))

class FakeStore:
    def __init__(self):
        self.rows = []
    def write_heartbeat(self, worker_name, **kwargs):
        self.rows.append((worker_name, kwargs))

def test_cloud_runtime_is_ctrader_research_only_and_rate_limited():
    cfg = load_project_config()
    feed = FakeFeed()
    store = FakeStore()
    sleeps = []
    runtime = CTraderCloudResearchRuntime(
        cfg, feed, store, historical_request_delay_seconds=0.25, sleeper=sleeps.append
    )
    report = runtime.probe(include_mtf=True)
    expected = len(cfg.pairs) * len(cfg.strategy["mtf"]["required_timeframes"])
    assert report.healthy
    assert report.quotes_ok == len(cfg.pairs)
    assert report.mtf_ok == expected
    assert feed.bar_calls == expected
    assert len(sleeps) == expected
    assert min(sleeps) >= 0.20
    assert store.rows[-1][0] == "ctrader_research_cloud"
    assert store.rows[-1][1]["details"]["role"] == "RESEARCH_ONLY"
