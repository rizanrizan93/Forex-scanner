from __future__ import annotations

from dataclasses import replace

from .broker_gateway import BrokerPreflight
from .ctrader_gateway import CTraderExecutionGateway, CTraderPreparedOrder, _money
from .models import OrderIntent, OrderSide


class LiveManualCTraderExecutionGateway(CTraderExecutionGateway):
    """LIVE approval adapter that normalizes ProtoOAExpectedMarginRes monetary units.

    ProtoOAExpectedMarginRes.moneyDigits applies to buyMargin/sellMargin. The
    legacy gateway stores the protocol integer on CTraderPreparedOrder; this
    adapter recomputes the estimate and converts it to deposit-currency units
    before the LIVE margin-ratio guard consumes it. Order construction and
    submission remain delegated to the canonical cTrader gateway.
    """

    def preflight(self, intent: OrderIntent, order_config: dict) -> BrokerPreflight:
        preflight = super().preflight(intent, order_config)
        if not preflight.accepted or not isinstance(preflight.request, CTraderPreparedOrder):
            return preflight
        prepared = preflight.request
        margin_res = self.session.expected_margin(prepared.symbol_id, prepared.volume_cents)
        margins = tuple(getattr(margin_res, "margin", ()))
        if not margins:
            return BrokerPreflight(
                self.backend,
                False,
                "EXPECTED_MARGIN_EMPTY",
                "cTrader expected-margin response returned no margin rows",
                None,
            )
        first = margins[0]
        raw = first.buyMargin if intent.side == OrderSide.BUY else first.sellMargin
        digits = int(getattr(margin_res, "moneyDigits", 0) or 0)
        expected_margin = _money(raw, digits)
        if expected_margin <= 0:
            return BrokerPreflight(
                self.backend,
                False,
                "EXPECTED_MARGIN_INVALID",
                "cTrader normalized expected margin is not positive",
                None,
            )
        return BrokerPreflight(
            backend=preflight.backend,
            accepted=True,
            code=preflight.code,
            message=preflight.message,
            request=replace(prepared, expected_margin=expected_margin),
        )
