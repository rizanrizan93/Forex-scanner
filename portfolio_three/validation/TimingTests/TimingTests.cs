using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;
using E=Rizan.Portfolio.Eur;

int checks=0,orders=0;
void Check(bool ok,string why){if(!ok)throw new Exception(why);checks++;}
foreach(bool xau in new[]{true,false})
{
    var (h,c)=Setup(xau);
    Check(!c.RecoveryReady,"COLD_START_NEEDS_HANDSHAKE");
    Handshake(c);
    Check(c.RecoveryReady,"INITIAL_SYNC_READY");
    Check((bool)Get(c,"_continuityReady"),"SESSION_AUTHORIZED");
    Call(c,"BridgeOffline","OUTAGE");
    Check(c.RecoveryReady&&h.PortfolioReady,"TRANSPORT_ALONE_DOES_NOT_BLOCK");
    h.Server.TimeInUtc=h.Server.TimeInUtc.AddDays(1);
    Basket(h,c,xau);
    Call(c,"ProcessQueue",h.Server.TimeInUtc);
    Check(h.Requests==1,"OFFLINE_ENTRY_AFTER_ONE_DAY");orders+=h.Requests;
    Check(h.Positions.Count==1&&h.Positions[0].StopLoss!=null&&h.Positions[0].TakeProfit!=null,"BROKER_PROTECTION");
    Check(!(bool)Get(State(c),"Quarantined"),"OFFLINE_ACCEPTED_WITHIN_BUDGET");
    Call(c,"ProcessQueue",h.Server.TimeInUtc);
    Check(h.Requests==1,"NO_DUPLICATE_QUEUE_SEND");
    var before=JsonSerializer.Serialize(State(c));var rev=(long)Get(State(c),"Revision");
    Call(c,"ConnectBridge");
    // Remote replica is stale: keep the whole local basket and watermark.
    var remote=xau?(object)new X.Checkpoint{ContractHash=X.FrozenContract.Xau.Hash,Symbol="XAUUSD",AccountNumber=h.Account.Number,ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",PeakEquity=100}:new E.Checkpoint{Schema=3,ContractHash=E.F0245Policy.ConfigHash,Symbol="EURUSD",AccountNumber=h.Account.Number,ExecutionModel=E.EurBatchExecution.Model,PeakEquity=100};
    Call(c,"ReceiveBridge",JsonSerializer.Serialize(new{type="ready",revision=1,state=remote},Options(c)));
    Check(!(bool)Get(State(c),"Quarantined"),"RECONNECT_RECONCILES_OWNED_POSITION");
    Check((long)Get(State(c),"Revision")>rev,"LOCAL_REVISION_NOT_REWOUND");
    Check(h.Requests==1,"RECONNECT_NO_DUPLICATE_ORDER");
    // Restart never inherits session authorization from stored checkpoints.
    var (rh,rc)=Setup(xau);
    rh.Server.TimeInUtc=h.Server.TimeInUtc;
    foreach(var kv in h.LocalStorage.Values)rh.LocalStorage.Values[kv.Key]=kv.Value;
    rh.Positions.AddRange(h.Positions);rh.Account.Balance=h.Account.Balance;rh.Mark();
    rh.Start();rc=xau?rh.Xau!:rh.Eur!;
    Check(!rc.RecoveryReady,"RESTART_CANNOT_OFFLINE_AUTHORIZE");
    Call(rc,"ReceiveBridge","{\"type\":\"ready\",\"revision\":0,\"state\":null}");
    Check(rc.RecoveryReady&&rh.Requests==0&&rh.Positions.Count==1,"ACTUAL_RESTART_RECONCILES_WITHOUT_DUPLICATE");

    foreach(string failure in new[]{"FailWrite","FailFlush","CorruptRead"})
    {
        var (fh,fc)=Setup(xau);Handshake(fc);Call(fc,"BridgeOffline","OUTAGE");
        typeof(Store).GetField(failure)!.SetValue(fh.LocalStorage,true);
        Call(fc,"Changed");Call(fc,"Persist");
        Check(!fc.RecoveryReady,"STORAGE_FAILURE_BLOCKS_"+failure);
        Check((string)Get(State(fc),"QuarantineReason")=="LOCAL_CHECKPOINT_WRITE_FAILED","STORAGE_FAILURE_REASON");
        Check(!(bool)Prop(fc,"Durable"),"FAILED_WRITE_NOT_DURABLE");
    }
    foreach(string code in new[]{"LEASE_BUSY","AUTH_FAILED"})
    {
        var (fh,fc)=Setup(xau);Handshake(fc);
        Call(fc,"ReceiveBridge",JsonSerializer.Serialize(new{type="error",code}));
        Check(!fc.RecoveryReady,"OWNERSHIP_FAILURE_BLOCKS_"+code);
    }
    // A remote writer ahead of a continuously active process must never replace it.
    {
        var (fh,fc)=Setup(xau);Handshake(fc);Call(fc,"BridgeOffline","OUTAGE");
        var old=State(fc);var json=JsonSerializer.Serialize(old,Options(fc));
        var node=System.Text.Json.Nodes.JsonNode.Parse(json)!;node["Revision"]=(long)Get(old,"Revision")+100;
        Call(fc,"ConnectBridge");Call(fc,"ReceiveBridge","{\"type\":\"ready\",\"revision\":9,\"state\":"+node.ToJsonString()+"}");
        Check(ReferenceEquals(old,State(fc)),"REMOTE_AHEAD_NEVER_OVERWRITES");
        Check(!fc.RecoveryReady&&(bool)Get(State(fc),"Quarantined"),"REMOTE_AHEAD_QUARANTINED");
    }
    // No broker evidence for a restored prepared intent: never retry.
    {
        var (fh,fc)=Setup(xau);Handshake(fc);Call(fc,"BridgeOffline","OUTAGE");Basket(fh,fc,xau);
        var st=State(fc);Set(st,"PendingLabel","uncertain");Set(st,"PendingChildren",1);Set(st,"PendingStage",0);
        Call(fc,"RecoverAttempt");Check((bool)Get(st,"Quarantined")&&fh.Requests==0,"UNCERTAIN_INTENT_NO_RETRY");
    }
    // Online path still waits for the matching bridge ACK.
    {
        var (fh,fc)=Setup(xau);Handshake(fc);Set(fc,"_saveInFlight",false);Basket(fh,fc,xau);
        Call(fc,"ProcessQueue",fh.Server.TimeInUtc);Check(fh.Requests==0,"ONLINE_WAIT_ACK");
        for(int i=0;i<4&&fh.Requests==0;i++){var sent=(long)Get(fc,"_sentRevision");
        Call(fc,"ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=3+i,client_revision=sent}));}
        Check(fh.Requests==1,"ONLINE_MATCHING_ACK_SENDS_ONCE");orders+=fh.Requests;
    }
}
foreach(bool xau in new[]{true,false})foreach(int side in new[]{1,-1})foreach(double cash in new[]{100d,115d,1000d})
{
    var(h,c)=Setup(xau);Handshake(c);Call(c,"BridgeOffline","DAY_OUTAGE");
    h.Server.TimeInUtc=h.Server.TimeInUtc.AddDays(1);Basket(h,c,xau,cash,side);
    Call(c,"ProcessQueue",h.Server.TimeInUtc);
    Check(h.Requests==1&&h.Positions.Count==1,"BUY_SELL_CASH_OFFLINE_MATRIX");orders+=h.Requests;
    Check(!(bool)Get(State(c),"Quarantined"),"MATRIX_VALID_BUDGET_AND_PROTECTION");
    Check(h.Account.Margin<=h.Account.Equity*.5,"MATRIX_SHARED_MARGIN_LIMIT");
}
// Preserve XAU's exact macro/event freshness gate. Offline is not a feed bypass.
{
    var(h,c)=Setup(true);Handshake(c);var now=h.Server.TimeInUtc;
    var snap=new X.ExternalSnapshot{ProducedUtc=now,CoverageFromUtc=now.AddDays(-1),CoverageToUtc=now.AddDays(1),ForexFactoryOk=true,BlsOk=true,Dfii10=new(){Delta=-.01,AvailableUtc=now.AddHours(-1)}};
    Set(c,"_snapshot",snap);Call(c,"BridgeOffline","OUTAGE");
    Check(ReferenceEquals(snap,Get(c,"_snapshot")),"CACHED_FEED_SURVIVES_TRANSPORT_DROP");
    var signal=new X.Signal(now,1,0,2,1198);
    Check((bool)CallResult(c,"ExternalOk",signal,now),"FRESH_CACHED_FEED_ACCEPTED");
    Check(!(bool)CallResult(c,"ExternalOk",signal,now.AddSeconds(181)),"STALE_FEED_STILL_BLOCKS_XAU");
}
var latencyCases=new List<object>();
foreach(bool xau in new[]{true,false})foreach(int side in new[]{1,-1})
{
 var(h,c)=Setup(xau);Handshake(c);Call(c,"BridgeOffline","TIMING_FIXTURE");Basket(h,c,xau,115,side);
 var requested=h.Server.TimeInUtc;var symbol=h.Symbols.GetSymbol(xau?"XAUUSD":"EURUSD");double before=symbol.Bid;int marketEvents=0;
 h.BeforeMarketFill=()=>{for(int i=0;i<20;i++){h.Server.TimeInUtc=h.Server.TimeInUtc.AddMilliseconds(100);double delta=xau?side*.001:-side*.00000005;symbol.Bid+=delta;symbol.Ask+=delta;marketEvents++;}};
 Call(c,"ProcessQueue",requested);
 Check(marketEvents==20,"MARKET_NOT_PAUSED_DURING_BROKER_WAIT");
 Check((h.Server.TimeInUtc-requested).TotalSeconds==2,"BROKER_WAIT_ADVANCES_VIRTUAL_CLOCK");
 Check(symbol.Bid!=before,"EXECUTION_QUOTE_NOT_FROZEN");
 Check(h.Requests==1&&h.Positions.Count==1,"ONE_REQUEST_ONE_FILL_AFTER_WAIT");
 var fill=h.Positions[0];double expected=(side==1?symbol.Ask:symbol.Bid)+side*(xau?.05:.00001);
 Check(Math.Abs(fill.EntryPrice-expected)<1e-9,"FILL_USES_ARRIVAL_QUOTE_NOT_REQUEST_QUOTE");
 Check(!(bool)Get(State(c),"Quarantined"),"DELAYED_FILL_RECHECKS_BUDGET");
 latencyCases.Add(new{Symbol=xau?"XAUUSD":"EURUSD",Side=side,Requested=requested,Filled=h.Server.TimeInUtc,MarketEventsDuringWait=marketEvents,QuoteBefore=before,QuoteAfter=symbol.Bid,Fill=fill.EntryPrice});orders++;
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,SyntheticOrders=orders,LiveOrders=0,NativeHost=false,LatencyCases=latencyCases}));

(TestHost,EngineContext) Setup(bool xau){var h=new TestHost{EnableTrading=true,EnableXau=xau,EnableEur=!xau,ExpectedAccount="1237903",BridgeUrl="wss://example.invalid:25345",BridgeToken="fixture"};h.CreateEngines();EngineContext c=xau?h.Xau!:h.Eur!;var key=(xau?"RZXRC1":"RZEF245")+":"+h.Account.Number+":"+(xau?"XAUUSD":"EURUSD");Set(c,"_storageKey",X.FrozenCore.CheckpointStorageKey(key));Set(c,"_stateKey",key);
object state=xau?new X.Checkpoint{ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",ContractHash=X.FrozenContract.Xau.Hash,Symbol="XAUUSD",AccountNumber=h.Account.Number,PeakEquity=100}:new E.Checkpoint{Schema=3,ExecutionModel=E.EurBatchExecution.Model,ContractHash=E.F0245Policy.ConfigHash,Symbol="EURUSD",AccountNumber=h.Account.Number,PeakEquity=100};Set(c,"_state",state);h.Symbols.GetSymbol("XAUUSD").Bid=1200;h.Symbols.GetSymbol("XAUUSD").Ask=1200.11;h.Symbols.GetSymbol("EURUSD").Bid=1.1;h.Symbols.GetSymbol("EURUSD").Ask=1.10001;return(h,c);}
void Handshake(EngineContext c){Call(c,"ConnectBridge");Call(c,"ReceiveBridge","{\"type\":\"ready\",\"revision\":0,\"state\":null}");}
void Basket(TestHost h,EngineContext c,bool xau,double cash=100,int side=1){var now=h.Server.TimeInUtc;h.Account.Balance=h.Account.Equity=cash;var state=State(c);if(xau){var cfg=X.FrozenContract.Xau with{Slip=.10,CommissionPerSide=.06};var signal=new X.Signal(now,side,0,2,side==1?1198:1202.11);var b=X.FrozenCore.StartBasket(cfg,signal,(side==1?1200.11:1200)+side*.10,cash,cash,cash,0,6,1,cash,.16)!;if(b==null)throw new Exception("XAU_FIXTURE_NO_BASKET");Set(state,"Basket",b);Set(state,"XauPendingSignal",signal);}else{var cfg=E.F0245Policy.Contract;var b=E.EurBatchExecution.Start(cfg,new E.Signal(now,side,.001,.0003,1.0995),side==1?1.10001:1.1,cash,cash,cash,0,5.50005,1,cash)!;if(b==null)throw new Exception("EUR_FIXTURE_NO_BASKET");Set(state,"Basket",b);}Call(c,"Changed");Call(c,"Persist");}
JsonSerializerOptions Options(object c)=>(JsonSerializerOptions)T(c).GetField("Json",BindingFlags.NonPublic|BindingFlags.Static)!.GetValue(null)!;
object State(object c)=>Get(c,"_state");
Type T(object c)=>c is X.RizanRobot?typeof(X.RizanRobot):c is E.RizanRobot?typeof(E.RizanRobot):c.GetType();
object Get(object c,string n)=>T(c).GetField(n,BindingFlags.Instance|BindingFlags.NonPublic)?.GetValue(c)??T(c).GetProperty(n,BindingFlags.Instance|BindingFlags.Public)!.GetValue(c)!;
object Prop(object c,string n)=>T(c).GetProperty(n,BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(c)!;
void Set(object c,string n,object v){var f=T(c).GetField(n,BindingFlags.Instance|BindingFlags.NonPublic);if(f!=null)f.SetValue(c,v);else T(c).GetProperty(n)!.SetValue(c,v);}
object CallResult(object c,string n,params object[] a){try{return T(c).GetMethod(n,BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(c,a)!;}catch(TargetInvocationException e){throw e.InnerException!;}}
void Call(object c,string n,params object[] a)=>CallResult(c,n,a);
sealed class TestHost:RizanPortfolio{public TestHost(){EnableBtc=false;}public void Start()=>OnStart();}
