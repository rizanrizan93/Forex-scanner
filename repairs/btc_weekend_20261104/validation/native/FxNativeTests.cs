using System;using System.Linq;using System.Reflection;using System.Text.Json;using cAlgo.API;using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;using E=Rizan.Portfolio.Eur;
int checks=0;void Check(bool v,string why){checks++;if(!v)throw new Exception(why);}
DateTime at=new(2026,10,15,12,0,0,DateTimeKind.Utc);
{
 Check(FrozenR3.Matches()&&RP.C.Id=="F005_BTC10"&&RP.C.XauStop==2.8&&RP.C.XauTarget==5,"BTC10_EXACT_PROFILE");
 var c=RP.X(X.FrozenContract.Xau);Check(c.StopAtrMultiplier==2.8&&c.TargetR==5&&c.BalanceStepUsd==51.25&&Math.Abs(c.RiskFraction-.1815)<1e-12,"XAU_EFFECTIVE_CONTRACT");
 var m=Enumerable.Range(0,15).Select(i=>new X.Candle(at.AddMinutes((i-15)*5),99.5,100,99,99.5,5)).ToList();
 var atr=Enumerable.Repeat(1.4,15).ToArray();
 m[14]=new(at.AddMinutes(-5),100.8,101,98,98.1,5);
 Check(CompressionEntry.Evaluate(m,atr,14,-1,at,48)?.Side==-1,"SELL_ACCEPTS_COMPRESSION_BETWEEN_POINT7_POINT8");
 Check(CompressionEntry.Evaluate(m,atr,14,-1,at,47)==null,"SELL_REQUIRES_H1_48");
 m[14]=m[14] with{Count=4};Check(CompressionEntry.Evaluate(m,atr,14,-1,at,60)==null,"SELL_REQUIRES_M5_5");
 m[14]=new(at.AddMinutes(-5),99.1,102,99,101.9,5);
 Check(CompressionEntry.Evaluate(m,atr,14,1,at)==null,"BUY_DOES_NOT_USE_SELL_POINT8_THRESHOLD");
 atr[13]=1.6;Check(CompressionEntry.Evaluate(m,atr,14,1,at)?.Side==1,"BUY_POINT7_BODY_POINT5");
 Check(CompressionEntry.Evaluate(m,atr,14,-1,at)==null,"BUY_REQUIRES_UP_BIAS");
 Check(CompressionEntry.Evaluate(m,atr,14,1,at.AddMinutes(1))==null,"NO_REUSE_AT_LATER_M1");
 Check(!CompressionEntry.EligibleTime(at.AddDays(2)),"NO_WEEKEND_ENTRY");
 Check(!CompressionEntry.EligibleTime(at.AddHours(5)),"SESSION_END_EXCLUSIVE");
 atr[14]=double.NaN;Check(CompressionEntry.Evaluate(m,atr,14,1,at)==null,"NO_NAN_ATR");
 var invalid=new TestHost{XauTargetR=5.5};invalid.Start();Check(invalid.Stopped&&invalid.Requests==0,"FROZEN_TP_DRIFT_BLOCKED");
}
foreach(bool xau in new[]{true,false})foreach(int side in new[]{1,-1}){
 var h=new TestHost{EnableTrading=true,EnableXau=xau,EnableEur=!xau,EnableBtc=false,BridgeUrl="wss://test.invalid:25345/btc10/",BridgeToken=new string('x',32)};h.ExpectedAccount=h.Account.Number.ToString();h.Account.Balance=h.Account.Equity=1000000;h.Server.TimeInUtc=at;
 string name=xau?"XAUUSD":"EURUSD";var sym=h.Symbols.GetSymbol(name);sym.Bid=xau?2000:1.1;sym.Ask=sym.Bid+(xau?.1:.00001);
 var bars=new Bars();for(int i=200;i>0;i--){bars.OpenTimes.Add(at.AddMinutes(-i));bars.OpenPrices.Add(sym.Bid);bars.HighPrices.Add(sym.Bid);bars.LowPrices.Add(sym.Bid);bars.ClosePrices.Add(sym.Bid);}h.MarketData.Provider=(_,_)=>bars;
 h.CreateEngines();EngineContext engine=xau?h.Xau!:h.Eur!;Type t=xau?typeof(X.RizanRobot):typeof(E.RizanRobot);engine.OnStart();var socket=(WebSocketClient)t.GetField("_bridge",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(engine)!;
 socket.Emit("{\"type\":\"ready\",\"revision\":0,\"state\":null}");int cursor=0;long revision=0;
 void Ack(){int guard=0;while(cursor<socket.Sent.Count&&guard++<1000){using var doc=JsonDocument.Parse(socket.Sent[cursor++]);var r=doc.RootElement;switch(r.GetProperty("type").GetString()){case "save":socket.Emit(JsonSerializer.Serialize(new{type="ack",client_revision=r.GetProperty("client_revision").GetInt64(),revision=++revision}));break;case "ping":socket.Emit("{\"type\":\"pong\"}");break;}}}
 Ack();socket.Emit(JsonSerializer.Serialize(new{type="snapshot",data=new X.ExternalSnapshot{ProducedUtc=at,CoverageFromUtc=at.AddHours(-1),CoverageToUtc=at.AddHours(10),ForexFactoryOk=true,BlsOk=true,Dgs10=new(){Delta=-side,AvailableUtc=at.AddDays(-1)},Dfii10=new(){Delta=-side,AvailableUtc=at.AddDays(-1)}}}));Ack();
 Check(engine.RecoveryReady&&h.PortfolioReady,name+"_RECOVERY_READY");object signal=xau?new X.Signal(at,side,0,2,side>0?1994:2006):new E.Signal(at,side,.001,0,0,side==1);
 t.GetMethod("PrepareBasket",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(engine,new[]{signal,(object)at});Check(h.Requests==0,name+"_NO_ORDER_ON_PREPARE");
 engine.OnTimer();Check(h.Requests==0,name+"_NO_ORDER_BEFORE_DURABLE_ACK");Ack();
 for(int i=0;i<8&&h.Requests==0;i++){h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(1);engine.OnTimer();Ack();}
 Check(h.Requests>0&&h.Positions.Count>0,name+"_NATIVE_MARKET_ORDER_SENT");Check(h.Positions.All(p=>p.StopLoss!=null&&p.TakeProfit!=null),name+"_ALL_ORDERS_PROTECTED");Check(h.Positions.All(p=>p.TradeType==(side>0?TradeType.Buy:TradeType.Sell)),name+"_BUY_SELL_DIRECTION");
 if(xau){var state=t.GetField("_state",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(engine)!;var basket=(X.Basket)state.GetType().GetProperty("Basket")!.GetValue(state)!;Check(Math.Abs((basket.Target-basket.Entry)/(basket.Entry-basket.Stop)-5)<1e-10,"XAU_BASKET_EXACT_TP5R");Check(Math.Abs(basket.Entry-basket.Stop)>=5.6-1e-8,"XAU_SL_AT_LEAST_2_POINT8_ATR");}
 Check(h.OpenRisk()<=Math.Min(h.Account.Balance,h.Account.Equity)*.2075+1e-5,name+"_RISK_CAP");Check(h.Account.Margin<=Math.Min(h.Account.Balance,h.Account.Equity)*.5+1e-5,name+"_MARGIN_CAP");
 if(!xau&&side>0){var state=t.GetField("_state",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(engine)!;var basket=(E.Basket)state.GetType().GetProperty("Basket")!.GetValue(state)!;Check(basket.Scale==.1,"ASIA_EXPLICIT_SCALE_CAP");}
 int before=h.Requests;h.EnableTrading=false;engine.SetParameters();for(int i=0;i<5;i++){h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(1);engine.OnTimer();Ack();}Check(h.Requests==before,name+"_OFF_STOPS_NEW_ORDERS");
 engine.OnStop();
 if(side==-1&&args.Length>0){string key=X.FrozenCore.CheckpointStorageKey((xau?FrozenR3.XauPrefix:FrozenR3.EurPrefix)+":"+h.Account.Number+":"+name);System.IO.File.WriteAllText(System.IO.Path.Combine(args[0],xau?"XAU.json":"EUR.json"),h.LocalStorage.Values[key]);}
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,ProductionClasses=true,FakeBrokerOnly=true,RealOrders=0,XAU=true,EUR=true,BuyAndSell=true,NoOrderBeforeAck=true}));
sealed class TestHost:RizanPortfolio{public void Start()=>OnStart();}
