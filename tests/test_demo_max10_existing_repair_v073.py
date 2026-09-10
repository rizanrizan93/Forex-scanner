from pathlib import Path
from types import SimpleNamespace

import pytest

from fx_scanner.demo_existing_protection_repair import (
    _exact_broker_identity,
    _load_signal_plan,
    _signal_id_from_comment,
)
from fx_scanner.demo_fresh_ready_handoff import (
    DEMO_ORDER_LOT_CAP_ENV,
    DEMO_POSITION_CAP_ENV,
    DEMO_STACKING_ENV,
    load_demo_execution_policy,
)
from fx_scanner.exceptions import ConfigurationError
from fx_scanner.execution.policy import load_execution_policy


ROOT = Path(__file__).resolve().parents[1]


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "signals"
        return _Query(self.rows)


def test_demo_runtime_profile_defaults_keep_bounded_lot_and_no_stacking(monkeypatch):
    monkeypatch.setenv(DEMO_POSITION_CAP_ENV, "10")
    monkeypatch.delenv(DEMO_ORDER_LOT_CAP_ENV, raising=False)
    monkeypatch.delenv(DEMO_STACKING_ENV, raising=False)
    policy = load_demo_execution_policy()
    assert policy.demo_safety["max_concurrent_positions"] == 10
    assert policy.demo_safety["max_order_lots"] == 0.50
    assert policy.demo_safety["allow_same_symbol_stacking"] is False
    assert policy.ctrader["environment"] == "DEMO"
    assert policy.ctrader["require_demo"] is True


def test_demo_runtime_profile_rejects_capacity_above_ten(monkeypatch):
    monkeypatch.setenv(DEMO_POSITION_CAP_ENV, "11")
    with pytest.raises(RuntimeError, match=r"must be in \[1,10\]"):
        load_demo_execution_policy()


def test_execution_policy_ceiling_accepts_ten_and_rejects_eleven(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    source = (ROOT / "config" / "execution.yaml").read_text(encoding="utf-8")
    (config_dir / "execution.yaml").write_text(source, encoding="utf-8")
    assert load_execution_policy(tmp_path).demo_safety["max_concurrent_positions"] == 10

    eleven = source.replace("max_concurrent_positions: 10", "max_concurrent_positions: 11")
    (config_dir / "execution.yaml").write_text(eleven, encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"\[1,10\]"):
        load_execution_policy(tmp_path)


def test_signal_comment_must_be_exact_scanner_uuid():
    signal_id = "9aad9e85-d13c-47ef-80e2-c937dc64293d"
    assert _signal_id_from_comment(f"FXIS:{signal_id}", "FXIS") == signal_id
    assert _signal_id_from_comment(f"OTHER:{signal_id}", "FXIS") is None
    assert _signal_id_from_comment("FXIS:not-a-uuid", "FXIS") is None


def test_signal_plan_requires_symbol_direction_and_structural_stop():
    signal_id = "9aad9e85-d13c-47ef-80e2-c937dc64293d"
    good = {
        "id": signal_id,
        "symbol": "SOLUSD",
        "direction": "SHORT",
        "sl": 103.69825,
        "tp2": 97.005,
    }
    store = SimpleNamespace(client=_Client([good]))
    row = _load_signal_plan(
        store,
        signal_id=signal_id,
        symbol="SOLUSD",
        side="SELL",
    )
    assert row == good

    wrong_side = dict(good, direction="LONG")
    store = SimpleNamespace(client=_Client([wrong_side]))
    assert _load_signal_plan(
        store,
        signal_id=signal_id,
        symbol="SOLUSD",
        side="SELL",
    ) is None


def test_exact_broker_identity_rejects_position_or_side_mismatch():
    trade_data = SimpleNamespace(symbolId=77, tradeSide=2, volume=100)
    position = SimpleNamespace(positionId=41389302, tradeData=trade_data)
    session = SimpleNamespace(
        reconcile=lambda: SimpleNamespace(position=[position]),
        symbol_id=lambda symbol: 77 if symbol == "SOLUSD" else 0,
    )
    assert _exact_broker_identity(
        session,
        position_id=41389302,
        symbol="SOLUSD",
        side="SELL",
    ) == (77, 2, 100)
    assert _exact_broker_identity(
        session,
        position_id=41389302,
        symbol="SOLUSD",
        side="BUY",
    ) is None
    assert _exact_broker_identity(
        session,
        position_id=999,
        symbol="SOLUSD",
        side="SELL",
    ) is None


def test_auto_workflow_repairs_before_new_orders_and_requests_dynamic_profile():
    source = (ROOT / ".github" / "workflows" / "ctrader-demo-auto-pipeline.yml").read_text(
        encoding="utf-8"
    )
    repair = "python -m fx_scanner.demo_existing_protection_repair"
    execute = "python -m fx_scanner.demo_fresh_ready_handoff --limit 10"
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in source
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in source
    assert 'CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING: "1"' in source
    assert 'CTRADER_DEMO_STACK_MIN_SCORE: "85"' in source
    assert 'CTRADER_DEMO_MAX_SAME_SYMBOL_POSITIONS: "3"' in source
    assert source.index(repair) < source.index(execute)


def test_base_executor_same_symbol_and_unprotected_guards_remain_present():
    source = (ROOT / "src" / "fx_scanner" / "execution" / "demo_autotrade.py").read_text(
        encoding="utf-8"
    )
    assert "BROKER_SYMBOL_ALREADY_OPEN" in source
    assert "BROKER_POSITION_UNPROTECTED" in source
