from types import SimpleNamespace

from fx_scanner.demo_broker_pnl import capture_ctrader_demo_snapshot


class FakeStore:
    def __init__(self):
        self.calls = []

    def publish_broker_telemetry(self, account, positions, **kwargs):
        self.calls.append((account, tuple(positions), kwargs))
        return "snap-1"


class FakeSession:
    account_id = 12345

    def __init__(self):
        self.symbol_name_by_id = {11: "EURUSD"}
        self.symbol_full_by_id = {11: SimpleNamespace(lotSize=10_000_000)}

    def ensure_connected(self):
        return None

    def trader(self):
        return SimpleNamespace(balance=100_000, moneyDigits=2, accessRights=0)

    def unrealized_pnl(self):
        return SimpleNamespace(
            moneyDigits=2,
            positionUnrealizedPnL=[
                SimpleNamespace(positionId=77, netUnrealizedPnL=250),
            ],
        )

    def reconcile(self):
        trade_data = SimpleNamespace(
            symbolId=11,
            tradeSide=1,
            volume=100_000,
            comment="FXIS:test",
            openTimestamp=1_788_000_000_000,
        )
        position = SimpleNamespace(
            positionId=77,
            tradeData=trade_data,
            usedMargin=5_000,
            moneyDigits=2,
            price=1.1000,
            stopLoss=1.0950,
            takeProfit=1.1100,
            swap=-10,
        )
        return SimpleNamespace(position=[position])


def test_capture_ctrader_demo_snapshot_exposes_account_and_position_floating_pnl():
    store = FakeStore()
    snap = capture_ctrader_demo_snapshot(
        session=FakeSession(),
        store=store,
        phase="AFTER",
    )

    assert snap.snapshot_id == "snap-1"
    assert snap.account.balance == 1000.0
    assert snap.account.floating_profit == 2.5
    assert snap.account.equity == 1002.5
    assert snap.account.margin == 50.0
    assert snap.account.margin_free == 952.5
    assert len(snap.positions) == 1
    position = snap.positions[0]
    assert position.symbol == "EURUSD"
    assert position.side == "BUY"
    assert position.volume == 0.01
    assert position.profit == 2.5
    assert position.swap == -0.1
    assert len(store.calls) == 1
    assert store.calls[0][2]["environment"] == "DEMO"
