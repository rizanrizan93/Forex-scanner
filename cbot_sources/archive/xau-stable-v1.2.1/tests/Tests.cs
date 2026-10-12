using System;using System.Linq;using System.Collections.Generic;using System.Reflection;using System.Text.Json;using Rizan.Frozen;using cAlgo.API;
var tests=new List<object>();
foreach(int side in new[]{1,-1})foreach(double cash in new[]{100d,1000d})foreach(double move in new[]{0d,.1,.5}){
 var r=Setup(cash,side);var st=State(r);var old=st.Basket!;Run(r,"ProcessQueue",r.Server.TimeInUtc);int cap=st.PendingChildren;var saved=JsonSerializer.Serialize(st);
 if(r.Requests!=0||cap<1)throw new Exception("BEFORE_ACK");r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(2);r.Symbol.Bid+=side*move;r.Symbol.Ask+=side*move;r.Mark();Ack(r);
 var b=st.Basket!;if(r.Requests!=1||st.PendingLabel!=""||b.Accepted.Sum()<1||b.UsedRisk>b.RiskBudget+1e-7||b.RiskBudget>cash*.121+1e-7||Math.Abs(b.Entry-old.Entry-side*move)>1e-7||r.Positions.Any(p=>p.StopLoss!=b.Stop||p.TakeProfit!=b.Target))throw new Exception("BOUNDED_SEND_RECIPE");
 if(b.Accepted.Sum()>cap)throw new Exception("PERSISTED_MAXIMUM");Run(r,"ProcessQueue",r.Server.TimeInUtc);if(r.Requests!=1)throw new Exception("DUPLICATE_SEND");tests.Add(new{Case="SendAfterAck",Side=side,Cash=cash,Move=move,Quantity=b.Accepted.Sum()});
}
foreach(int side in new[]{1,-1}){
 var r=Setup(1000,side);Run(r,"ProcessQueue",r.Server.TimeInUtc);r.Symbol.Bid+=side*2;r.Symbol.Ask+=side*2;r.Mark();Ack(r);if(r.Requests!=0||State(r).PendingLabel!=""||State(r).Quarantined)throw new Exception("STALE_ZONE_REJECTION");tests.Add(new{Case="OutsideReferenceWindow",Side=side});
}
foreach(string kind in new[]{"Exposure","ClosedHistory","MissingComment","TamperedComment","PartialVolume"}){
 var r=Setup(1000,1);Run(r,"ProcessQueue",r.Server.TimeInUtc);string saved=JsonSerializer.Serialize(State(r));r.Symbol.Bid+=.1;r.Symbol.Ask+=.1;r.Mark();Ack(r);var p=r.Positions.Single();if(kind=="MissingComment")p.Comment="";if(kind=="TamperedComment")p.Comment=p.Comment.Replace("RZ1","BAD");if(kind=="PartialVolume")p.VolumeInUnits-=1;
 var x=Setup(1000,1);Set(x,"_state",JsonSerializer.Deserialize<Checkpoint>(saved)!);x.Account.Balance=r.Account.Balance;x.Symbol.Bid=r.Symbol.Bid;x.Symbol.Ask=r.Symbol.Ask;x.Server.TimeInUtc=r.Server.TimeInUtc;
 if(kind=="ClosedHistory"){r.ClosePosition(p);x.History.AddRange(r.History);x.Account.Balance=r.Account.Balance;}else x.Positions.Add(p);x.Mark();Run(x,"RecoverAttempt");bool valid=kind is "Exposure" or "ClosedHistory";if(State(x).Quarantined==valid||x.Requests!=0||(valid&&State(x).Basket!.Accepted.Sum()!=10))throw new Exception("RECOVERY_POLICY");Run(x,"RecoverAttempt");if(x.Requests!=0||(valid&&State(x).Basket!.Accepted.Sum()!=10))throw new Exception("RECOVERY_REPEATED");tests.Add(new{Case="Recovery",Kind=kind,Pass=true});
}
foreach(double direction in new[]{-1d,1d}){
 var r=Setup(1000,1);Run(r,"ProcessQueue",r.Server.TimeInUtc);Ack(r);r.Server.TimeInUtc=r.Server.TimeInUtc.AddMinutes(1);r.Symbol.Bid+=direction;r.Symbol.Ask+=direction;r.Mark();foreach(var p in r.Positions.ToArray())r.ClosePosition(p);Run(r,"ManagePositions",r.Server.TimeInUtc);var st=State(r);if(st.Basket!=null||(direction<0&&st.XauResumeUtc!=r.Server.TimeInUtc.AddDays(3))||(direction>0&&st.XauResumeUtc!=default))throw new Exception("LOSS_COOLDOWN");
 if(direction<0){Snapshot(r);Run(r,"PrepareBasket",new Signal(r.Server.TimeInUtc,1,0,2,1198),r.Server.TimeInUtc);if(st.Basket!=null)throw new Exception("COOLDOWN_ENTRY");r.Server.TimeInUtc=st.XauResumeUtc.AddSeconds(1);Snapshot(r);Run(r,"PrepareBasket",new Signal(r.Server.TimeInUtc,1,0,2,1198),r.Server.TimeInUtc);if(st.Basket==null)throw new Exception("COOLDOWN_RESUME");}
 tests.Add(new{Case="Cooldown",Direction=direction});
}
{
 var r=Setup(1000,1);Run(r,"ProcessQueue",r.Server.TimeInUtc);Ack(r);foreach(var p in r.Positions.ToArray())r.ClosePosition(p);r.History.Clear();Run(r,"ManagePositions",r.Server.TimeInUtc);if(State(r).Basket==null)throw new Exception("HISTORY_SETTLEMENT_WAIT");tests.Add(new{Case="SettlementWait"});
}
foreach(string fail in new[]{"Reject","Protection","CloseFailure","Partial"}){
 var r=Setup(1000,1);r.Reject=fail=="Reject";r.FailProtection=fail is "Protection" or "CloseFailure";r.FailClose=fail=="CloseFailure";r.ReturnVolumeFactor=fail=="Partial"?.9:1;Run(r,"ProcessQueue",r.Server.TimeInUtc);Ack(r);if(!State(r).Quarantined||State(r).Basket!.Accepted.Sum()!=0||r.Requests!=1)throw new Exception("PROTECTION_FAILURE");tests.Add(new{Case="BrokerFailure",Fail=fail});
}
foreach(string source in new[]{"XAU_ARCHIVE_PARITY_V2","XAU_BATCH_STAGE_FIXED_REF_WAL_V1"})foreach(bool active in new[]{false,true}){
 var r=Setup(1000,1);var st=State(r);st.ExecutionModel=source;if(!active){st.Basket=null;st.XauPendingSignal=null;}bool pass=true;try{Run(r,"ValidateState");}catch{pass=false;}if(pass==active)throw new Exception("FLAT_ONLY_MIGRATION");tests.Add(new{Case="Migration",Source=source,Active=active});
}
{
 var r=Setup(1000,1);Run(r,"ProcessQueue",r.Server.TimeInUtc);Ack(r);r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(1);Run(r,"QueueStage",1,r.Symbol.Ask+.10);Run(r,"ProcessQueue",r.Server.TimeInUtc);if(State(r).PendingLabel=="")throw new Exception("ADD_PENDING_SETUP");r.Symbol.Bid-=1;r.Symbol.Ask-=1;r.Mark();foreach(var p in r.Positions.ToArray())r.ClosePosition(p);Run(r,"ManagePositions",r.Server.TimeInUtc);if(State(r).Quarantined||State(r).PendingLabel!=""||State(r).Basket!=null||r.Requests!=1)throw new Exception("KNOWN_UNSUBMITTED_PENDING_CANCEL");tests.Add(new{Case="PositionClosedWhileStageWaitsAck"});
}
{
 var r=Setup(1000,1);Run(r,"ProcessQueue",r.Server.TimeInUtc);Run(r,"ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=999,client_revision=999}));if(r.Requests!=0||State(r).PendingLabel=="")throw new Exception("UNMATCHED_ACK_UNLOCKED");Ack(r);if(r.Requests!=1)throw new Exception("MATCHED_ACK_NOT_SENT");tests.Add(new{Case="UnmatchedAckIgnored"});
}
{
 var r=Setup(600,1);Set(r,"_state",new Checkpoint{ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",ContractHash=FrozenContract.Xau.Hash,Symbol="XAUUSD",AccountNumber=r.Account.Number,PeakEquity=600});Run(r,"PrepareBasket",new Signal(r.Server.TimeInUtc,1,0,4,1188.6),r.Server.TimeInUtc);Run(r,"ProcessQueue",r.Server.TimeInUtc);int cap=State(r).PendingChildren;if(cap!=6)throw new Exception("SHRINK_SETUP");r.Symbol.Bid+=.8;r.Symbol.Ask+=.8;r.Mark();Ack(r);if(r.Requests!=1||r.LastVolume!=5||State(r).Basket!.Accepted.Sum()!=5)throw new Exception("DURABLE_MAX_VOLUME_SHRINK");tests.Add(new{Case="MaximumIntentAllowsSafeSmallerBatch",Maximum=cap,Actual=r.LastVolume});
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,NativeHost=false,Cases=tests},new JsonSerializerOptions{WriteIndented=true}));
Host Setup(double cash,int side){var r=new Host();r.Account.Balance=r.Account.Equity=cash;r.Account.Number=2144480;r.ExpectedAccount="2144480";r.EnableTrading=true;r.Symbol.Bid=1200;r.Symbol.Ask=1200.11;r.Symbol.Leverage=100;r.BridgeUrl="wss://example.invalid:25345";Set(r,"_storageKey","fixture");Set(r,"_bridge",new WebSocketClient());Set(r,"_bridgeReady",true);Set(r,"_lastBridgeAck",r.Server.TimeInUtc);Set(r,"_state",new Checkpoint{ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",ContractHash=FrozenContract.Xau.Hash,Symbol="XAUUSD",AccountNumber=r.Account.Number,PeakEquity=cash});Snapshot(r);Run(r,"PrepareBasket",new Signal(r.Server.TimeInUtc,side,0,2,side==1?1198:1202),r.Server.TimeInUtc);if(State(r).Basket==null)throw new Exception("SETUP");return r;}
void Snapshot(Host r)=>Set(r,"_snapshot",new ExternalSnapshot{ProducedUtc=r.Server.TimeInUtc,CoverageFromUtc=r.Server.TimeInUtc.AddMinutes(-30),CoverageToUtc=r.Server.TimeInUtc.AddMinutes(495),ForexFactoryOk=true,BlsOk=true,Dfii10=new(){AvailableUtc=r.Server.TimeInUtc,Delta=0},Dgs10=new(){AvailableUtc=r.Server.TimeInUtc,Delta=0}});
void Ack(Host r){var st=State(r);Run(r,"ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=st.Revision,client_revision=(long)typeof(RizanRobot).GetField("_sentRevision",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(r)!}));}
Checkpoint State(Host r)=>(Checkpoint)typeof(RizanRobot).GetField("_state",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(r)!;
void Set(Host r,string n,object v)=>typeof(RizanRobot).GetField(n,BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(r,v);
void Run(Host r,string n,params object[] a){try{typeof(RizanRobot).GetMethod(n,BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(r,a);}catch(TargetInvocationException x){throw x.InnerException!;}}
class Host:RizanRobot{protected override FrozenContract Contract=>FrozenContract.Xau;protected override string Prefix=>"RZXA1";protected override string LoginSuffix=>"4480";}
