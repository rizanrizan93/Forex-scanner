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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from collect_buy050_shadow_market import Reader
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOADealListReq, ProtoOAOrderListReq

class AuditReader(Reader):
    # Historical retrieval only; explicitly excludes all new/amend/cancel order requests.
    allowed=Reader.allowed | frozenset({'ProtoOADealListReq','ProtoOAOrderListReq'})

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
    client=AuditReader(
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
        # Query broker-certified execution history for this account. Deal and
        # order requests are read-only historical endpoints, never trade actions.
        # Time is bounded to 48h. hasMore means evidence is only partial.
        clock=datetime.now(UTC)
        since=clock-timedelta(hours=48)
        from_ms=int(since.timestamp()*1000)
        through_ms=int(clock.timestamp()*1000)
        history={"deals_history_checked":False,"orders_history_checked":False,
                 "from_at":since.isoformat(),"through_at":clock.isoformat(),
                 "executions":[]}
        def audit_row(symbol,at,kind,signal_at):
            if kind not in {
                "BROKER_ORDER_ACCEPTED","BROKER_ORDER_FILLED",
                "BROKER_ORDER_REJECTED","BROKER_ORDER_CANCELLED",
                "BROKER_ORDER_EXPIRED","BROKER_DEAL_FILLED",
                "BROKER_DEAL_PARTIAL","BROKER_DEAL_REJECTED",
                "BROKER_DEAL_ERROR","BROKER_DEAL_NO_RESPONSE"
            }:
                return
            if not at or at<since or at>clock+timedelta(seconds=5):
                return
            history["executions"].append({
                "symbol":symbol,"signal_at":signal_at,
                "observed_at":at.isoformat(),"event":kind
            })
        def from_ms_at(value):
            try:
                return datetime.fromtimestamp(int(value)/1000,UTC) if int(value)>0 else None
            except (TypeError,ValueError,OverflowError,OSError):
                return None
        try:
            req=ProtoOADealListReq(
                ctidTraderAccountId=client.account_id,
                fromTimestamp=from_ms,toTimestamp=through_ms,maxRows=1000
            )
            response=client._send_sync(req)
            history["deals_history_checked"]=not bool(getattr(response,"hasMore",False))
            for deal in response.deal:
                mapped=label_signal(getattr(deal,"label",""))
                if not mapped:
                    continue
                # A closing deal must not be called an entry fill.
                try:
                    if deal.HasField("closePositionDetail"):
                        continue
                except (AttributeError,TypeError,ValueError):
                    continue
                sym,signal_at=mapped
                if ids.get(deal.symbolId)!=sym:
                    continue
                status=int(deal.dealStatus)
                kind={2:"BROKER_DEAL_FILLED",3:"BROKER_DEAL_PARTIAL",
                      4:"BROKER_DEAL_REJECTED",5:"BROKER_DEAL_REJECTED",
                      6:"BROKER_DEAL_ERROR",7:"BROKER_DEAL_NO_RESPONSE"}.get(status)
                audit_row(sym,from_ms_at(deal.utcLastUpdateTimestamp or deal.executionTimestamp or deal.createTimestamp),kind,signal_at)
        except Exception:
            # A failed historical request never proves absence of deals.
            history["deals_history_checked"]=False
        try:
            req=ProtoOAOrderListReq(
                ctidTraderAccountId=client.account_id,
                fromTimestamp=from_ms,toTimestamp=through_ms
            )
            response=client._send_sync(req)
            history["orders_history_checked"]=not bool(getattr(response,"hasMore",False))
            for order in response.order:
                if bool(getattr(order,"closingOrder",False)):
                    continue
                mapped=label_signal(getattr(order.tradeData,"label",""))
                if not mapped or ids.get(order.tradeData.symbolId)!=mapped[0]:
                    continue
                kind={1:"BROKER_ORDER_ACCEPTED",2:"BROKER_ORDER_FILLED",
                      3:"BROKER_ORDER_REJECTED",4:"BROKER_ORDER_EXPIRED",
                      5:"BROKER_ORDER_CANCELLED"}.get(int(order.orderStatus))
                audit_row(mapped[0],from_ms_at(getattr(order,"utcLastUpdateTimestamp",0)),kind,mapped[1])
        except Exception:
            history["orders_history_checked"]=False
        # Deduplicate repeated broker records; never expose IDs, prices or raw labels.
        uniq={}
        for item in history["executions"]:
            uniq[(item["symbol"],item["signal_at"],item["event"],item["observed_at"])]=item
        history["executions"]=list(uniq.values())[-180:]
        return {
            "contract":"RIZAN_BUY050_BROKER_OPEN_V1",
            "read_only":True,
            "execution_authority":False,
            "account_binding":binding,
            "observed_at":datetime.now(UTC).isoformat(),
            "foreign_exposure_present":foreign,
            "pending_orders_present":bool(data.order),
            "open_position_evidence":list(evidence.values())[:120],
            "deals_history_checked":history["deals_history_checked"],
            "orders_history_checked":history["orders_history_checked"],
            "history_from":history["from_at"],
            "history_to":history["through_at"],
            "execution_evidence":history["executions"],
        }
    finally:
        client.close()

if __name__=="__main__":
    print(json.dumps(read(),separators=(",",":"),allow_nan=False))
