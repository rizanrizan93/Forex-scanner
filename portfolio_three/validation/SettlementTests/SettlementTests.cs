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
// Original production-path reproducer, now required to settle.
var(sh,sc)=RejectAdd();var sb=((X.Checkpoint)State(sc)).Basket!;
Check(sb.Accepted.Sum()==1,"REJECTED_FILL_NOT_ACCEPTED_RISK");
Check(((X.Checkpoint)State(sc)).RejectedFills.Count==1,"REJECTED_FILL_DURABLE_LEDGER");
sh.ClosePosition(sh.Positions[0]);Call(sc,"ManagePositions",sh.Server.TimeInUtc);
Check(((X.Checkpoint)State(sc)).Basket==null,"ORIGINAL_BUG_FIXED_BASKET_SETTLES");
Check(((X.Checkpoint)State(sc)).RejectedFills.Count==0,"LEDGER_CLEARED_ONLY_AFTER_SETTLEMENT");
Check(Math.Abs(sh.Account.Balance-(115+sh.History.Sum(x=>x.NetProfit)))<1e-8,"ALL_COSTS_AND_LOSSES_IN_BALANCE");
Check(sc.RecoveryReady,"HEALTHY_AFTER_REJECTION_SETTLEMENT");
// Restart from the WAL at the exact rejection-before-close boundary.
foreach(var boundary in new[]{"before-close","after-close","after-commit"})
{
 var(h,c)=RejectAdd();var st=(X.Checkpoint)State(c);var rejected=h.History[0];
 if(boundary!="after-commit"){
   st.PendingLabel=rejected.Label;st.PendingChildren=(int)rejected.VolumeInUnits;st.PendingStage=1;
   st.Basket!.QueueStage=1;st.Basket.QueueRemaining=st.PendingChildren;
   if(boundary=="before-close"){
     h.History.Remove(rejected);
     h.Positions.Add(new Position{Id=(int)rejected.PositionId,SymbolName="XAUUSD",Label=rejected.Label,VolumeInUnits=rejected.VolumeInUnits,EntryPrice=rejected.EntryPrice,TradeType=rejected.TradeType,Comment=rejected.Comment,StopLoss=st.Basket.Stop,TakeProfit=st.Basket.Target});h.Mark();
   }
 }
 Call(c,"Changed");Call(c,"Persist");var(rh,rc)=Restart(h);
 Check(rc.RecoveryReady&&rh.Requests==0&&rh.Positions.Count==1,"RECOVER_REJECTION_NO_DUPLICATE_"+boundary);
 Check(((X.Checkpoint)State(rc)).Basket!.Accepted.Sum()==1,"RECOVERY_NEVER_ACCEPTS_REJECTED_"+boundary);
 rh.ClosePosition(rh.Positions[0]);Call(rc,"ManagePositions",rh.Server.TimeInUtc);
 Check(((X.Checkpoint)State(rc)).Basket==null,"RESTART_SETTLES_"+boundary);
}
// Rejected-only first fill must also wait for history and apply loss cooldown.
{
 var(h,c)=Setup(true);Handshake(c);Call(c,"BridgeOffline","TEST");Basket(h,c,true,115);
 h.BeforeMarketFill=()=>{var sym=h.Symbols.GetSymbol("XAUUSD");sym.Bid+=5;sym.Ask+=5;};
 Call(c,"ProcessQueue",h.Server.TimeInUtc);
 var st=(X.Checkpoint)State(c);Check(st.RejectedFills.Count==1&&st.Basket!.Accepted.Sum()==0,"FIRST_FILL_REJECTED_ONLY");
 var hist=h.History.ToArray();h.History.Clear();Call(c,"ManagePositions",h.Server.TimeInUtc);
 Check(st.Basket!=null,"REJECTED_ONLY_WAITS_FOR_HISTORY");h.History.AddRange(hist);
 Call(c,"ManagePositions",h.Server.TimeInUtc);Check(st.Basket==null,"REJECTED_ONLY_SETTLES");
 Check(st.XauResumeUtc==h.Server.TimeInUtc.AddDays(3),"REJECTED_ONLY_LOSS_COOLDOWN");
}
foreach(var corrupt in new[]{"duplicate-history","unknown-extra-history","wrong-id","missing-history","old-unclassified","nonfinite-pnl"})
{
 var(h,c)=RejectAdd();var st=(X.Checkpoint)State(c);h.ClosePosition(h.Positions[0]);
 if(corrupt=="duplicate-history")h.History.Add(h.History[0]);
 if(corrupt=="unknown-extra-history"){
  var t=JsonSerializer.Deserialize<HistoricalTrade>(JsonSerializer.Serialize(h.History[1]))!;t.PositionId=999;h.History.Add(t);
 }
 if(corrupt=="wrong-id")h.History[0].PositionId=999;
 if(corrupt=="missing-history")h.History.RemoveAt(0);
 if(corrupt=="old-unclassified")st.RejectedFills.Clear();
 if(corrupt=="nonfinite-pnl")h.History[0].NetProfit=double.NaN;
 Call(c,"ManagePositions",h.Server.TimeInUtc);
 Check(st.Basket!=null,"CORRUPTION_NEVER_CLEARS_BASKET_"+corrupt);
 if(corrupt!="missing-history")Check(st.Quarantined&&!c.RecoveryReady,"OVERCOUNT_OR_IDENTITY_BLOCKS_"+corrupt);
 else {Check(!st.Quarantined,"DELAYED_HISTORY_CAN_RETRY");}
}
// Failure to close never makes rejected exposure accepted or enables entry.
{
 var(h,c)=RejectAdd(true);var st=(X.Checkpoint)State(c);
 Check(st.Quarantined&&!c.RecoveryReady&&h.Positions.Count==2,"CLOSE_FAILURE_BLOCKS");
 Check(st.Basket!.Accepted.Sum()==1&&st.RejectedFills.Count==1&&st.PendingLabel!="","CLOSE_FAILURE_PRESERVES_WAL");
}
// A failure to save rejection classification leaves protected exposure quarantined.
{
 var(h,c)=Setup(true);Handshake(c);Call(c,"BridgeOffline","TEST");Basket(h,c,true,115);Call(c,"ProcessQueue",h.Server.TimeInUtc);
 var sym=h.Symbols.GetSymbol("XAUUSD");h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(1);sym.Bid-=2;sym.Ask-=2;h.Mark();Call(c,"QueueStage",1,sym.Ask+.10);
 h.BeforeMarketFill=()=>{sym.Bid+=4;sym.Ask+=4;h.LocalStorage.FailWrite=true;};Call(c,"ProcessQueue",h.Server.TimeInUtc);
 Check(!c.RecoveryReady&&((X.Checkpoint)State(c)).Quarantined,"REJECTION_WAL_FAILURE_BLOCKS");
 Check(h.Positions.Count==2&&h.Positions.All(p=>p.StopLoss!=null&&p.TakeProfit!=null),"WAL_FAILURE_PRESERVES_PROTECTED_EXPOSURE");
}
// Loss test includes rejected PnL even when accepted child itself is profitable.
{
 var(h,c)=RejectAdd();h.ClosePosition(h.Positions[0]);h.History[0].NetProfit=-10;h.History[1].NetProfit=1;
 Call(c,"ManagePositions",h.Server.TimeInUtc);Check(((X.Checkpoint)State(c)).XauResumeUtc==h.Server.TimeInUtc.AddDays(3),"COOLDOWN_INCLUDES_REJECTED_LOSS");
}
// Corrupt checkpoint rejection metadata is refused on load; old flat state migrates.
foreach(var corruption in new[]{"duplicate-id","wrong-label","nan-volume","no-basket","old-flat"})
{
 var(h,c)=RejectAdd();var st=(X.Checkpoint)State(c);
 if(corruption=="duplicate-id")st.RejectedFills.Add(st.RejectedFills[0]);
 if(corruption=="wrong-label")st.RejectedFills[0].Label="foreign";
 if(corruption=="nan-volume")st.RejectedFills[0].Volume=double.NaN;
 if(corruption=="no-basket")st.Basket=null;
 if(corruption=="old-flat"){st.RejectedFills.Clear();st.Basket=null;st.XauPendingSignal=null;h.Positions.Clear();}
 bool failed=false;try{Call(c,"ValidateState");}catch{failed=true;}
 Check(failed==(corruption!="old-flat"),"CHECKPOINT_VALIDATION_"+corruption);
}
// Buy/sell and small/large batch regression, including repeated rejected adds.
foreach(int direction in new[]{1,-1})foreach(double cash in new[]{115d,1000d}){
 var(h,c)=Setup(true);Handshake(c);Call(c,"BridgeOffline","MATRIX");Basket(h,c,true,cash,direction);Call(c,"ProcessQueue",h.Server.TimeInUtc);
 var st=(X.Checkpoint)State(c);int accepted=st.Basket!.Accepted.Sum();double risk=st.Basket.UsedRisk;
 for(int attempt=0;attempt<2;attempt++){
  var sym=h.Symbols.GetSymbol("XAUUSD");h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(3);
  sym.Bid=1200-direction*2;sym.Ask=sym.Bid+.11;h.Mark();Call(c,"QueueStage",1,(direction==1?sym.Ask:sym.Bid)+direction*.10);
  Check(st.Basket.QueueRemaining>0,"MATRIX_REJECT_ADD_PLANNED");
  h.BeforeMarketFill=()=>{sym.Bid+=direction*4;sym.Ask+=direction*4;};Call(c,"ProcessQueue",h.Server.TimeInUtc);h.BeforeMarketFill=null;
  Check(st.RejectedFills.Count==attempt+1,"MULTIPLE_REJECTED_BATCHES_TRACKED");
  Check(st.Basket.Accepted.Sum()==accepted&&st.Basket.UsedRisk==risk,"REJECTED_BATCH_NEVER_SPENDS_ACCEPTED_RISK");
 }
 foreach(var pos in h.Positions.ToArray())h.ClosePosition(pos);
 Check(Math.Abs(h.Account.Balance-(cash+h.History.Sum(t=>t.NetProfit)))<1e-8,"MATRIX_PNL_RECONCILES");
 Call(c,"ManagePositions",h.Server.TimeInUtc);
 Check(st.Basket==null&&!st.Quarantined,"MATRIX_MULTIPLE_REJECTION_SETTLES");
}
// Broker partial closes may produce several history rows for one position.
{
 var(h,c)=RejectAdd();h.ClosePosition(h.Positions[0]);var row=h.History[0];
 var part=JsonSerializer.Deserialize<HistoricalTrade>(JsonSerializer.Serialize(row))!;
 row.VolumeInUnits/=2;part.VolumeInUnits/=2;row.NetProfit/=2;part.NetProfit/=2;h.History.Add(part);
 // Use a larger virtual child batch so both partial volumes stay on the grid.
 row.VolumeInUnits=part.VolumeInUnits=1;((X.Checkpoint)State(c)).RejectedFills[0].Volume=2;
 // Labels describe the requested full volume.
 string label=row.Label[..row.Label.LastIndexOf('|')]+"|2";row.Label=part.Label=label;((X.Checkpoint)State(c)).RejectedFills[0].Label=label;
 Call(c,"ManagePositions",h.Server.TimeInUtc);
 Check(((X.Checkpoint)State(c)).Basket==null,"PARTIAL_HISTORY_SUMS_BY_POSITION");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,LiveOrders=0,NativeHost=false,OriginalBugFixed=true}));

(TestHost,EngineContext) RejectAdd(bool failClose=false){
 var(h,c)=Setup(true);Handshake(c);Call(c,"BridgeOffline","REPRO");Basket(h,c,true,115);Call(c,"ProcessQueue",h.Server.TimeInUtc);
 var sym=h.Symbols.GetSymbol("XAUUSD");h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(1);sym.Bid-=2;sym.Ask-=2;h.Mark();Call(c,"QueueStage",1,sym.Ask+.10);
 h.BeforeMarketFill=()=>{h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(2);sym.Bid+=4;sym.Ask+=4;h.FailClose=failClose;};
 Call(c,"ProcessQueue",h.Server.TimeInUtc);h.BeforeMarketFill=null;return(h,c);
}
(TestHost,EngineContext) Restart(TestHost old){
 var(h,c)=Setup(true);h.Server.TimeInUtc=old.Server.TimeInUtc;
 foreach(var kv in old.LocalStorage.Values)h.LocalStorage.Values[kv.Key]=kv.Value;
 h.Positions.AddRange(old.Positions);h.History.AddRange(old.History);h.Account.Balance=old.Account.Balance;
 var a=h.Symbols.GetSymbol("XAUUSD");var b=old.Symbols.GetSymbol("XAUUSD");a.Bid=b.Bid;a.Ask=b.Ask;h.Mark();h.Start();c=h.Xau!;Handshake(c);return(h,c);
}
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
