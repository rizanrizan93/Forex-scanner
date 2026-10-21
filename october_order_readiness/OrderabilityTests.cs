using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;
using E=Rizan.Portfolio.Eur;
var results=new List<object>();
foreach(bool xau in new[]{true,false})foreach(int side in new[]{1,-1})foreach(string scenario in new[]{"VALID_ACK","NO_ACK","DISABLED","WIDE_SPREAD","FOREIGN_EXPOSURE","STALE_BRIDGE"}){
 var h=new TestHost{EnableTrading=scenario!="DISABLED",EnableBtc=false,EnableXau=xau,EnableEur=!xau,ExpectedAccount="1237903",BridgeUrl="wss://fixture.invalid:25345",BridgeToken=new string('x',48)};
 h.Server.TimeInUtc=new DateTime(2026,10,19,xau?14:10,0,0,DateTimeKind.Utc);h.Account.Balance=h.Account.Equity=100000;h.CreateEngines();
 EngineContext c=xau?h.Xau!:h.Eur!;Type t=xau?typeof(X.RizanRobot):typeof(E.RizanRobot);const BindingFlags bf=BindingFlags.Instance|BindingFlags.NonPublic;
 object Get(string n)=>t.GetField(n,bf)!.GetValue(c)!;void Set(string n,object v)=>t.GetField(n,bf)!.SetValue(c,v);
 void Call(string n,params object[] v){try{t.GetMethod(n,bf)!.Invoke(c,v);}catch(TargetInvocationException e){throw e.InnerException!;}}
 var wire=new WebSocketClient();Set("_bridge",wire);Set("_bridgeReady",true);Set("_lastBridgeAck",h.Server.TimeInUtc);Set("_storageKey","isolated-orderability-fixture");Set("_stateKey","isolated-orderability-fixture");
 Set("_state",xau?new X.Checkpoint{AccountNumber=h.Account.Number,Symbol="XAUUSD",ContractHash=X.FrozenContract.Xau.Hash,ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",PeakEquity=100000}:new E.Checkpoint{AccountNumber=h.Account.Number,Symbol="EURUSD",ContractHash=E.F0245Policy.ConfigHash,ExecutionModel=E.EurBatchExecution.Model,PeakEquity=100000});
 var q=h.Symbols.GetSymbol(xau?"XAUUSD":"EURUSD");q.Bid=xau?2000:1.1;q.Ask=q.Bid+(xau?.2:.00001);
 if(xau)Set("_snapshot",new X.ExternalSnapshot{ProducedUtc=h.Server.TimeInUtc,CoverageFromUtc=h.Server.TimeInUtc.AddMinutes(-30),CoverageToUtc=h.Server.TimeInUtc.AddMinutes(495),ForexFactoryOk=true,BlsOk=true,Dgs10=new(){Delta=-side,AvailableUtc=h.Server.TimeInUtc},Dfii10=new(){Delta=-side,AvailableUtc=h.Server.TimeInUtc}});
 if(scenario=="WIDE_SPREAD")q.Ask=q.Bid+(xau?1.6:.00023);
 if(scenario=="FOREIGN_EXPOSURE")h.Positions.Add(new(){SymbolName=q.Name,Label="MANUAL",VolumeInUnits=q.VolumeInUnitsMin,EntryPrice=q.Bid,StopLoss=q.Bid-1,TakeProfit=q.Bid+1});
 if(scenario=="STALE_BRIDGE")Set("_lastBridgeAck",h.Server.TimeInUtc.AddSeconds(-31));
 object signal=xau?new X.Signal(h.Server.TimeInUtc,side,0,5,2000-side*10):new E.Signal(h.Server.TimeInUtc,side,.002,0,0);
 Call("PrepareBasket",signal,h.Server.TimeInUtc);Call("Persist");
 long remote=0;int saveCursor=0;void AckAll(){for(int i=0;i<20;i++){if(saveCursor>=wire.Sent.Count)return;using var d=JsonDocument.Parse(wire.Sent[saveCursor++]);if(d.RootElement.GetProperty("type").GetString()=="save")Call("ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=++remote,client_revision=d.RootElement.GetProperty("client_revision").GetInt64()}));}throw new Exception("ACK_LOOP");}
 // Initial basket persistence may be acknowledged; the entry intent ACK is withheld in NO_ACK.
 AckAll();if(scenario=="STALE_BRIDGE")Set("_lastBridgeAck",h.Server.TimeInUtc.AddSeconds(-31));Call("ProcessQueue",h.Server.TimeInUtc);int beforeIntentAck=h.Requests;
 if(scenario!="NO_ACK"){AckAll();Call("ProcessQueue",h.Server.TimeInUtc);}
 var st=Get("_state");bool quarantined=(bool)st.GetType().GetProperty("Quarantined")!.GetValue(st)!;
 bool expected=scenario=="VALID_ACK";bool passed=h.Requests==(expected?1:0)&&(!expected||h.Positions.Count==1&&h.Positions[0].StopLoss.HasValue&&h.Positions[0].TakeProfit.HasValue&&!quarantined)&&beforeIntentAck==0;
 var row=new{symbol=q.Name,direction=side==1?"BUY":"SELL",scenario,passed,broker_requests=h.Requests,before_intent_ack=beforeIntentAck,positions=h.Positions.Count,status=(string)Get("_status"),quarantined,scope="ISOLATED_API_STUB_EXECUTION_FIXTURE_NO_NETWORK_NO_LIVE_ORDER"};results.Add(row);Console.WriteLine(JsonSerializer.Serialize(row));
 if(!passed)throw new Exception("ORDERABILITY_FAILED "+q.Name+" "+side+" "+scenario);
}
File.WriteAllText("publish/ORDERABILITY_FIXTURES.json",JsonSerializer.Serialize(results,new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Cases=results.Count,NativeBrokerAcknowledgement=false,LiveOrders=0}));
sealed class TestHost:RizanPortfolio{}
