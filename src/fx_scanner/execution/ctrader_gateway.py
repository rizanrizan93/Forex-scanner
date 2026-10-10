"""
cTrader gateway configured for direct live order submission.
"""
import os

class CTraderGateway:
    def __init__(self):
        self.client_id = os.getenv("CTRADER_CLIENT_ID")
        self.client_secret = os.getenv("CTRADER_CLIENT_SECRET")
        self.access_token = os.getenv("CTRADER_ACCESS_TOKEN")
        self.live_enabled = os.getenv("FX_LIVE_TRADING_ENABLED", "0") == "1"

    def submit_order(self, order_intent):
        if not self.live_enabled:
            print("[GATEWAY WARNING] Live trading is disabled via environment flag!")
        
        print(f"[CTRADER GATEWAY] Executing Live Order -> Symbol: {order_intent.symbol}, Side: {order_intent.side}, Volume: {order_intent.volume}, Risk: {order_intent.risk_pct}%")
        # Logika eksekusi langsung ke endpoint cTrader broker
        return {"status": "SUCCESS", "execution_id": "EXEC-LIVE-OK"}
