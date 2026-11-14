using System.Reflection;
using System.Text.Json;
using Rizan.Portfolio;
using cAlgo.API;
using cAlgo.API.Internals;
static class Test {
 static int assertions;static void Check(bool x,string why){assertions++;if(!x)throw new Exception(why);}
 static readonly DateTime Now=new(2026,11,12,14,0,0,DateTimeKind.Utc);
 static readonly JsonSerializerOptions Json=new(){Converters={new Rizan.Portfolio.Xau.UtcDateTimeConverter()}};
 sealed class Host:RizanPortfolio{}
 static void Set(object o,string field,object value){Find(o.GetType(),field).SetValue(o,value);}
 static FieldInfo Find(Type t,string n){while(t!=null){var f=t.GetField(n,BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public);if(f!=null)return f;t=t.BaseType!;}throw new Exception("Missing field "+n);}
 static object Field(object o,string name)=>o.GetType().GetField(name,BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(o)!;
 static void Call(object o,string name)=>o.GetType().GetMethod(name,BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(o,null);
 static Host NewHost(){var h=new Host{EnableTrading=true,BridgeUrl="ws://127.0.0.1:25345/bootstrap125/",BridgeToken=new string('x',40),BtcBridgeUrl="ws://127.0.0.1:25345/bootstrap125/btc",BtcBridgeToken=new string('x',40)};h.ExpectedAccount=h.Account.Number.ToString();h.Server.TimeInUtc=Now;h.CreateEngines();foreach(var e in h.Engines){if(e.Instrument=="XAUUSD"||e.Instrument=="EURUSD"&&e is not BootstrapEngine){Set(e,"_bridgeReady",true);Set(e,"_lastBridgeAck",Now);}}Set(h.Btc!,"ready",true);Set(h.Btc!,"replay",true);h.Bootstrap!.OnStart();return h;}
 static BootstrapLink Link(Host h)=>(BootstrapLink)Field(h.Bootstrap!,"link");
 static WebSocketClient Socket(Host h)=>(WebSocketClient)Field(Link(h),"socket");
 static readonly Dictionary<WebSocketClient,int> read=new();
 static JsonElement? serverState;static long serverRevision;
 static void Ready(Host h,JsonElement? state=null,long revision=0){Socket(h).Emit(JsonSerializer.Serialize(new{type="ready",revision,state}));}
 static void Ack(Host h){var s=Socket(h);int i=read.GetValueOrDefault(s);for(int guard=0;guard<200&&i<s.Sent.Count;guard++){using var doc=JsonDocument.Parse(s.Sent[i++]);var r=doc.RootElement;if(r.GetProperty("type").GetString()=="save"){serverRevision=r.GetProperty("base_revision").GetInt64()+1;serverState=r.GetProperty("state").Clone();s.Emit(JsonSerializer.Serialize(new{type="ack",revision=serverRevision,client_revision=r.GetProperty("client_revision").GetInt64()}));}else if(r.GetProperty("type").GetString()=="ping")s.Emit("{\"type\":\"pong\"}");}read[s]=i;}
 static Host Connected(){var h=NewHost();Ready(h);Ack(h);Check(h.Bootstrap!.RecoveryReady,"seed bridge recovery");Check(h.PortfolioReady,"all portfolio contexts ready");return h;}
 static void Intent(Host h,double units=1000){var s=h.Bootstrap!.DebugState;s.Intent=new(){Label=BootstrapEngine.Prefix+"|"+Now.Ticks,AtUtc=Now,DeadlineUtc=Now.AddMinutes(120),Units=units,Stop=1.099,Target=1.104,Reference=100};Call(h.Bootstrap,"Save");Ack(h);}
 static void Arm(Host h){h.Bootstrap!.OnTimer();Check(h.Bootstrap.DebugState.Intent?.Stage==2,"durable armed marker");Check(h.Requests==0,"no send before armed ACK");Ack(h);}
 static JsonElement Snapshot(Host h)=>JsonSerializer.SerializeToElement(h.Bootstrap!.DebugState,Json);
 public static void Main(){
  MacroDirection.InitializeFrozenOff();
  Check(!BootstrapRules.CanGraduate(124.99,126,true),"floating profit alone cannot graduate");Check(!BootstrapRules.CanGraduate(126,126,false),"must be flat");Check(BootstrapRules.CanGraduate(125,125,true),"125 inclusive");
  var m=Enumerable.Range(0,512).Select(i=>new SeedBar(Now.AddMinutes((i-512)*5),1.1,1.101,1.099,1.1,5)).ToList();m[^1]=m[^1] with{Close=1.103,High=1.104};
  var h4=Enumerable.Range(0,1024).Select(i=>new SeedBar(Now.Date.AddHours(12).AddHours((i-1024)*4),1+i*.00001,1.1+i*.00001,.9+i*.00001,1+i*.00001,240)).ToList();
  var signal=BootstrapRules.Evaluate(m,h4,Now);Check(signal!=null,"closed bullish breakout");var future=new SeedBar(Now.AddHours(4),9,10,1,1,240);Check(BootstrapRules.Evaluate(m,h4.Append(future).ToList(),Now)==signal,"no future H4");var partial=h4.ToList();partial[^1]=partial[^1] with{Count=120};Check(BootstrapRules.Evaluate(m,partial,Now)==null,"reject partial H4");Check(BootstrapRules.Evaluate(m,h4,Now.AddMinutes(-1))==null,"no unfinished M5");
  Bars Raw(IEnumerable<SeedBar> data){var bars=new Bars();foreach(var b in data){bars.OpenTimes.Add(b.At);bars.OpenPrices.Add(b.Open);bars.HighPrices.Add(b.High);bars.LowPrices.Add(b.Low);bars.ClosePrices.Add(b.Close);}return bars;}
  var full=Connected();var minute=Enumerable.Range(0,1201).Select(i=>new SeedBar(Now.AddMinutes(i-1200),1.1,1.101,1.099,1.1,1)).ToList();
  for(int i=0;i<minute.Count;i++){var at=minute[i].At;if(at>=h4[^1].At&&at<h4[^1].At.AddHours(4))minute[i]=new(at,h4[^1].Open,h4[^1].High,h4[^1].Low,h4[^1].Close,1);else if(at>=Now.AddMinutes(-5)&&at<Now)minute[i]=new(at,1.1,1.104,1.099,1.103,1);}
  Set(full.Bootstrap!,"m1",Raw(minute));Set(full.Bootstrap!,"m5",Raw(m.Append(new(Now,1.103,1.104,1.102,1.103,5))));Set(full.Bootstrap!,"h4",Raw(h4.Append(new(Now.Date.AddHours(12),1.1,1.11,1.09,1.1,240))));
  full.Bootstrap!.OnTimer();Check(full.Bootstrap.DebugState.Intent?.Stage==1&&full.Requests==0,"broker M1/M5/H4 bars produce a prepared seed signal");Ack(full);Arm(full);full.Bootstrap.OnTimer();Check(full.Requests==1&&full.Positions.Count==1,"full closed-bar signal to protected broker order");
  var host=Connected();Intent(host);Check(host.Requests==0,"prepared marker does not submit");Arm(host);host.Bootstrap!.OnTimer();Check(host.Requests==1&&host.Positions.Count==1,"one confirmed seed order");Check(host.Positions[0].StopLoss==1.099&&host.Positions[0].TakeProfit==1.104,"absolute broker protection");Ack(host);for(int i=0;i<5;i++){host.Bootstrap.OnTimer();Ack(host);}Check(host.Requests==1,"no duplicate seed on repeat timer");
  // Same process reconnect knows the armed intent has never been submitted.
  var reconnect=Connected();Intent(reconnect);Arm(reconnect);var snap=Snapshot(reconnect);var rev=serverRevision;Socket(reconnect).Drop();reconnect.Server.TimeInUtc=Now.AddSeconds(2);reconnect.Bootstrap!.OnTimer();Ready(reconnect,snap,rev);Ack(reconnect);reconnect.Bootstrap.OnTimer();Check(reconnect.Requests==1,"known unsent intent survives reconnect");
  // A new process must not retry an armed intent with no broker receipt.
  var crash=NewHost();Ready(crash,snap,rev);Ack(crash);crash.Bootstrap!.OnTimer();Check(crash.Bootstrap.DebugState.Fault&&crash.Requests==0,"unknown armed submission fails closed");
  // A broker position after a crash reconciles by exact label; no resubmission.
  var recover=NewHost();recover.Positions.Add(new Position{Id=999,SymbolName="EURUSD",Label=snap.GetProperty("Intent").GetProperty("Label").GetString()!,EntryTime=Now,EntryPrice=1.10002,VolumeInUnits=1000,TradeType=TradeType.Buy,StopLoss=1.099,TakeProfit=1.104});Ready(recover,snap,rev);Ack(recover);recover.Bootstrap!.OnTimer();Check(!recover.Bootstrap.DebugState.Fault&&recover.Requests==0&&recover.Bootstrap.DebugState.OpenLabel!="","broker receipt recovered once");
  var rejected=Connected();rejected.Reject=true;Intent(rejected);Arm(rejected);rejected.Bootstrap!.OnTimer();Ack(rejected);rejected.Bootstrap.OnTimer();Check(rejected.Requests==1&&rejected.Bootstrap.DebugState.Fault&&rejected.Bootstrap.DebugState.Intent?.Stage==2,"rejected/unknown send retains armed receipt and cannot retry");
  var minlot=Connected();var plan=typeof(BootstrapEngine).GetMethod("Plan",BindingFlags.Instance|BindingFlags.NonPublic)!;Check(plan.Invoke(minlot.Bootstrap,new object[]{new SeedSignal(Now,1,.5)})==null,"skip unaffordable minimum lot");
  var gate=Connected();bool blocked=false;try{gate.Send(TradeType.Buy,"EURUSD",1000,FrozenR3.EurPrefix+"|forbidden",10,40,"test");}catch(InvalidOperationException){blocked=true;}Check(blocked&&gate.Requests==0,"seed phase blocks growth order path");
  var risk=Connected();risk.ReturnVolumeFactor=2;Intent(risk,5000);Arm(risk);risk.Bootstrap!.OnTimer();Check(risk.Requests==1&&risk.Positions.Count==0,"postfill excess risk is closed");
  var stale=Connected();Intent(stale);stale.Server.TimeInUtc=Now.AddSeconds(61);stale.Bootstrap!.OnTimer();Check(stale.Requests==0,"expired signal not sent");
  var phase=Connected();phase.Account.Balance=125;phase.Account.Equity=124.99;phase.Bootstrap!.OnTimer();Ack(phase);Check(phase.Bootstrap.DebugState.Phase=="SEED","require net balance and equity");phase.Account.Equity=125;phase.Bootstrap.OnTimer();Ack(phase);phase.Bootstrap.OnTimer();Check(phase.Bootstrap.DebugState.Phase=="GROWTH"&&!phase.Bootstrap.GrowthEnabled,"phase needs durable ACK");Ack(phase);Check(phase.Bootstrap.GrowthEnabled,"phase enabled after ACK");phase.Account.Balance=phase.Account.Equity=100;phase.Bootstrap.OnTimer();Check(phase.Bootstrap.GrowthEnabled,"one way latch after loss");
  var growing=Snapshot(phase);var gr=serverRevision;var restart=NewHost();Ready(restart,growing,gr);Ack(restart);Check(restart.Bootstrap!.GrowthEnabled,"growth survives cold restart below125");Check(restart.Requests==0,"restart never seeds growth account");
  var wire=Snapshot(phase);File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"bootstrap_wire_fixture.json"),wire.GetRawText());Console.WriteLine("PASS "+assertions+" financial lifecycle/phase/signal assertions; real_orders=0");
 }
}
