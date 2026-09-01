from types import SimpleNamespace

from fx_scanner.execution.ctrader_session import CTraderOpenApiSession


class ReconcileWithoutOptionalField:
    __slots__ = ("ctidTraderAccountId",)

    def __init__(self):
        self.ctidTraderAccountId = 0


class ReconcileWithOptionalField:
    __slots__ = ("ctidTraderAccountId", "returnProtectionOrders")

    def __init__(self):
        self.ctidTraderAccountId = 0
        self.returnProtectionOrders = True


def session(req_cls):
    s = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    s.account_id = 12345
    s.msg = {"ReconcileReq": req_cls}
    s.sent = None

    def send(req, *, client_msg_id):
        s.sent = req
        return SimpleNamespace(position=(), order=())

    s._send_sync = send
    return s


def test_reconcile_works_when_sdk_omits_optional_return_protection_orders():
    s = session(ReconcileWithoutOptionalField)
    res = s.reconcile()
    assert res.position == ()
    assert s.sent.ctidTraderAccountId == 12345


def test_reconcile_sets_optional_return_protection_orders_false_when_available():
    s = session(ReconcileWithOptionalField)
    s.reconcile()
    assert s.sent.ctidTraderAccountId == 12345
    assert s.sent.returnProtectionOrders is False
