from datetime import datetime, timezone
from threading import Event, Thread

import pytest

from fx_scanner.execution.broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerOrderResult,
    BrokerPreflight,
)
from fx_scanner.execution.duplicate_guard import DuplicateOrderGuard
from fx_scanner.execution.models import ExecutionMode, OrderIntent, OrderSide, OrderType
from fx_scanner.execution.policy import ExecutionPolicy
from fx_scanner.execution.router import ExecutionBlocked, ExecutionRouter

UTC = timezone.utc


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        mode=ExecutionMode.AUTO,
        scheduler={
            "heavy_scan_seconds": 900,
            "fast_setup_seconds": 60,
            "execution_watch_seconds": 2,
            "position_monitor_seconds": 2,
        },
        order={
            "max_signal_age_seconds": 300,
            "require_broker_preflight": True,
            "require_server_side_sl": True,
            "require_server_side_tp": True,
            "comment_prefix": "FXIS",
        },
        live_safety={
            "live_enable_env": "FX_LIVE_TRADING_ENABLED",
            "live_enable_value": "I_UNDERSTAND_LIVE_ORDERS",
            "account_allowlist_env": "FX_BROKER_ACCOUNT_ALLOWLIST",
            "require_account_allowlist": True,
            "kill_switch_env": "FX_KILL_SWITCH",
            "kill_switch_safe_value": "0",
        },
    )


def _intent(sig="LIVE-1") -> OrderIntent:
    return OrderIntent(
        signal_id=sig,
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.05,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


class FakeGateway:
    backend = BrokerBackend.CTRADER

    def __init__(self, *, account_id="12345", trade_allowed=True, preflight_ok=True, send_ok=True):
        self.account_id = account_id
        self.trade_allowed = trade_allowed
        self.preflight_ok = preflight_ok
        self.send_ok = send_ok
        self.sent = 0
        self.on_preflight = None

    def account_snapshot(self):
        return BrokerAccountSnapshot(self.backend, self.account_id, 10_000, 10_000, 10_000, self.trade_allowed)

    def preflight(self, intent, order_config):
        if self.on_preflight:
            self.on_preflight()
        return BrokerPreflight(self.backend, self.preflight_ok, "PF", "preflight", {"signal": intent.signal_id})

    def submit(self, preflight):
        self.sent += 1
        return BrokerOrderResult(self.backend, self.send_ok, "3", "filled", "777", 0.05, 1.1001)


def _open_live(monkeypatch, allowlist="12345"):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.setenv("FX_LIVE_TRADING_ENABLED", "I_UNDERSTAND_LIVE_ORDERS")
    monkeypatch.setenv("FX_BROKER_ACCOUNT_ALLOWLIST", allowlist)


def test_auto_live_env_gate_is_closed_by_default(monkeypatch):
    monkeypatch.setenv("FX_KILL_SWITCH", "0")
    monkeypatch.delenv("FX_LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.setenv("FX_BROKER_ACCOUNT_ALLOWLIST", "12345")
    router = ExecutionRouter(_policy(), duplicate_guard=DuplicateOrderGuard(), gateway=FakeGateway())
    with pytest.raises(ExecutionBlocked, match="LIVE_ENV_GATE_CLOSED"):
        router.execute(_intent())


def test_auto_requires_account_allowlist(monkeypatch):
    _open_live(monkeypatch, "99999")
    router = ExecutionRouter(_policy(), duplicate_guard=DuplicateOrderGuard(), gateway=FakeGateway(account_id="12345"))
    with pytest.raises(ExecutionBlocked, match="ACCOUNT_NOT_ALLOWLISTED"):
        router.execute(_intent())


def test_preflight_rejection_prevents_send(monkeypatch):
    _open_live(monkeypatch)
    gateway = FakeGateway(preflight_ok=False)
    router = ExecutionRouter(_policy(), duplicate_guard=DuplicateOrderGuard(), gateway=gateway)
    with pytest.raises(ExecutionBlocked, match="PREFLIGHT_REJECTED"):
        router.execute(_intent())
    assert gateway.sent == 0


def test_fake_live_success_requires_all_gates(monkeypatch):
    _open_live(monkeypatch)
    gateway = FakeGateway()
    guard = DuplicateOrderGuard()
    router = ExecutionRouter(_policy(), duplicate_guard=guard, gateway=gateway)
    receipt = router.execute(_intent())
    assert receipt.accepted
    assert receipt.broker_order_id == "777"
    assert "CTRADER_ACCEPTED" in receipt.message
    assert gateway.sent == 1
    assert guard.is_duplicate("LIVE-1")


def test_kill_switch_rechecked_after_preflight(monkeypatch):
    _open_live(monkeypatch)
    gateway = FakeGateway()
    gateway.on_preflight = lambda: monkeypatch.setenv("FX_KILL_SWITCH", "1")
    router = ExecutionRouter(_policy(), duplicate_guard=DuplicateOrderGuard(), gateway=gateway)
    with pytest.raises(ExecutionBlocked, match="KILL_SWITCH_ENGAGED"):
        router.execute(_intent("RACE-KILL"))
    assert gateway.sent == 0


def test_inflight_claim_blocks_concurrent_duplicate(monkeypatch):
    _open_live(monkeypatch)
    entered = Event()
    release = Event()
    gateway = FakeGateway()

    def block():
        entered.set()
        assert release.wait(timeout=1.0)

    gateway.on_preflight = block
    router = ExecutionRouter(_policy(), duplicate_guard=DuplicateOrderGuard(), gateway=gateway)
    outcomes = []

    def first():
        try:
            outcomes.append(router.execute(_intent("SAME")))
        except Exception as exc:
            outcomes.append(exc)

    t = Thread(target=first)
    t.start()
    assert entered.wait(timeout=0.5)
    with pytest.raises(ExecutionBlocked, match="DUPLICATE_SIGNAL"):
        router.execute(_intent("SAME"))
    release.set()
    t.join(timeout=1.0)
    assert gateway.sent == 1


class RaisingGateway(FakeGateway):
    def submit(self, preflight):
        self.sent += 1
        raise TimeoutError("response lost after send")


def test_unknown_order_outcome_is_quarantined_and_persisted(monkeypatch, tmp_path):
    _open_live(monkeypatch)
    path = tmp_path / "idempotency.json"
    gateway = RaisingGateway()
    guard = DuplicateOrderGuard(path)
    router = ExecutionRouter(_policy(), duplicate_guard=guard, gateway=gateway)
    signal = _intent("UNKNOWN-OUTCOME")
    with pytest.raises(TimeoutError, match="response lost"):
        router.execute(signal)
    assert guard.is_uncertain(signal.signal_id)
    assert guard.is_duplicate(signal.signal_id)

    restarted = DuplicateOrderGuard(path)
    assert restarted.is_uncertain(signal.signal_id)
    assert restarted.is_duplicate(signal.signal_id)
    with pytest.raises(ExecutionBlocked, match="DUPLICATE_SIGNAL"):
        ExecutionRouter(_policy(), duplicate_guard=restarted, gateway=FakeGateway()).execute(signal)


def test_uncertain_signal_requires_explicit_reconciliation(tmp_path):
    path = tmp_path / "idempotency.json"
    guard = DuplicateOrderGuard(path)
    assert guard.try_claim("U-1")
    guard.mark_uncertain("U-1")
    guard.resolve_uncertain("U-1", executed=False)
    assert not guard.is_duplicate("U-1")

    assert guard.try_claim("U-2")
    guard.mark_uncertain("U-2")
    guard.resolve_uncertain("U-2", executed=True)
    assert guard.is_duplicate("U-2")
