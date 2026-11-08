"""Read-only broker reconcile evidence for BUY050 (no trade requests).

Only active positions can be confirmed with Reconcile. Absence of an open
position does NOT prove rejection, missed entry, or absence of a closed trade.
No order IDs, account numbers, volumes or raw labels are published.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from collect_buy050_shadow_market import Reader

UTC=timezone.utc
PREFIXES={"TPX_13bfa137":"XAUUSD","TPE_13bfa137":"EURUSD","TPB_13bfa137":"BTCUSD"}
TICKS_EPOCH=621355968000000000

def label_signal(label):
    if not isinstance(label,str):
        return None
    parts=label.split("|")
    if len(parts)<2 or parts[0] not in PREFIXES or not parts[1].isdigit():
        return None
    try:
        ticks=int(parts[1])
        if ticks<TICKS_EPOCH:
            return None
        seconds=(ticks-TICKS_EPOCH)/10_000_000
        at=datetime.fromtimestamp(seconds, UTC)
        if at.year<2019 or at>datetime.now(UTC):
            return None
        return PREFIXES[parts[0]],at.replace(microsecond=0).isoformat()
    except (ValueError, OverflowError, OSError):
        return None

def read():
    client=Reader(
        client_id=os.environ["CTRADER_CLIENT_ID"],
        client_secret=os.environ["CTRADER_CLIENT_SECRET"],
        access_token=os.environ["CTRADER_ACCESS_TOKEN"],
        account_id=None, environment="live",refresh_token=None,
        allow_token_refresh=False,request_timeout_seconds=20
    )
    try:
        grants=[a for a in client.granted_accounts()
                if a.is_live and str(a.trader_login).endswith("7903")]
        if len(grants)!=1:
            raise RuntimeError("LIVE_ACCOUNT_BINDING_AMBIGUOUS")
        account=grants[0]
        binding=hashlib.sha256(str(account.trader_login).encode()).hexdigest()
        client.account_id=account.ctid_trader_account_id
        client.connect()
        client.load_symbols(["XAUUSD","EURUSD","BTCUSD"])
        ids={client.symbol_id(symbol):symbol for symbol in PREFIXES.values()}
        data=client.reconcile()
        evidence={}
        foreign=False
        for pos in data.position:
            d=pos.tradeData
            mapped=label_signal(str(getattr(d,"label","")))
            symbol=ids.get(d.symbolId)
            if mapped is None or mapped[0]!=symbol:
                foreign=True
                continue
            s,at=mapped
            key=s+"|"+at
            rec=evidence.setdefault(key,{
                "symbol":s,"signal_at":at,"open_positions":0,
                "sl_protected":True,"tp_protected":True
            })
            rec["open_positions"]+=1
            rec["sl_protected"] &= bool(getattr(pos,"stopLoss",0))
            rec["tp_protected"] &= bool(getattr(pos,"takeProfit",0))
        return {
            "contract":"RIZAN_BUY050_BROKER_OPEN_V1",
            "read_only":True,
            "execution_authority":False,
            "account_binding":binding,
            "observed_at":datetime.now(UTC).isoformat(),
            "foreign_exposure_present":foreign,
            "pending_orders_present":bool(data.order),
            "open_position_evidence":list(evidence.values())[:120],
            "deals_history_checked":False,
        }
    finally:
        client.close()

if __name__=="__main__":
    print(json.dumps(read(),separators=(",",":"),allow_nan=False))
