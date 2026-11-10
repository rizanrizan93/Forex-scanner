using System;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Frozen;
int assertions=0;
foreach(int side in new[]{1,-1})foreach(double equity in new[]{100d,1000d,100000d}){
 var r=Ready(equity,side);var b=State(r).Basket!;int wanted=b.QueueRemaining;
 Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Requests==1,"ONE_BATCH_REQUEST");Check(b.Accepted.Sum()==EurBatchExecution.ChildrenForVolume(r.LastVolume,1000),"VOLUME_COUNT_PARITY");Check(b.Accepted.Sum()<=wanted,"NO_EXCESS_CHILDREN");Check(Math.Abs(b.Entry-r.Positions[0].EntryPrice)<1e-12,"ACTUAL_FIRST_ANCHOR");Check(Math.Abs(r.Positions[0].StopLoss!.Value-b.Stop)<1e-12,"SERVER_SL");Check(Math.Abs(r.Positions[0].TakeProfit!.Value-b.Target)<1e-12,"SERVER_TP");
 // Force another queue to verify rate limit covers all callback entry points.
 b.QueueStage=1;b.QueueRemaining=1;Set(r,"_persistedRevision",State(r).Revision);Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Requests==1,"ONE_ORDER_PER_SECOND");
}
{
 var r=Ready(100000,1);r.Symbol.VolumeInUnitsMax=10000;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.LastVolume<=10000,"BROKER_CAP");
 var s=State(r);Check(s.Basket!.Accepted.Sum()==10,"BROKER_CAP_CHILD_COUNT");
}
{
 var r=Ready(100,1);r.BridgeUrl="wss://example.test:25345";Set(r,"_persistedRevision",-1L);Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Requests==0,"INTENT_DURABILITY_REQUIRED");
}
{
 var r=Ready(100,1);r.Reject=true;Run(r,"ProcessQueue",r.Server.TimeInUtc);Run(r,"ProcessQueue",r.Server.TimeInUtc.AddSeconds(1));Check(r.Requests==1&&State(r).Quarantined,"UNCERTAIN_NO_RETRY");
}
{
 var r=Ready(100,1);r.FailProtection=true;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Closes==1&&State(r).Quarantined,"PROTECTION_FAIL_CLOSE");
}
{
 var r=Ready(100,1);r.FailProtection=true;r.FailClose=true;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Positions.Count==1&&State(r).Quarantined,"CLOSE_FAIL_QUARANTINE");
}
{
 var r=Ready(100,1);r.ExtraFee=95;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Closes==1&&State(r).Basket!.Accepted.Sum()==0,"ACTUAL_EQUITY_RECHECK");
}
foreach(bool closed in new[]{false,true}){
 var r=Ready(1000,1);var s=State(r);var b=s.Basket!;int q=7;string label="RZEU4B|"+b.AtUtc.Ticks+"|0|1|7";
 s.PendingLabel=label;s.PendingChildren=q;s.PendingStage=0;s.PendingFirstFill=true;
 double entry=1.10004;
 if(closed)r.History.Add(new(){Label=label,PositionId=77,EntryPrice=entry,VolumeInUnits=7000,TradeType=TradeType.Buy});else r.Positions.Add(new(){Id=77,Label=label,EntryPrice=entry,VolumeInUnits=7000,TradeType=TradeType.Buy,StopLoss=1.09,TakeProfit=1.12});
 Run(r,"RecoverAttempt");Check(b.Accepted[0]==q&&s.PendingLabel=="","RECOVER_COUNTS_VOLUME");Check(Math.Abs(b.Entry-entry)<1e-12,"RECOVER_ACTUAL_ANCHOR");Run(r,"RecoverAttempt");Check(b.Accepted[0]==q,"RECOVERY_IDEMPOTENT");
}
{
 var r=Ready(1000,1);var s=State(r);s.PendingLabel="unresolved";s.PendingChildren=2;s.PendingStage=0;s.PendingFirstFill=true;Run(r,"RecoverAttempt");Check(s.Quarantined&&r.Requests==0,"RECOVERY_NO_BLIND_RETRY");
}
{
 var r=Ready(1000,1);var s=State(r);s.PendingLabel="partial";s.PendingChildren=7;s.PendingStage=0;s.PendingFirstFill=true;r.Positions.Add(new(){Id=77,Label="partial",EntryPrice=1.10003,VolumeInUnits=2000,TradeType=TradeType.Buy});Run(r,"RecoverAttempt");Check(s.Quarantined&&s.Basket!.Accepted.Sum()==0,"PARTIAL_FILL_QUARANTINE");
}
{
 var r=Ready(1000,1);r.Symbol.Ask+=.001;r.Symbol.Bid+=.001;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Requests==0&&State(r).Basket!.QueueStage==-1,"STALE_ZONE_CANCEL");
}
{
 var r=Ready(1000,1);r.Account.Equity=0;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Requests==0,"NO_ORDER_WITH_ZERO_EQUITY");
}
{
 var r=Ready(1000,1);r.Positions.Add(new(){Label="RZEU3|legacy",VolumeInUnits=1000});Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Requests==0,"LEGACY_EXPOSURE_BLOCK");
}
{
 var r=Ready(1000,1);r.ExtraFee=2;Run(r,"ProcessQueue",r.Server.TimeInUtc);Check(r.Closes==1&&State(r).Basket!.Accepted.Sum()==0,"HIGH_COMMISSION_STAGE_RISK_BLOCK");
}
{
 var r=Ready(1000,1);Run(r,"ProcessQueue",r.Server.TimeInUtc);Run(r,"ReconcileExposure");Check(!State(r).Quarantined,"GROUPED_EXPOSURE_RECONCILES");r.Positions[0].Label="RZEU4B|"+State(r).Basket!.AtUtc.Ticks+"|2|1|"+State(r).Basket!.Accepted[0];Run(r,"ReconcileExposure");Check(State(r).Quarantined,"WRONG_STAGE_EXPOSURE_BLOCK");
}
{
 var r=Ready(1000,1);var s=State(r);s.PendingLabel="RZEU4B|"+s.Basket!.AtUtc.Ticks+"|0|1|7";s.PendingChildren=7;s.PendingStage=0;s.PendingFirstFill=true;r.Positions.Add(new(){Id=77,Label=s.PendingLabel,EntryPrice=1.10003,VolumeInUnits=4000,TradeType=TradeType.Buy});r.History.Add(new(){PositionId=77,Label=s.PendingLabel,EntryPrice=1.10003,VolumeInUnits=3000,TradeType=TradeType.Buy});Run(r,"RecoverAttempt");Check(s.Basket.Accepted[0]==7&&!s.Quarantined,"RECOVERY_PARTIAL_CLOSE_TOTAL_VOLUME");
}
{
 var r=Ready(1000,1);Run(r,"ValidateState");Check(true,"VALID_BATCH_CHECKPOINT");State(r).Schema=1;bool rejected=false;try{Run(r,"ValidateState");}catch(Exception){rejected=true;}Check(rejected,"LEGACY_CHECKPOINT_REJECTED");
}
{
 var r=Ready(1000,1);var s=State(r);s.Basket!.Sequence=1;s.PendingStage=0;s.PendingChildren=7;s.PendingFirstFill=true;s.PendingLabel="RZEU4B|"+s.Basket.AtUtc.Ticks+"|0|1|7";var json=JsonSerializer.Serialize(s);var recovered=JsonSerializer.Deserialize<Checkpoint>(json)!;Set(r,"_state",recovered);Run(r,"ValidateState");Check(recovered.PendingChildren==7&&recovered.PendingFirstFill,"PENDING_VOLUME_ROUNDTRIP");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Assertions=assertions,Scope="Runtime source linked to simulated broker API; not native cTrader"}));
TestRobot Ready(double equity,int side){var r=new TestRobot();r.EnableTrading=true;r.ExpectedAccount=r.Account.Number.ToString();r.Account.Balance=equity;r.Account.Equity=equity;var c=FrozenContract.Eur;double quote=side==1?r.Symbol.Ask:r.Symbol.Bid;var b=EurBatchExecution.Start(c,new(r.Server.TimeInUtc,side,.002),quote,equity,equity,equity,0,r.Symbol.GetEstimatedMargin(side==1?TradeType.Buy:TradeType.Sell,1000),1,equity)!;var s=new Checkpoint{Basket=b,ExecutionModel=EurBatchExecution.Model,Revision=0,AccountNumber=r.Account.Number,Symbol="EURUSD",ContractHash=c.Hash};Set(r,"_state",s);Set(r,"_persistedRevision",0L);Set(r,"_storageKey","Test");return r;}
Checkpoint State(TestRobot r)=>(Checkpoint)Get(r,"_state");
object Get(object r,string n)=>typeof(RizanRobot).GetField(n,BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(r)!;
void Set(object r,string n,object v)=>typeof(RizanRobot).GetField(n,BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(r,v);
void Run(object r,string n,params object[] args){try{typeof(RizanRobot).GetMethod(n,BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(r,args);}catch(TargetInvocationException e){throw e.InnerException!;}}
void Check(bool v,string name){assertions++;if(!v)throw new Exception(name);}
class TestRobot:RizanRobot {protected override FrozenContract Contract=>FrozenContract.Eur;protected override string Prefix=>"RZEU4B";protected override string LoginSuffix=>"7903";}
