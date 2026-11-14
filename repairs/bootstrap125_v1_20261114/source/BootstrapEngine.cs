using System;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;
internal sealed class BootstrapEngine:EngineContext
{
 internal const string Prefix="RZB125S";
 static readonly JsonSerializerOptions Json=new(){Converters={new Xau.UtcDateTimeConverter()}};
 BootstrapState state=new();BootstrapLink? link;Bars? m1,m5,h4;bool recovered,armedHere,attempted,historyBusy;DateTime nextLoad,nextLog;
 string cache="";
 internal BootstrapEngine(RizanPortfolio host):base(host,"EURUSD"){}
 internal override void SetParameters(){}
 internal override double PendingRisk=>0;
 internal override double PendingMargin=>0;
 internal override string PendingOrderLabel=>state.Intent?.Label??"";
 internal override bool RecoveryReady=>recovered&&!state.Fault&&link!=null&&link.Persisted(state.Revision)&&!Stopped;
 internal bool GrowthEnabled=>state.Phase=="GROWTH"&&RecoveryReady;
 internal bool Submitting{get;private set;}
 internal BootstrapState DebugState=>state;
 Position[] Owned=>Positions.Where(p=>p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true).ToArray();
 void Save(){state.Revision++;var text=JsonSerializer.Serialize(state,Json);if(!IsCloudRuntime){LocalStorage.SetString(cache,text,LocalStorageScope.Instance);LocalStorage.Flush(LocalStorageScope.Instance);if(LocalStorage.GetString(cache,LocalStorageScope.Instance)!=text)throw new Exception("BOOTSTRAP_LOCAL_READBACK");}link?.Changed(state.Revision,text);}
 void Fault(string reason){state.Fault=true;state.Reason=reason;Print("BOOT125_FAULT {0}; new_orders_blocked=True",reason);try{Save();}catch{}}
 void Recover(JsonElement value){
  try{
   var knownLabel=state.Intent?.Label;bool knownUnsent=armedHere&&!attempted&&state.Intent?.Stage==2;
   if(value.ValueKind!=JsonValueKind.Null){var remote=JsonSerializer.Deserialize<BootstrapState>(value.GetRawText(),Json)??throw new Exception("EMPTY_STATE");remote.Validate(Account.Number,Server.TimeInUtc);
    if(state.Phase=="GROWTH"&&remote.Phase!="GROWTH"&&remote.Revision>=state.Revision)throw new Exception("PHASE_ROLLBACK");
    if(remote.Revision==state.Revision&&JsonSerializer.Serialize(remote,Json)!=JsonSerializer.Serialize(state,Json))throw new Exception("REVISION_CONFLICT");
    if(remote.Phase=="GROWTH"&&state.Phase!="GROWTH"){remote.Revision=Math.Max(remote.Revision,state.Revision);state=remote;}else if(remote.Revision>=state.Revision)state=remote;
   }else if(state.Revision==0&&(Owned.Length>0||History.Any(h=>h.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true)||(Positions.Any(p=>p.Label?.StartsWith(FrozenR3.XauPrefix+"|",StringComparison.Ordinal)==true||p.Label?.StartsWith(FrozenR3.EurPrefix+"|",StringComparison.Ordinal)==true||p.Label?.StartsWith(FrozenR3.BtcPrefix+"|",StringComparison.Ordinal)==true)||History.Any(p=>p.Label?.StartsWith(FrozenR3.XauPrefix+"|",StringComparison.Ordinal)==true||p.Label?.StartsWith(FrozenR3.EurPrefix+"|",StringComparison.Ordinal)==true||p.Label?.StartsWith(FrozenR3.BtcPrefix+"|",StringComparison.Ordinal)==true))))throw new Exception("CHECKPOINT_REQUIRED");
   recovered=true;if(!(knownUnsent&&state.Intent?.Label==knownLabel&&state.Intent?.Stage==2))ReconcileIntent();Save();
  }catch(Exception e){Fault("RECOVERY_"+e.Message);}
 }
 public override void OnStart(){
  cache=FrozenR3.NativeStorageKey("BOOT",Account.Number);state.AccountNumber=Account.Number;
  try{if(!IsCloudRuntime){var saved=LocalStorage.GetString(cache,LocalStorageScope.Instance);if(!string.IsNullOrEmpty(saved)){state=JsonSerializer.Deserialize<BootstrapState>(saved,Json)??throw new Exception("EMPTY_LOCAL");state.Validate(Account.Number,Server.TimeInUtc);}}
   m1=MarketData.GetBars(TimeFrame.Minute,"EURUSD");m5=MarketData.GetBars(TimeFrame.Minute5,"EURUSD");h4=MarketData.GetBars(TimeFrame.Hour4,"EURUSD");
   link=new BootstrapLink(Host,Recover);link.Changed(state.Revision,JsonSerializer.Serialize(state,Json));link.Tick();
  }catch(Exception e){Fault("START_"+e.GetType().Name);Stop();}
 }
 void ReconcileIntent(){
  armedHere=false;attempted=false;var intent=state.Intent;if(intent==null)return;
  var positions=Owned.Where(p=>p.Label==intent.Label).ToArray();var past=History.Where(h=>h.Label==intent.Label).ToArray();
  if(positions.Length>1)throw new Exception("MULTIPLE_SEED_POSITIONS");
  if(positions.Length==1){var p=positions[0];if(p.SymbolName!="EURUSD"||p.TradeType!=TradeType.Buy||p.StopLoss==null||p.TakeProfit==null)throw new Exception("UNPROTECTED_RECOVERY");state.OpenLabel=p.Label;state.OpenUnits=p.VolumeInUnits;state.DeadlineUtc=intent.DeadlineUtc;state.Intent=null;}
  else if(past.Length>0){state.OpenLabel=intent.Label;state.OpenUnits=past.Sum(h=>h.VolumeInUnits);state.DeadlineUtc=intent.DeadlineUtc;state.Intent=null;}
  else if(intent.Stage==2)throw new Exception("SUBMISSION_OUTCOME_UNCERTAIN");
  else {state.Intent=null;state.NextEntryUtc=Server.TimeInUtc.AddMinutes(5);}
 }
 public override void OnTick(){if(recovered)ObservePeak();}
 void ObservePeak(){if(state.Phase!="SEED"||state.Fault)return;double peak=Math.Max(state.Peak,Account.Equity),dd=Math.Max(state.MaxDD,peak>0?(peak-Account.Equity)/peak:0);if(peak!=state.Peak||dd!=state.MaxDD){state.Peak=peak;state.MaxDD=dd;Save();}}
 void ManageOpen(DateTime now){
  if(Owned.Any(p=>p.Label!=state.OpenLabel&&p.Label!=state.Intent?.Label)){Fault("UNTRACKED_SEED_POSITION");return;}
  if(state.OpenLabel=="")return;
  var own=Owned.Where(p=>p.Label==state.OpenLabel).ToArray();
  if(own.Length>1){Fault("MULTIPLE_SEED_POSITIONS");return;}
  if(own.Length==1){var p=own[0];if((p.StopLoss==null||p.TakeProfit==null||now>=state.DeadlineUtc)&&Host.EnableTrading)Host.Close(p);return;}
  var closed=History.Where(h=>h.Label==state.OpenLabel).ToArray();
  if(closed.Sum(h=>h.VolumeInUnits)+Symbol.VolumeInUnitsStep*.01<state.OpenUnits)return;
  if(closed.Length==0)return;
  foreach(var h in closed)if(!state.Settled.Contains(h.PositionId))state.Settled.Add(h.PositionId);
  var exit=closed.Max(h=>h.ClosingTime);state.NextEntryUtc=exit.AddMinutes(closed.Sum(h=>h.NetProfit)<0?60:5);state.OpenLabel="";state.OpenUnits=0;state.DeadlineUtc=default;Save();
 }
 public override void OnTimer(){
  try{
   var now=Server.TimeInUtc;link?.Tick();if(!recovered)return;
   ManageOpen(now);ObservePeak();
   if(state.Phase=="GROWTH"){if(Owned.Length>0)Fault("GROWTH_HAS_SEED_EXPOSURE");Telemetry(now);return;}
   if(state.Fault){Telemetry(now);return;}
   if(state.Intent!=null){ProcessIntent(now);Telemetry(now);return;}
   if(state.OpenLabel!=""||Owned.Length>0){Telemetry(now);return;}
   bool flat=!Positions.Any()&&!Host.PendingOrders.Any();
   if(RecoveryReady&&BootstrapRules.CanGraduate(Account.Balance,Account.Equity,flat)){state.Phase="GROWTH";state.GraduatedUtc=now;state.GraduationBalance=Account.Balance;Save();Print("BOOT125_PHASE growth_pending_ack=True balance={0} equity={1}",Account.Balance,Account.Equity);return;}
   if(state.MaxDD>=.6||Account.Balance<=0){if(!state.Halted){state.Halted=true;Save();}Telemetry(now);return;}
   if(!RecoveryReady||!Host.PortfolioReady||!Host.EnableTrading||!flat||state.Halted||now<state.NextEntryUtc||!Symbol.MarketHours.IsOpened(now)){Telemetry(now);return;}
   if(!Warm()){Telemetry(now);return;}
   var at=Utc(m5!.OpenTimes[m5.Count-2]).AddMinutes(5);
   if(at<=state.LastSignalUtc||at>now||(now-at).TotalSeconds>=60)return;
   var signal=BootstrapRules.Evaluate(Series(m5,5,at),Series(h4!,240,at),at);state.LastSignalUtc=at;Save();
   if(signal==null)return;
   if(state.DayUtc!=at.Date){state.DayUtc=at.Date;state.DayAttempts=0;}
   if(state.DayAttempts>=2)return;
   var intent=Plan(signal.Value);if(intent==null)return;
   state.Intent=intent;armedHere=false;attempted=false;Save();Telemetry(now);
  }catch(Exception e){Fault("RUNTIME_"+e.GetType().Name);}
 }
 bool Warm(){
  if(m1==null||m5==null||h4==null)return false;
  var need=m1.Count<1200?m1:m5.Count<513?m5:h4.Count<1025?h4:null;if(need==null)return true;
  if(!historyBusy&&Server.TimeInUtc>=nextLoad){historyBusy=true;nextLoad=Server.TimeInUtc.AddSeconds(3);need.LoadMoreHistoryAsync(_=>Host.Dispatch(()=>historyBusy=false));}return false;
 }
 static DateTime Utc(DateTime t)=>DateTime.SpecifyKind(t,DateTimeKind.Utc);
 List<SeedBar> Series(Bars bars,int minutes,DateTime available){
  var result=new List<SeedBar>();for(int i=0;i<bars.Count;i++){var at=Utc(bars.OpenTimes[i]);if(at.AddMinutes(minutes)>available)break;int count=minutes;
   // Validate the currently decisive closed M5/H4 against constituent M1 bars.
   if(i==bars.Count-2){count=0;double hi=double.MinValue,lo=double.MaxValue,o=0,c=0;for(int j=0;j<m1!.Count;j++){var t=Utc(m1.OpenTimes[j]);if(t<at||t>=at.AddMinutes(minutes))continue;if(count==0)o=m1.OpenPrices[j];c=m1.ClosePrices[j];hi=Math.Max(hi,m1.HighPrices[j]);lo=Math.Min(lo,m1.LowPrices[j]);count++;}
    if(count!=minutes||Math.Abs(o-bars.OpenPrices[i])>Symbol.TickSize*.5||Math.Abs(c-bars.ClosePrices[i])>Symbol.TickSize*.5||Math.Abs(hi-bars.HighPrices[i])>Symbol.TickSize*.5||Math.Abs(lo-bars.LowPrices[i])>Symbol.TickSize*.5)count=0;
   }
   result.Add(new(at,bars.OpenPrices[i],bars.HighPrices[i],bars.LowPrices[i],bars.ClosePrices[i],count));
  }return result;
 }
 SeedIntent? Plan(SeedSignal s){
  double bid=Symbol.Bid,entry=Symbol.Ask+.00001,spread=Symbol.Ask-bid,value=Symbol.PipValue/Symbol.PipSize;
  if(!double.IsFinite(value)||value<=0||spread<0||bid<=s.Anchor)return null;
  double distance=Math.Max(.00005,Math.Max(1.25*s.Atr,entry-s.Anchor));double perRisk=value*(distance+.00003+.00003+.00001),entryCost=value*(spread+.00001+.00003),reference=Math.Min(Account.Balance,Account.Equity),marginUnit=Symbol.GetEstimatedMargin(TradeType.Buy,Symbol.VolumeInUnitsMin)/Symbol.VolumeInUnitsMin;
  if(!double.IsFinite(marginUnit)||marginUnit<=0)return null;
  double units=Symbol.NormalizeVolumeInUnits(Math.Min(Symbol.VolumeInUnitsMax,Math.Min(reference*.08/(perRisk+.08*entryCost),reference*.5/(marginUnit+.5*entryCost))),RoundingMode.Down);
  if(units<Symbol.VolumeInUnitsMin){Print("BOOT125_MINLOT_SKIP reference={0} minimum={1}",reference,Symbol.VolumeInUnitsMin);return null;}
  return new(){Label=Prefix+"|"+s.At.Ticks,AtUtc=s.At,Units=units,Stop=entry-distance,Target=entry+4*distance,Reference=reference,DeadlineUtc=new[]{s.At.AddMinutes(120),s.At.Date.AddHours(20)}.Min()};
 }
 void ProcessIntent(DateTime now){
  var i=state.Intent!;if(!RecoveryReady)return;
  if(now<i.AtUtc||now-i.AtUtc>=TimeSpan.FromSeconds(60)||!Host.EnableTrading||!Host.PortfolioReady||Host.Positions.Any()||Host.PendingOrders.Any()||!Symbol.MarketHours.IsOpened(now)){
   if(i.Stage==1||armedHere&&!attempted){state.Intent=null;Save();}return;
  }
  if(i.Stage==1){i.Stage=2;state.DayAttempts++;armedHere=true;attempted=false;Save();return;}
  if(!armedHere||attempted){Fault("SUBMISSION_OUTCOME_UNCERTAIN");return;}
  double value=Symbol.PipValue/Symbol.PipSize,refNow=Math.Min(Account.Balance,Account.Equity),entry=Symbol.Ask+.00001;
  double risk=i.Units*value*(Math.Max(0,entry-i.Stop)+.00007),margin=Symbol.GetEstimatedMargin(TradeType.Buy,i.Units);
  if(risk>Math.Min(i.Reference,refNow)*.08+1e-8||Account.Margin+margin>Account.Equity*.5||Account.FreeMargin<margin||i.Stop>=Symbol.Bid||i.Target<=Symbol.Ask){state.Intent=null;Save();return;}
  attempted=true;Submitting=true;TradeResult result;
  try{result=Host.Send(TradeType.Buy,"EURUSD",i.Units,i.Label,(entry-i.Stop)/Symbol.PipSize,(i.Target-entry)/Symbol.PipSize,"BOOTSTRAP125_V1_SEED");}finally{Submitting=false;}
  if(!result.IsSuccessful||result.Position==null){Fault("SEED_SUBMISSION_REJECTED_OR_UNCERTAIN");return;}
  var p=result.Position;state.OpenLabel=p.Label;state.OpenUnits=p.VolumeInUnits;state.DeadlineUtc=i.DeadlineUtc;state.Intent=null;
  bool protectedOk=Host.Protect(p,i.Stop,i.Target,ProtectionType.Absolute).IsSuccessful;
  double actual=p.VolumeInUnits*value*(Math.Max(0,p.EntryPrice-i.Stop)+.00001)+2*Math.Max(p.VolumeInUnits*value*.00003,Math.Abs(p.Commissions));
  Save();if(!protectedOk||actual>i.Reference*.08+1e-8||Account.Margin>Account.Equity*.5||Symbol.Bid<=i.Stop||Symbol.Ask>=i.Target){if(!Host.Close(p).IsSuccessful)Fault("POSTFILL_RISK_CLOSE_REJECTED");}
 }
 void Telemetry(DateTime now){if(now<nextLog)return;nextLog=now.AddMinutes(1);Print("BOOT125 phase={0} ready={1} seed_halted={2} fault={3} reason={4} rev={5} balance={6} equity={7} history_busy={8}",state.Phase,RecoveryReady,state.Halted,state.Fault,state.Reason,state.Revision,Account.Balance,Account.Equity,historyBusy);}
 public override void OnStop(){link?.Dispose();}
}
