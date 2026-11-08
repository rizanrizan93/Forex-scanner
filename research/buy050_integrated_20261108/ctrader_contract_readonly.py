"""Read-only FP Markets cTrader Open API symbol limits. NEVER send orders."""
from __future__ import annotations
import os,json,datetime,sys
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession

def main():
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 kwargs=dict(client_id=os.environ["CTRADER_CLIENT_ID"],client_secret=os.environ["CTRADER_CLIENT_SECRET"],
             access_token=os.environ["CTRADER_ACCESS_TOKEN"],refresh_token=None,
             allow_token_refresh=False,environment="live")
 result={"observed_utc":now,"mode":"READ_ONLY","broker_orders_sent":0,"account_suffix_expected":"7903",
         "symbols":{},"status":"STARTING"}
 discovery=CTraderOpenApiSession(account_id=None,**kwargs)
 try:grants=discovery.granted_accounts()
 finally:discovery.close()
 matches=[x for x in grants if x.is_live and str(x.trader_login).endswith("7903")]
 if len(matches)!=1:
  result["status"]="ACCOUNT_GRANT_NOT_UNIQUE";result["grant_count"]=len(grants);result["match_count"]=len(matches)
  print("BROKER_SYMBOL_METADATA="+json.dumps(result,sort_keys=True));return
 account=matches[0]
 result["broker"]=str(account.broker_title_short)[:64]
 result["account_id_last4"]=str(account.ctid_trader_account_id)[-4:]
 result["scope"]=int(account.permission_scope)
 session=CTraderOpenApiSession(account_id=account.ctid_trader_account_id,**kwargs)
 try:
  session.connect()
  trader=session.trader()
  result["leverageInCents"]=getattr(trader,"leverageInCents",None)
  result["depositAssetId"]=getattr(trader,"depositAssetId",None)
  for sym in ("XAUUSD","EURUSD","BTCUSD"):
   try:
    session.load_symbols([sym])
    o=session.symbol_info(sym)
    attrs=["symbolId","lotSize","minVolume","maxVolume","stepVolume","maxExposure",
           "leverageId","digits","pipPosition","enableShortSelling",
           "slDistance","tpDistance","commissionType","commission",
           "preciseTradingCommissionRate","swapLong","swapShort","measurementUnits"]
    data={k:getattr(o,k,None) for k in attrs}
    for v in ("lotSize","minVolume","maxVolume","stepVolume"):
     if data.get(v) is not None:data[v.replace("Volume","VolumeUnits").replace("lotSize","lotSizeUnits")] = float(data[v])/100.0
    if data.get("lotSize") and data.get("maxVolume"):
     data["maxLotsPerOrder"]=float(data["maxVolume"])/float(data["lotSize"])
    # cTrader return dynamic leverage tiers via readonly ProtoOADynamicLeverageByIDReq.
    leverage_id=data.get("leverageId")
    if leverage_id:
     try:
      from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOADynamicLeverageByIDReq
      req=ProtoOADynamicLeverageByIDReq()
      req.ctidTraderAccountId=account.ctid_trader_account_id
      req.leverageId=int(leverage_id)
      response=session._send_sync(req)
      dynamic=getattr(response,"leverage",None)
      tiers=getattr(dynamic,"tiers",()) if dynamic else ()
      data["leverageTiers"]=[{"notionalUsd":float(getattr(t,"volume",0))/100,
                              "leverage":float(getattr(t,"leverage",0))/100}
                             for t in tiers]
     except Exception as ex:
      data["leverageTierError"]=type(ex).__name__
    result["symbols"][sym]=data
   except Exception as ex:
    result["symbols"][sym]={"state":"UNAVAILABLE","error_type":type(ex).__name__}
  result["status"]="FINISHED"
 finally:session.close()
 print("BROKER_SYMBOL_METADATA="+json.dumps(result,sort_keys=True,default=str))
if __name__=="__main__":
 try:main()
 except Exception as ex:
  print("BROKER_SYMBOL_METADATA="+json.dumps({"status":"ERROR","error_type":type(ex).__name__,
         "orders_sent":0,"account_suffix_expected":"7903"}))
  sys.exit(1)
