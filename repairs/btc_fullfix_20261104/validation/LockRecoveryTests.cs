using System;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using cAlgo.API;
using Rizan.Portfolio;
using F=System.Reflection.BindingFlags;

int checks=0;
void Check(bool ok,string name){checks++;if(!ok)throw new Exception(name);}
DateTime U(string s)=>DateTime.Parse(s,null,System.Globalization.DateTimeStyles.AssumeUniversal|System.Globalization.DateTimeStyles.AdjustToUniversal);
var now=U("2026-11-04T00:00:00Z");var monday=U("2026-11-02T00:00:00Z");var poison=U("2026-11-09T00:00:00Z");
string originalFeed=System.IO.File.ReadAllText(args[0]);
object Field(object o,string n)=>o.GetType().GetField(n,F.Instance|F.NonPublic)!.GetValue(o)!;
object State(TestHost h)=>Field(h.Btc!,"state");
void Set(TestHost h,string n,object v)=>State(h).GetType().GetProperty(n)!.SetValue(State(h),v);
DateTime Lock(TestHost h)=>(DateTime)State(h).GetType().GetProperty("WeekendLockUntil")!.GetValue(State(h))!;
long Revision(TestHost h)=>(long)State(h).GetType().GetProperty("Revision")!.GetValue(State(h))!;
string Saved(TestHost h)=>h.LocalStorage.Values[FrozenR3.BtcStorageKey(h.Account.Number)];
string Packet(DateTime at){
 var p=JsonNode.Parse(originalFeed)!;long through=new DateTimeOffset(BtcSevenDayFeed.Hour(at)).ToUnixTimeSeconds();
 var bars=p["bars"]!.AsArray();while(bars.Count>0&&bars[^1]![0]!.GetValue<long>()>=through)bars.RemoveAt(bars.Count-1);
 long end=bars[^1]![0]!.GetValue<long>()+3600;double close=bars[^1]![4]!.GetValue<double>();
 for(long t=end;t<through;t+=3600)bars.Add(new JsonArray(JsonValue.Create(t),JsonValue.Create(close),JsonValue.Create(close),JsonValue.Create(close),JsonValue.Create(close),JsonValue.Create(60)));
 p["through"]=through;return p.ToJsonString();
}
TestHost Make(DateTime? at=null,Action<TestHost>? mutate=null,bool ack=true,bool feed=true,bool localAhead=false){
 var h=new TestHost{EnableTrading=false,EnableXau=false,EnableEur=false,EnableBtc=true,BtcBridgeUrl="wss://test.invalid:25345",BtcBridgeToken=new string('x',32)};
 h.ExpectedAccount=h.Account.Number.ToString();h.Server.TimeInUtc=at??now;h.CreateEngines();
 Set(h,"AccountNumber",h.Account.Number);Set(h,"Revision",168L);Set(h,"WeekendLockUntil",poison);mutate?.Invoke(h);
 string remote=JsonSerializer.Serialize(State(h));
 if(localAhead){Set(h,"Revision",169L);h.LocalStorage.Values[FrozenR3.BtcStorageKey(h.Account.Number)]=JsonSerializer.Serialize(State(h));}
 else typeof(BtcEngine).GetField("state",F.Instance|F.NonPublic)!.SetValue(h.Btc,Activator.CreateInstance(State(h).GetType(),true));
 h.Btc!.OnStart();var w=new Wire(h);h.Wire=w;w.Ready(remote);if(feed)w.Feed(Packet(h.Server.TimeInUtc));if(ack)w.AckAll();return h;
}
void Tick(TestHost h)=>h.Btc!.OnTimer();

// Real recovery callback, feed acceptance, durable ACK, backup, repair and second ACK.
{
 var h=Make();string before=Saved(h);long rev=Revision(h);Tick(h);
 Check(Lock(h)==monday,"KNOWN_POISON_REPAIRED");Check(Revision(h)==rev+1,"CLIENT_REVISION_MONOTONIC");
 Check(h.Requests==0&&h.Closes==0,"REPAIR_NO_BROKER_OPERATIONS");Check(!h.Btc!.RecoveryReady,"REPAIR_WAITS_FOR_ACK");
 Check(h.LocalStorage.Values[FrozenR3.NativeStorageKey("BTCFIX",h.Account.Number)]==before,"BACKUP_IS_EXACT_PRIOR_STATE");
 var a=JsonNode.Parse(before)!.AsObject();var b=JsonNode.Parse(Saved(h))!.AsObject();a.Remove("Revision");a.Remove("WeekendLockUntil");b.Remove("Revision");b.Remove("WeekendLockUntil");
 Check(JsonNode.DeepEquals(a,b),"ALL_OTHER_STATE_FIELDS_PRESERVED");
 Tick(h);Check(h.Requests==0&&!h.Btc.RecoveryReady,"WITHHELD_REPAIR_ACK_BLOCKS_ENTRY");
 h.Wire!.AckAll();Check(h.Btc.RecoveryReady,"READY_AFTER_REPAIR_ACK");Tick(h);Check(Revision(h)==rev+1,"REPAIR_IDEMPOTENT");
 h.Btc.Enter(new(now.AddHours(-1),1,200,10000),now);Check(h.Requests==0,"OLD_SIGNAL_NOT_REPLAYED");
 var c=Make(mutate:x=>Set(x,"WeekendLockUntil",monday));Tick(c);Check(Lock(c)==monday&&!c.LocalStorage.Values.ContainsKey(FrozenR3.NativeStorageKey("BTCFIX",c.Account.Number)),"RESTART_CORRECTED_STATE_NO_SECOND_REPAIR");
}
// A local revision ahead of the remote must first be saved and ACKed normally.
{
 var h=Make(ack:false,localAhead:true);Tick(h);Check(Lock(h)==poison,"LOCAL_AHEAD_NOT_REPAIRED_BEFORE_SYNC_ACK");h.Wire!.AckAll();Tick(h);Check(Lock(h)==monday,"LOCAL_AHEAD_REPAIRS_AFTER_SYNC_ACK");
}
foreach(string kind in new[]{"FAULT","SENDING","QUEUE","PENDING_SEQUENCE","LAST_SIGNAL","EXPIRY","ACCOUNT","POSITION","PENDING_ORDER","HISTORY","NO_FEED","NO_ACK","CLOSED","BAD_SCHEDULE","UNKNOWN_LOCK","EXIT_PENDING"}){
 var h=Make(mutate:x=>{
  switch(kind){
   case "FAULT":Set(x,"Fault",true);break;
   case "SENDING":Set(x,"Sending",true);break;
   case "QUEUE":Set(x,"BatchRemaining",1);break;
   case "PENDING_SEQUENCE":Set(x,"NativePendingSequence",1);Set(x,"Sending",true);Set(x,"NativePendingLabel",FrozenR3.BtcPrefix+"|"+default(DateTime).Ticks);Set(x,"NativePendingMaxUnits",.01);Set(x,"NativePendingReference",100.0);break;
   case "LAST_SIGNAL":Set(x,"LastSignal",now.AddHours(-1));break;
   case "EXPIRY":Set(x,"Expiry",now.AddHours(1));break;
   case "ACCOUNT":x.ExpectedAccount="DIFFERENT";break;
   case "POSITION":x.Positions.Add(new(){SymbolName="EURUSD",Label="OTHER",Id=1,StopLoss=1,TakeProfit=2});break;
   case "PENDING_ORDER":x.PendingOrders.Add(new object());break;
   case "HISTORY":x.History.Add(new(){SymbolName="BTCUSD",Label=FrozenR3.BtcPrefix+"|1"});break;
   case "CLOSED":x.Symbols.GetSymbol("BTCUSD").MarketHours.Calendar=t=>t!=now&&t.DayOfWeek!=DayOfWeek.Saturday&&t.DayOfWeek!=DayOfWeek.Sunday&&(t.DayOfWeek!=DayOfWeek.Friday||t.Hour<22);break;
   case "BAD_SCHEDULE":x.Symbols.GetSymbol("BTCUSD").MarketHours.Calendar=_=>throw new Exception("OFFLINE");break;
   case "UNKNOWN_LOCK":Set(x,"WeekendLockUntil",poison.AddDays(7));break;
   case "EXIT_PENDING":Set(x,"ExitPending",true);Set(x,"ExitReason","WEEKEND_FLAT");break;
  }
 },ack:kind!="NO_ACK",feed:kind!="NO_FEED");
 Tick(h);Check(Lock(h)==(kind=="UNKNOWN_LOCK"?poison.AddDays(7):poison),"NO_UNSAFE_REPAIR_"+kind);Check(h.Requests==0,"NO_REQUEST_"+kind);
}
foreach(string failure in new[]{"WRITE","FLUSH","READBACK"}){
 var h=Make();if(failure=="WRITE")h.LocalStorage.FailWrite=true;if(failure=="FLUSH")h.LocalStorage.FailFlush=true;if(failure=="READBACK")h.LocalStorage.CorruptRead=true;
 Tick(h);Check(h.Btc!.ResearchFaulted&&Lock(h)==poison,"BACKUP_FAILURE_FAILS_CLOSED_"+failure);Check(h.Requests==0,"BACKUP_FAILURE_NO_ORDER_"+failure);
}
foreach(string at in new[]{"2026-11-06T21:00:00Z","2026-11-06T21:30:00Z","2026-11-07T12:00:00Z","2026-11-08T23:59:00Z","2026-11-09T00:00:00Z","2026-12-30T12:00:00Z"}){
 var h=Make(U(at));Tick(h);Check(Lock(h)==poison,"NO_REPAIR_OUTSIDE_SAFE_WINDOW_"+at);Check(h.Requests==0,"WINDOW_NO_ORDER");
}
{
 var h=Make();h.Wire!.Drop();Tick(h);Check(Lock(h)==poison&&h.Requests==0,"DISCONNECT_DEFERS_REPAIR");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,FullNativeRecovery=true,FakeBrokerOnly=true,RealOrders=0,OnlyLockAndRevisionChanged=true}));

sealed class TestHost:RizanPortfolio{public Wire? Wire;}
sealed class Wire{
 readonly WebSocketClient socket;int cursor;long remote=167;
 public Wire(TestHost h){var link=typeof(BtcEngine).GetField("link",F.Instance|F.NonPublic)!.GetValue(h.Btc)!;socket=(WebSocketClient)link.GetType().GetField("socket",F.Instance|F.NonPublic)!.GetValue(link)!;}
 public void Ready(string state)=>socket.Emit("{\"type\":\"ready\",\"revision\":167,\"state\":"+state+"}");
 public void Feed(string packet)=>socket.Emit(packet);
 public void Drop()=>socket.Drop();
 public void AckAll(){int n=0;while(cursor<socket.Sent.Count&&n++<100){using var d=JsonDocument.Parse(socket.Sent[cursor++]);var r=d.RootElement;if(r.GetProperty("type").GetString()=="save"){
  if(r.GetProperty("base_revision").GetInt64()!=remote)throw new Exception("BASE_REVISION_CONFLICT");socket.Emit(JsonSerializer.Serialize(new{type="ack",revision=++remote,client_revision=r.GetProperty("client_revision").GetInt64()}));
 }else if(r.GetProperty("type").GetString()=="ping")socket.Emit("{\"type\":\"pong\"}");}}
}
