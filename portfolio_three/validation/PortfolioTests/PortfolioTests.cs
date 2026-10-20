using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;
using E=Rizan.Portfolio.Eur;

int checks=0;void Check(bool ok,string reason){if(!ok)throw new Exception(reason);checks++;}
var host=new TestHost{EnableTrading=false,ExpectedAccount="1237903",BridgeUrl="wss://example.invalid:25345",BridgeToken="fixture"};host.CreateEngines();
var x=host.Xau!;var e=host.Eur!;Init(x,true);Init(e,false);
Check(host.PortfolioReady,"BOTH_READY");
Check(host.CapQuantity(x,20,5,1,1,2000,.2)==4,"WHOLE_ACCOUNT_RISK_CAP");
Set(e,"_bridgeReady",false);Check(host.CapQuantity(x,20,5,1,1,2000,.2)==0,"WAIT_BOTH_RECOVERED");Set(e,"_bridgeReady",true);
host.Positions.Add(new(){SymbolName="EURUSD",Label="RZEF245|1|0|1|1",VolumeInUnits=1000,EntryPrice=1.1,StopLoss=1.09,TakeProfit=1.2,TradeType=TradeType.Buy});
Check(host.NoForeignExposure(),"OTHER_ENGINE_POSITION_ALLOWED");Check(host.CapQuantity(x,20,5,1,1,2000,.2)==2,"OPEN_OTHER_LEG_RISK_RESERVED");
host.Positions.Clear();var es=(E.Checkpoint)Get(e,"_state");es.Basket=new(){Side=1,Entry=1.1,Stop=1.09};es.PendingLabel="RZEF245|1|0|1|1";es.PendingChildren=1;es.PendingFirstFill=true;
Check(e.PendingRisk>10,"PENDING_WAL_RISK_RESERVED");Check(host.CapQuantity(x,20,5,1,1,2000,.2)==2,"OTHER_PENDING_LIMITS_CAP");
host.Positions.Add(new(){SymbolName="EURUSD",Label=es.PendingLabel,VolumeInUnits=1000,EntryPrice=1.1,StopLoss=1.09,TakeProfit=1.2,TradeType=TradeType.Buy});Check(e.PendingRisk==0,"FILLED_PENDING_NOT_DOUBLE_COUNTED");
host.Positions.Clear();es.PendingChildren=0;es.PendingLabel="";es.Basket=null;
host.Positions.Add(new(){SymbolName="EURUSD",Label="MANUAL",StopLoss=1,TakeProfit=2,VolumeInUnits=1000,EntryPrice=1.1});Check(!host.NoForeignExposure(),"FOREIGN_POSITION_BLOCK");Check(host.CapQuantity(x,20,5,1,1,2000,.2)==0,"NO_ORDERS_WITH_FOREIGN_POSITION");host.Positions.Clear();
host.PendingOrders.Add(new());Check(!host.NoForeignExposure(),"FOREIGN_PENDING_BLOCK");host.PendingOrders.Clear();
host.Account.Margin=50;Check(host.CapQuantity(x,20,1,1,1,2000,.2)==0,"GLOBAL_MARGIN_CAP");host.Account.Margin=0;
host.Symbols.GetSymbol("XAUUSD").Bid=2000;host.Symbols.GetSymbol("XAUUSD").Ask=2000.2;host.Symbols.GetSymbol("EURUSD").Bid=1.1;host.Symbols.GetSymbol("EURUSD").Ask=1.10001;
host.Send(TradeType.Buy,"XAUUSD",1,"RZXRC1|1|0|1|1",100,200,"fixture");host.Send(TradeType.Buy,"EURUSD",1000,"RZEF245|1|0|1|1",100,200,"fixture");
double equity=host.Account.Equity;host.Symbols.GetSymbol("XAUUSD").Bid+=1;host.Symbols.GetSymbol("EURUSD").Bid+=.001;host.Mark();Check(Math.Abs(host.Account.Equity-equity-2)<1e-8,"ONE_WALLET_MARKS_BOTH_SYMBOLS");
Check(host.Positions.Count==2&&host.Positions.Select(p=>p.SymbolName).Distinct().Count()==2,"MULTI_SYMBOL_BROKER_ORDERS");foreach(var p in host.Positions.ToArray())host.ClosePosition(p);Check(host.Positions.Count==0&&host.History.Count==2,"SHARED_CLOSE_HISTORY");
// Both generated contexts use generation-fenced sockets and preserve independent WAL keys.
foreach(var context in new EngineContext[]{x,e}){
 for(int i=0;i<100;i++){
  Set(context,"_bridge",null!);Set(context,"_connecting",false);Set(context,"_stopping",false);Set(context,"_bridgeReady",false);
  Call(context,"ConnectBridge");var socket=(WebSocketClient)Get(context,"_bridge");
  socket.Emit("{\"type\":\"ready\",\"revision\":0,\"state\":null}");Check((bool)Get(context,"_bridgeReady"),"SOCKET_HANDSHAKE");
  Call(context,"BridgeOffline","TEST_DROP");Check(!(bool)Get(context,"_bridgeReady"),"OFFLINE_FAIL_CLOSED");Call(context,"ConnectBridge");var next=(WebSocketClient)Get(context,"_bridge");Check(!ReferenceEquals(socket,next),"NEW_SOCKET_ON_RECONNECT");
  socket.Emit("{\"type\":\"error\",\"code\":\"AUTH_FAILED\"}");Check(!(bool)Get(context,"_stopping"),"LATE_SOCKET_CALLBACK_FENCED");Call(context,"BridgeOffline","TEST_RESET");
 }
}
Check(host.LocalStorage.Values.ContainsKey("XAUUSD fixture")&&host.LocalStorage.Values.ContainsKey("EURUSD fixture"),"INDEPENDENT_CHECKPOINT_KEYS");
Check(host.Requests==2,"TRANSPORT_TEST_NO_EXTRA_ORDERS");
// Regression: old positions can close while a NEW add intent is awaiting ACK.
// Only a locally prepared, definitely unsent request is safe to cancel.
foreach(var flags in new[]{(Prepared:true,Submitted:false),(Prepared:false,Submitted:false),(Prepared:true,Submitted:true)}){
 Init(e,false);var checkpoint=(E.Checkpoint)Get(e,"_state");var at=host.Server.TimeInUtc.AddMinutes(-10);
 checkpoint.Basket=new(){AtUtc=at,ExitUtc=host.Server.TimeInUtc.AddMinutes(30),Side=1,Entry=1.1,Stop=1.09,Target=1.2,OriginalDistance=.01,BestExit=1.1,Accepted=new[]{1,0,0,0},QueueStage=1,QueueRemaining=1,NextStage=2};
 checkpoint.PendingLabel="RZEF245|"+at.Ticks+"|1|2|1";checkpoint.PendingChildren=1;checkpoint.PendingStage=1;
 Set(e,"_pendingPreparedHere",flags.Prepared);Set(e,"_pendingSubmitted",flags.Submitted);
 long preparedRevision=checkpoint.Revision;
 Call(e,"ManagePositions",host.Server.TimeInUtc);
 bool safe=flags.Prepared&&!flags.Submitted;
 Check(checkpoint.Quarantined!=safe,"ORPHAN_LOCAL_KNOWN_UNSENT_ONLY");
 Check((checkpoint.PendingLabel=="")==safe,"UNCERTAIN_WAL_PRESERVED");
 if(safe){Call(e,"ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=10,client_revision=preparedRevision}));Check(host.Requests==2,"LATE_ACK_AFTER_CANCEL_DOES_NOT_SEND");}
}
Check(host.Requests==2,"ORPHAN_RECOVERY_NO_DUPLICATE_ORDER");
host.Finish();Check(!host.PortfolioReady,"STOP_FENCES_ALL_ENGINE_CALLBACKS");Check(host.CapQuantity(x,20,1,1,1,2000,.2)==0,"NO_NEW_INTENT_AFTER_HOST_STOP");
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,ReconnectCycles=200,NativeHost=false,Orders=host.Requests}));
void Init(EngineContext c,bool isXau){object state=isXau?new X.Checkpoint{AccountNumber=host.Account.Number,Symbol="XAUUSD",ContractHash=X.FrozenContract.Xau.Hash,ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",PeakEquity=100}:new E.Checkpoint{AccountNumber=host.Account.Number,Symbol="EURUSD",ContractHash=E.F0245Policy.ConfigHash,ExecutionModel=E.EurBatchExecution.Model,PeakEquity=100};Set(c,"_state",state);Set(c,"_bridgeReady",true);Set(c,"_storageKey",(isXau?"XAUUSD":"EURUSD")+" fixture");Set(c,"_stateKey",(isXau?"RZXRC1":"RZEF245")+":"+host.Account.Number+":"+(isXau?"XAUUSD":"EURUSD"));}
Type T(EngineContext c)=>c is X.RizanRobot?typeof(X.RizanRobot):typeof(E.RizanRobot);
object Get(EngineContext c,string n)=>T(c).GetField(n,BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(c)!;
void Set(EngineContext c,string n,object value)=>T(c).GetField(n,BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(c,value);
void Call(EngineContext c,string n,params object[] values){try{T(c).GetMethod(n,BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(c,values);}catch(TargetInvocationException ex){throw ex.InnerException!;}}
sealed class TestHost:RizanPortfolio {public TestHost(){EnableBtc=false;}public void Finish()=>OnStop();}
