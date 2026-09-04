from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fx_scanner.config import load_project_config
from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.demo_autotrade import CTraderDemoAutoExecutor

UTC = timezone.utc


class _Duplicates:
    def __init__(self):
        self.uncertain = False

    def is_uncertain(self, signal_id):
        return self.uncertain


class _Router:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.duplicates = _Duplicates()
        self.control_gate = None

    def execute(self, intent):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(accepted=bool(outcome))


class _UncertainRouter(_Router):
    def execute(self, intent):
        self.calls += 1
        self.duplicates.uncertain = True
        raise CollectorUnavailable("cTrader request timeout after submit boundary")


class _Gateway:
    def __init__(self, *, quote_failures=0):
        self.quote_failures = int(quote_failures)

    def market_quote(self, symbol):
        if self.quote_failures > 0:
            self.quote_failures -= 1
            raise CollectorUnavailable("cTrader request timeout")
        return SimpleNamespace(bid=1.0999, ask=1.1000)

    def position_count(self):
        return 0


class _Store:
    def __init__(self, row):
        self.row = row
        self.claimed = []
        self.released = []

    def list_execution_ready_signals(self, *, limit=10):
        return (self.row,)

    def claim_signal_for_execution(self, signal_id):
        self.claimed.append(signal_id)
        return True

    def release_signal_execution_claim(self, signal_id):
        self.released.append(signal_id)
        return True


def _policy():
    return SimpleNamespace(
        demo_safety={
            "min_signal_coverage": 0.80,
            "max_order_lots": 0.01,
            "max_risk_pct": 1.0,
            "max_concurrent_positions": 5,
        },
        live_safety={"require_control_plane": False},
        order={"max_signal_age_seconds": 300},
        mode=SimpleNamespace(value="AUTO"),
    )


def _row():
    now = datetime.now(tz=UTC)
    return {
        "id": "00000000-0000-0000-0000-000000000034",
        "observed_at": now.isoformat(),
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "state": "EXECUTION_READY",
        "entry_low": 1.0998,
        "entry_high": 1.1002,
        "sl": 1.0950,
        "tp2": 1.1100,
        "rr2": 2.0,
        "active_guards": [],
        "data_coverage": 0.95,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "final_score": 95.0,
    }


def _executor(*, gateway, router, store):
    executor = CTraderDemoAutoExecutor(
        cfg=load_project_config(),
        policy=_policy(),
        gateway=gateway,
        router=router,
        store=store,
    )
    executor.SAFE_RETRY_DELAYS_SECONDS = (0.0, 0.0)
    return executor


def test_preclaim_quote_transport_failure_is_retried_before_signal_is_missed():
    row = _row()
    store = _Store(row)
    router = _Router([True])
    gateway = _Gateway(quote_failures=2)

    report = _executor(gateway=gateway, router=router, store=store).poll_once()

    assert report.eligible == 1
    assert report.claimed == 1
    assert report.executed == 1
    assert router.calls == 1
    assert store.released == []


def test_claimed_signal_retries_safe_transient_failure_and_executes_once():
    row = _row()
    store = _Store(row)
    router = _Router([
        CollectorUnavailable("cTrader connection timeout"),
        True,
    ])

    report = _executor(gateway=_Gateway(), router=router, store=store).poll_once()

    assert report.claimed == 1
    assert report.executed == 1
    assert router.calls == 2
    assert store.claimed == [row["id"]]
    assert store.released == []


def test_safe_transient_failure_is_requeued_after_bounded_retries():
    row = _row()
    store = _Store(row)
    router = _Router([
        CollectorUnavailable("cTrader connection timeout"),
        CollectorUnavailable("cTrader connection timeout"),
        CollectorUnavailable("cTrader connection timeout"),
    ])

    report = _executor(gateway=_Gateway(), router=router, store=store).poll_once()

    assert report.claimed == 1
    assert report.executed == 0
    assert router.calls == 3
    assert store.released == [row["id"]]
    assert any("TRANSIENT_REQUEUED:CollectorUnavailable" in item for item in report.skipped)


def test_uncertain_post_submit_failure_is_never_retried_or_requeued():
    row = _row()
    store = _Store(row)
    router = _UncertainRouter([])

    report = _executor(gateway=_Gateway(), router=router, store=store).poll_once()

    assert report.claimed == 1
    assert report.executed == 0
    assert router.calls == 1
    assert store.released == []
    assert any("OUTCOME_UNCERTAIN:CollectorUnavailable" in item for item in report.skipped)
