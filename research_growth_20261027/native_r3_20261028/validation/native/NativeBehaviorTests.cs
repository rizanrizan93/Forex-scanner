using System;using System.Linq;using System.Collections.Generic;using System.Reflection;using System.Text.Json;using System.IO;using cAlgo.API;using Rizan.Portfolio;
int checks=0;void Check(bool x,string why){checks++;if(!x)throw new Exception(why);}
DateTime start=DateTimeOffset.FromUnixTimeSeconds(1792108800).UtcDateTime;
string feedPacket=File.ReadAllText(args[0]);
object State(BtcEngine b)=>typeof(BtcEngine).GetField("state",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(b)!;
string Saved(TestHost h)=>h.LocalStorage.Values[FrozenR3.BtcStorageKey(h.Account.Number)];
void CheckKeys(){foreach(long account in new[]{1L,1237903L,long.MaxValue})foreach(string role in new[]{"PORT","BTC"}){string k=FrozenR3.NativeStorageKey(role,account);Check(k.Length<=50&&k.Trim()==k&&k.All(c=>char.IsLetterOrDigit(c)||c==' '),"NATIVE_STORAGE_KEY_VALID");}Check(FrozenR3.NativeStorageKey("PORT",1)!=FrozenR3.NativeStorageKey("BTC",1),"ROLE_STORAGE_ISOLATION");Check(FrozenR3.NativeStorageKey("BTC",1)!=FrozenR3.NativeStorageKey("BTC",2),"ACCOUNT_STORAGE_ISOLATION");Check(FrozenR3.XauPrefix!="RZXRC1"&&FrozenR3.BtcPrefix!="RZBTC8500283","FROZEN_NATIVE_NAMESPACE_NOT_OLD_LIVE");Check(FrozenR3.Matches()&&RP.C.BtcBatchOrders==32&&RP.C.EurInitial==1&&RP.C.EurWindow==60&&RP.C.XauRisk==1.5,"R3_NATIVE_PROFILE_LOCKED");}
TestHost Make(double balance=100000000){var h=new TestHost{EnableTrading=true,EnableXau=false,EnableEur=false,EnableBtc=true,BtcBridgeUrl="wss://test.invalid:25345",BtcBridgeToken=new string('x',32)};h.ExpectedAccount=h.Account.Number.ToString();h.Account.Balance=h.Account.Equity=balance;h.Server.TimeInUtc=start;h.Symbols.GetSymbol("BTCUSD").Bid=10000;h.Symbols.GetSymbol("BTCUSD").Ask=10005;h.CreateEngines();h.BeforeMarketFill=()=>{h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(2);h.Mark();};return h;}
Wire Connect(TestHost h,string? remote=null){h.Btc!.OnStart();var w=new Wire(h);w.Ready(remote);w.Feed(feedPacket);w.AckAll();return w;}
void Step(TestHost h,Wire w,bool ack=true){h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(1);h.Btc!.OnTimer();if(ack)w.AckAll();}
void First(TestHost h,Wire w,int side=1){h.Btc!.Enter(new(start,side,200,10000),h.Server.TimeInUtc);Check(h.Requests==0,"SIGNAL_INTENT_NO_ORDER_BEFORE_ACK");w.AckAll();Step(h,w);Check(h.Requests==0,"SIZED_INTENT_STILL_NO_ORDER_BEFORE_ACK");Step(h,w);Check(h.Requests==1,"FIRST_NATIVE_ORDER_AFTER_DURABLE_INTENT");}
TestHost Clone(TestHost old,string snapshot){var h=Make(old.Account.Balance);h.Server.TimeInUtc=old.Server.TimeInUtc;h.Positions.AddRange(old.Positions);h.History.AddRange(old.History);h.Requests=old.Requests;h.Mark();h.LocalStorage.Values[FrozenR3.BtcStorageKey(h.Account.Number)]=snapshot;return h;}
CheckKeys();
foreach(int side in new[]{1,-1}){
 var h=Make();var w=Connect(h);First(h,w,side);int guard=0;
 while(h.Btc!.ResearchBatchQueued&&guard++<250){Step(h,w);Check(h.Requests<=32,"NATIVE_BATCH_COUNT_NEVER_OVER_32");Check(h.Positions.All(p=>p.VolumeInUnits<=100&&p.StopLoss!=null&&p.TakeProfit!=null),"NATIVE_EVERY_CHILD_CAPPED_AND_PROTECTED");}
 Check(guard<250&&h.Requests==32&&!h.Btc.ResearchBatchQueued,"NATIVE_32_CHILDREN_COMPLETE_WITHIN_WINDOW");Check(h.Positions.Select(p=>p.Label).Distinct().Count()==32,"NATIVE_UNIQUE_LABELS");
 Check(h.Positions.Max(p=>(p.EntryTime-start).TotalSeconds)<=182,"NATIVE_CHILD_FILL_DEADLINE");Check(h.OpenRisk()<=Math.Min(h.Account.Balance,h.Account.Equity)*.2075+1e-6,"NATIVE_GLOBAL_RISK");Check(h.Account.Margin<=Math.Min(h.Account.Balance,h.Account.Equity)*.5+1e-6,"NATIVE_GLOBAL_MARGIN");
 foreach(var p in h.Positions){double dist=(side>0?2:1.5)*200;Check(Math.Abs(Math.Abs(p.EntryPrice-p.StopLoss!.Value)-dist)<1e-7,"ACTUAL_FILL_SL");Check(Math.Abs(Math.Abs(p.TakeProfit!.Value-p.EntryPrice)-dist*(side>0?12:2))<1e-7,"ACTUAL_FILL_TP");}
 using var doc=JsonDocument.Parse(Saved(h));h.Server.TimeInUtc=doc.RootElement.GetProperty("Expiry").GetDateTime().AddSeconds(2);h.Btc.Manage(h.Server.TimeInUtc);Check(h.Positions.Count==0&&h.History.Count==32,"NATIVE_EXPIRY_CLOSES_ALL_CHILDREN");Check(Math.Abs(h.Account.Balance-100000000-h.History.Sum(p=>p.NetProfit))<1e-5,"NATIVE_CASH_RECONCILIATION");
}
{
 var h=Make();var w=Connect(h);First(h,w);Step(h,w,false);Check(h.Requests==1,"CHILD_INTENT_AWAITING_ACK_NO_ORDER");Step(h,w,false);Check(h.Requests==1,"NO_CHILD_WHILE_ACK_WITHHELD");w.Drop();Step(h,w,false);Check(h.Requests==1,"DISCONNECTED_CHILD_BLOCKED");
}
{
 var h=Make();var w=Connect(h);First(h,w);h.Server.TimeInUtc=start.AddSeconds(181);h.Btc!.Manage(h.Server.TimeInUtc);Check(h.Requests==1&&!h.Btc.ResearchBatchQueued,"NATIVE_DEADLINE_CANCELS_REMAINDER");
}
{
 var h=Make();var w=Connect(h);First(h,w);h.ClosePosition(h.Positions.Single());h.Btc!.Manage(h.Server.TimeInUtc);Check(h.Requests==1&&!h.Btc.ResearchBatchQueued,"NATIVE_BRACKET_EXIT_CANCELS_REMAINDER");
}
{
 var h=Make(100000);var w=Connect(h);First(h,w);Check(!h.Btc!.ResearchBatchQueued,"SMALL_WALLET_NATIVE_LEGACY_SINGLE");string snapshot=Saved(h);var c=Clone(h,snapshot);Connect(c,snapshot);Check(!c.Btc!.ResearchFaulted&&c.Positions.Count==1,"SINGLE_ORDER_RESTART_SUPPORTED");
}
{
 var h=Make();var w=Connect(h);First(h,w);while(h.Requests<2)Step(h,w);string snapshot=Saved(h);var c=Clone(h,snapshot);var cw=Connect(c,snapshot);Check(!c.Btc!.ResearchFaulted&&c.Positions.Count==2,"MULTI_CHILD_RESTART_SUPPORTED");int before=c.Requests;for(int i=0;i<4&&c.Requests==before;i++)Step(c,cw);Check(c.Requests==before+1,"COMMITTED_QUEUE_RESUMES_ONCE");Check(c.Positions.Select(p=>p.Label).Distinct().Count()==c.Positions.Count,"RESTART_NEVER_DUPLICATES_LABEL");
}
{
 var h=Make();var w=Connect(h);First(h,w);Step(h,w,false);string snapshot=Saved(h);var c=Clone(h,snapshot);Connect(c,snapshot);Check(c.Btc!.ResearchFaulted&&!c.Btc.ResearchBatchQueued&&c.Requests==h.Requests,"UNCERTAIN_PENDING_SEND_FAILS_CLOSED_NO_RETRY");
}
{
 var h=Make();var w=Connect(h);First(h,w);Step(h,w);string pending=Saved(h);Step(h,w);Check(h.Requests==2,"PENDING_RESULT_SETUP");var c=Clone(h,pending);Connect(c,pending);Check(!c.Btc!.ResearchFaulted&&!c.Btc.ResearchBatchQueued&&c.Positions.Count==2,"CONFIRMED_INFLIGHT_RESULT_RECONCILED_REMAINDER_CANCELLED");
}
{
 var h=Make();var w=Connect(h);h.Reject=true;h.Btc!.Enter(new(start,1,200,10000),start);w.AckAll();Step(h,w);Step(h,w);Check(h.Btc.ResearchFaulted&&h.Positions.Count==0,"BROKER_REJECTION_BLOCKS_NEW_ENTRY");
}
{
 var h=Make();var w=Connect(h);h.ReturnVolumeFactor=1.1;h.Btc!.Enter(new(start,1,200,10000),start);w.AckAll();Step(h,w);Step(h,w);Check(h.Btc.ResearchFaulted&&h.Positions.Count==0,"OVERSIZED_FILL_CLOSED_AND_BLOCKED");
}
{
 var h=Make();var w=Connect(h);h.LocalStorage.FailWrite=true;bool failed=false;try{h.Btc!.Enter(new(start,1,200,10000),start);}catch{failed=true;}Check(failed&&h.Btc!.ResearchFaulted&&h.Requests==0,"PERSISTENCE_FAILURE_BEFORE_ORDER");
}
{
 var h=Make();var w=Connect(h);h.Btc!.Enter(new(start,1,200,10000),start);h.Server.TimeInUtc=start.AddSeconds(6);h.Btc.OnTimer();w.AckAll();h.Btc.OnTimer();Check(h.Requests==0,"LATE_INITIAL_ACK_DOES_NOT_CATCH_UP");
}
{
 var h=Make();h.Btc!.OnStart();h.Btc.Enter(new(start,1,200,10000),start);Check(h.Requests==0,"NATIVE_NO_READY_FEED_NO_ORDER");
}
{
 var h=new TestHost{EnableTrading=true,ExpectedAccount="WRONG"};h.Start();Check(h.Stopped&&h.Requests==0,"NATIVE_WRONG_ACCOUNT_STARTUP_BLOCK");
 var p=new TestHost{EnableTrading=false,EnableXau=false};p.Start();Check(p.Stopped,"NATIVE_DISABLED_LEG_CHANGES_PROFILE_BLOCKED");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,NativeBranch=true,FakeBrokerOnly=true,RealOrders=0,Profile=FrozenR3.ProfileId,BuyAndSell=true}));
sealed class TestHost:RizanPortfolio{public void Start()=>OnStart();}
sealed class Wire {
 readonly TestHost h;readonly WebSocketClient socket;int cursor;long remote;
 public Wire(TestHost value){h=value;var link=typeof(BtcEngine).GetField("link",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(h.Btc)!;socket=(WebSocketClient)link.GetType().GetField("socket",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(link)!;}
 public void Ready(string? state){socket.Emit("{\"type\":\"ready\",\"revision\":0,\"state\":"+(state??"null")+"}");}
 public void Feed(string packet)=>socket.Emit(packet);
 public void Drop()=>socket.Drop();
 public void AckAll(){int guard=0;while(cursor<socket.Sent.Count&&guard++<1000){using var d=JsonDocument.Parse(socket.Sent[cursor++]);var r=d.RootElement;switch(r.GetProperty("type").GetString()){case "save":if(r.GetProperty("base_revision").GetInt64()!=remote)throw new Exception("TEST_SERVER_BASE_REVISION");socket.Emit(JsonSerializer.Serialize(new{type="ack",client_revision=r.GetProperty("client_revision").GetInt64(),revision=++remote}));break;case "ping":socket.Emit("{\"type\":\"pong\"}");break;}}if(guard>=1000)throw new Exception("TEST_ACK_LOOP");}
}
