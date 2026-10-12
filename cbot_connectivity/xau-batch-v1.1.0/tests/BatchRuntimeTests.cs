using System;using System.Linq;using System.Reflection;using System.Text.Json;using System.Collections.Generic;using Rizan.Frozen;using cAlgo.API;
var output=new List<object>();
foreach(int side in new[]{1,-1})foreach(double cash in new[]{100d,1000d,10000d})foreach(bool bridge in new[]{false,true}){
 var r=Setup(cash,side);var state=State(r);if(bridge){r.BridgeUrl="wss://example.invalid:25345";Set(r,"_bridge",new WebSocketClient());Set(r,"_bridgeReady",true);Set(r,"_lastBridgeAck",r.Server.TimeInUtc);}
 Run(r,"ProcessQueue",r.Server.TimeInUtc);
 if(bridge){if(r.Requests!=0||state.PendingChildren!=(int)(cash/100))throw new Exception("SEND_BEFORE_ACK_OR_COUNT");Run(r,"ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=1,client_revision=state.Revision}));}
 int q=(int)(cash/100);if(r.Requests!=1||Math.Abs(r.LastVolume-q)>1e-8||state.Basket!.Accepted[0]!=q||r.Positions.Count!=1||state.Quarantined||state.PendingLabel!=""||state.PendingChildren!=0)throw new Exception("BATCH_ACCEPTANCE");
 var p=r.Positions[0];if(p.StopLoss!=state.Basket.Stop||p.TakeProfit!=state.Basket.Target)throw new Exception("ABSOLUTE_PROTECTION");Run(r,"ProcessQueue",r.Server.TimeInUtc);if(r.Requests!=1)throw new Exception("DUPLICATE_BATCH");Run(r,"ReconcileExposure");if(state.Quarantined)throw new Exception("EXPOSURE_RECONCILE");
 output.Add(new{Case="Normal",Side=side,Cash=cash,Bridge=bridge,VirtualChildren=q,BrokerRequests=r.Requests});
}
foreach(string error in new[]{"Reject","Protection","CloseFailure","ExtraFee","ExtraSlip","PartialFill","PriceBeforeAck"}){
 var r=Setup(1000,1);var st=State(r);r.Reject=error=="Reject";r.FailProtection=error is "Protection" or "CloseFailure";r.FailClose=error=="CloseFailure";r.ReturnVolumeFactor=error=="PartialFill"?.9:1;r.ExtraFee=error=="ExtraFee"?1:0;r.ExtraSlip=error=="ExtraSlip"?.10:.05;
 if(error=="PriceBeforeAck"){
  r.BridgeUrl="wss://example.invalid:25345";Set(r,"_bridge",new WebSocketClient());Set(r,"_bridgeReady",true);Set(r,"_lastBridgeAck",r.Server.TimeInUtc);Run(r,"ProcessQueue",r.Server.TimeInUtc);r.Symbol.Ask+=.10;r.Symbol.Bid+=.10;Run(r,"ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=1,client_revision=st.Revision}));if(r.Requests!=0||st.PendingLabel!="")throw new Exception("CHANGED_BUDGET_AFTER_ACK");
 }else{
  Run(r,"ProcessQueue",r.Server.TimeInUtc);if(r.Requests!=1||st.Basket!.Accepted.Sum()!=0)throw new Exception("INVALID_FILL_ACCEPTED");if(error is "Reject" or "Protection" or "CloseFailure" or "PartialFill"){if(!st.Quarantined)throw new Exception("EXPECTED_QUARANTINE");}else{if(r.Closes!=1||r.Positions.Count!=0||st.PendingLabel!="")throw new Exception("BAD_FILL_NOT_CLOSED");}
 }
 output.Add(new{Case=error,Requests=r.Requests,Closes=r.Closes,Quarantined=st.Quarantined});
}
// Recover one persisted batch exactly once from broker exposure, then disallow retries of uncertain intent.
foreach(string mode in new[]{"Exposure","ClosedHistory","Missing","Duplicate","WrongVolume"}){
 var r=Setup(1000,1);var st=State(r);var b=st.Basket!;b.Sequence=1;st.PendingStage=0;st.PendingChildren=10;st.PendingFirstFill=true;st.PendingLabel=$"RZXA1|{b.AtUtc.Ticks}|0|1|10";
 if(mode=="ClosedHistory")r.History.Add(new(){SymbolName="XAUUSD",Label=st.PendingLabel,PositionId=1,EntryPrice=1200.16,VolumeInUnits=10,TradeType=TradeType.Buy,Commissions=-.30});
 if(mode is "Exposure" or "Duplicate" or "WrongVolume")r.Positions.Add(new(){SymbolName="XAUUSD",Label=st.PendingLabel,Id=1,EntryPrice=1200.16,VolumeInUnits=mode=="WrongVolume"?9:10,TradeType=TradeType.Buy,StopLoss=b.Stop,TakeProfit=b.Target,Commissions=-.30});
 if(mode=="Duplicate")r.Positions.Add(new(){SymbolName="XAUUSD",Label=st.PendingLabel,Id=2,EntryPrice=1200.16,VolumeInUnits=10,TradeType=TradeType.Buy,StopLoss=b.Stop,TakeProfit=b.Target,Commissions=-.30});
 Run(r,"RecoverAttempt");bool valid=mode is "Exposure" or "ClosedHistory";if(st.Quarantined==valid||b.Accepted[0]!=(valid?10:0)||r.Requests!=0)throw new Exception("RECOVERY_ACCOUNTING");Run(r,"RecoverAttempt");if(b.Accepted[0]!=(valid?10:0)||r.Requests!=0)throw new Exception("RECOVERY_DOUBLE_COUNT");output.Add(new{Case="Recover"+mode,Accepted=b.Accepted[0],Quarantined=st.Quarantined});
}
foreach(string model in new[]{"","XAU_ARCHIVE_PARITY_V2","XAU_BATCH_STAGE_FIXED_REF_WAL_V1"})foreach(bool active in new[]{false,true}){
 var r=Setup(1000,1);var st=State(r);st.ExecutionModel=model;if(!active)st.Basket=null;bool pass=true;try{Run(r,"ValidateState");}catch{pass=false;}if(pass!=(model=="XAU_BATCH_STAGE_FIXED_REF_WAL_V1"||!active))throw new Exception("CHECKPOINT_MIGRATION");output.Add(new{Case="Migration",Model=model,Active=active,Accepted=pass});
}
// Additional stage is a separate group, sharing initial absolute SL/TP.
{
 var r=Setup(1000,1);var st=State(r);Run(r,"ProcessQueue",r.Server.TimeInUtc);var b=st.Basket!;r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(1);r.Symbol.Bid-=2;r.Symbol.Ask-=2;r.Account.Equity=1000-20;r.Account.Margin=120;Run(r,"QueueStage",1,r.Symbol.Ask+.05);int wanted=b.QueueRemaining;if(wanted<1)throw new Exception("ADD_EXPECTED");Run(r,"ProcessQueue",r.Server.TimeInUtc);if(r.Requests!=2||r.Positions.Count!=2||b.Accepted[1]!=wanted||r.Positions.Any(p=>p.StopLoss!=b.Stop||p.TakeProfit!=b.Target))throw new Exception("ADD_BATCH");output.Add(new{Case="StageAdd",InitialChildren=b.Accepted[0],AddedChildren=b.Accepted[1],BrokerRequests=r.Requests});
}
{
 var r=Setup(1000,1);var st=State(r);r.Symbol.VolumeInUnitsMax=4;
 Run(r,"ProcessQueue",r.Server.TimeInUtc);Run(r,"ProcessQueue",r.Server.TimeInUtc);if(r.Requests!=1)throw new Exception("RATE_LIMIT");
 for(int i=0;i<2;i++){r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(1);Run(r,"ProcessQueue",r.Server.TimeInUtc);}
 if(r.Requests!=3||st.Basket!.Accepted[0]!=10||r.Positions.Select(p=>p.VolumeInUnits).SequenceEqual(new[]{4d,4d,2d})==false)throw new Exception("BROKER_VOLUME_CHUNKS");
 Run(r,"ReconcileExposure");if(st.Quarantined)throw new Exception("CHUNK_RECONCILE");output.Add(new{Case="BrokerVolumeLimit",Requests=r.Requests,Children=st.Basket.Accepted[0]});
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,NativeHost=false,Cases=output},new JsonSerializerOptions{WriteIndented=true}));
TestRobot Setup(double cash,int side){var r=new TestRobot();r.SymbolName="XAUUSD";r.Symbol.Bid=1200;r.Symbol.Ask=1200.11;r.Symbol.Leverage=100;r.Symbol.VolumeInUnitsMin=1;r.Symbol.VolumeInUnitsStep=1;r.Symbol.VolumeInUnitsMax=2000;r.Account.Balance=r.Account.Equity=cash;r.EnableTrading=true;r.ChildrenPerSecond=1;r.ExpectedAccount=r.Account.Number.ToString();r.ExtraSlip=.05;double entry=(side==1?r.Symbol.Ask:r.Symbol.Bid)+side*.05;var b=FrozenCore.StartBasket(FrozenContract.Xau,new(r.Server.TimeInUtc,side,0,2,side==1?1198:1202.11),entry,cash,cash,cash,0,entry/100,1,cash,.16)!;Set(r,"_state",new Checkpoint{ExecutionModel="XAU_BATCH_STAGE_FIXED_REF_WAL_V1",Basket=b,ContractHash=FrozenContract.Xau.Hash,Symbol="XAUUSD",AccountNumber=r.Account.Number,PeakEquity=cash});Set(r,"_storageKey","Test");return r;}
Checkpoint State(object r)=>(Checkpoint)typeof(RizanRobot).GetField("_state",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(r)!;
void Set(object r,string n,object v)=>typeof(RizanRobot).GetField(n,BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(r,v);
void Run(object r,string n,params object[] a){try{typeof(RizanRobot).GetMethod(n,BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(r,a);}catch(TargetInvocationException e){throw e.InnerException!;}}
sealed class TestRobot:RizanRobot{protected override FrozenContract Contract=>FrozenContract.Xau;protected override string Prefix=>"RZXA1";protected override string LoginSuffix=>"7903";}
