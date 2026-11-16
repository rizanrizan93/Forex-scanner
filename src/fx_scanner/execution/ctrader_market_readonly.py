"""Market-data-only cTrader transport; no trading or token rotation requests."""
from .ctrader_session import CTraderOpenApiSession


class ReadOnly(CTraderOpenApiSession):
    allowed = frozenset({
        'ProtoOAApplicationAuthReq', 'ProtoOAGetAccountListByAccessTokenReq',
        'ProtoOAAccountAuthReq', 'ProtoOASymbolsListReq', 'ProtoOASymbolByIdReq',
        'ProtoOAGetTrendbarsReq', 'ProtoHeartbeatEvent',
    })

    def _send_sync(self, message, **kwargs):
        if message.DESCRIPTOR.name not in self.allowed:
            raise RuntimeError('XAU_MARKET_READ_ONLY_PROTOCOL_GUARD')
        return super()._send_sync(message, **kwargs)
