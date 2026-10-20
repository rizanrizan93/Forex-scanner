using System.Globalization;
using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;
using E=Rizan.Portfolio.Eur;

BrokerCalendar.CloseHour=int.Parse(Environment.GetEnvironmentVariable("BTC_FRIDAY_CLOSE_UTC_HOUR")??"22");
Period.StartYear=args.Length>4?int.Parse(args[4]):2012;int maxYear=args.Length>3&&args[3]=="smoke"?Period.StartYear:args.Length>5?int.Parse(args[5]):2026;var bdata=Data.LoadBtc(Environment.GetEnvironmentVariable("BTC_INPUT")!);var btcSessionBars=bdata.Rows.Select(v=>new BtcBar(v.At,v.Open,v.High,v.Low,v.Close)).ToList();var btape=BtcCore.Signals(BtcCore.Aggregate(btcSessionBars,60),BtcCore.Aggregate(btcSessionBars,240));
File.WriteAllText(args[2]+".btc_signals.json",JsonSerializer.Serialize(btape));var xdata=Data.Load(args[0],true,maxYear);var edata=Data.Load(args[1],false,maxYear);
Console.WriteLine($"INPUT XAU={xdata.Rows.Length} EUR={edata.Rows.Length}");
var xtape=TapeCache.LoadOrBuild(Path.Combine(Path.GetDirectoryName(args[2])!,"../fresh_xau_tape.json"),true,()=>Data.XauTape(xdata));GC.Collect();var etape=TapeCache.LoadOrBuild(Path.Combine(Path.GetDirectoryName(args[2])!,"../fresh_eur_tape.json"),false,()=>Data.EurTape(edata));GC.Collect();
Console.WriteLine($"TAPES XAU={xtape.Signals.Count} EUR={etape.Signals.Count}");
var requested=args.Length>3?args[3]:"smoke";
double cost=double.Parse(Environment.GetEnvironmentVariable("RESEARCH_COST")??"1",CultureInfo.InvariantCulture);
string path=Environment.GetEnvironmentVariable("RESEARCH_PATH")??"A";
var scenarios=new[]{new Scenario(Environment.GetEnvironmentVariable("RESEARCH_CASE")??"REPRO",200,cost,2,path=="A",20.75,true,true,false,maxYear,Environment.GetEnvironmentVariable("RESEARCH_CONTROL")!="1")};
var reports=new List<object>();
foreach(var scenario in scenarios){var engine=new Simulation(scenario,xdata,edata,xtape,etape,bdata,btape);var result=engine.Run();reports.Add(result);File.WriteAllText(args[2]+".partial",JsonSerializer.Serialize(reports));Console.WriteLine(JsonSerializer.Serialize(new{scenario,result=engine.Summary}));}
File.WriteAllText(args[2],JsonSerializer.Serialize(new{Scope="Shared-wallet replay of the actual composed strategy source via fake broker; synchronized synthetic 1-second OHLC paths with event skipping, reliable scripted bridge ACK, no native cTrader tick verification",StartYear=Period.StartYear,EndYear=maxYear,XauRows=xdata.Rows.Length,EurRows=edata.Rows.Length,Reports=reports},new JsonSerializerOptions{WriteIndented=true}));

record struct Row(DateTime At,double Open,double High,double Low,double Close,double Spread,int Roll,bool BuyOk,bool SellOk);
record Scenario(string Name,int Leverage,double Cost,double Delay,bool Adverse,double Risk,bool Xau,bool Eur,bool Bypass,int LastYear,bool Btc);
record SignalPoint(object Signal,double Fast=0,double Slow=0);
sealed record Tape(Dictionary<DateTime,SignalPoint> Signals,Dictionary<DateTime,int> Confirmations);
sealed class Data
{
 public Row[] Rows=Array.Empty<Row>();
 public static Data LoadBtc(string path){var rows=new List<Row>();foreach(var line in File.ReadLines(path).Skip(1)){var p=line.Split(',');rows.Add(new(DateTime.Parse(p[0],CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal),double.Parse(p[1],CultureInfo.InvariantCulture),double.Parse(p[2],CultureInfo.InvariantCulture),double.Parse(p[3],CultureInfo.InvariantCulture),double.Parse(p[4],CultureInfo.InvariantCulture),0,0,false,false));}return new(){Rows=rows.ToArray()};}
 public static Data Load(string path,bool xau,int maxYear){var rows=new List<Row>();foreach(var line in File.ReadLines(path).Skip(1)){var p=line.Split(',');var at=DateTime.Parse(p[0],CultureInfo.InvariantCulture,DateTimeStyles.AdjustToUniversal|DateTimeStyles.AssumeUniversal);if(at.Year>maxYear)break;rows.Add(new(at,double.Parse(p[1],CultureInfo.InvariantCulture),double.Parse(p[2],CultureInfo.InvariantCulture),double.Parse(p[3],CultureInfo.InvariantCulture),double.Parse(p[4],CultureInfo.InvariantCulture),xau?double.Parse(p[5],CultureInfo.InvariantCulture):.00001,xau?int.Parse(p[6]):0,xau&&p[7]=="1",xau&&p[8]=="1"));}return new(){Rows=rows.ToArray()};}
 public static Tape XauTape(Data d){
  var raw=d.Rows.Select(r=>new X.Candle(r.At,r.Open,r.High,r.Low,r.Close)).ToList();var end=raw[^1].End(1);var m5=X.FrozenCore.Aggregate(raw,5,end);var m15=X.FrozenCore.Aggregate(raw,15,end);var h1=X.FrozenCore.Aggregate(raw,60,end);var atr=X.FrozenCore.Atr(m5);var candidates=X.FrozenCore.XauRaw(m5,atr,X.FrozenCore.AlignStrict(h1,60,m5),X.FrozenCore.AlignStrict(m15,15,m5));var signals=new Dictionary<DateTime,SignalPoint>();int hj=-1,mj=-1;
  for(int i=0;i<m5.Count;i++){var at=m5[i].End(5);while(hj+1<h1.Count&&h1[hj+1].End(60)<=at)hj++;while(mj+1<m15.Count&&m15[mj+1].End(15)<=at)mj++;if(i+1<100||hj+1<200||mj+1<200||at.Year<Period.StartYear||at.Hour<12||at.Hour>=17||at.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday)continue;var v=candidates[i];int side=v.Sell?-1:v.Buy?1:0;if(side!=0)signals[at]=new(new X.Signal(at,side,0,atr[i],side==1?v.BuyAnchor:v.SellAnchor));}
  var c5=m5.Where(x=>x.Count==5).ToList();var c15=m15.Where(x=>x.Count==15).ToList();var c60=h1.Where(x=>x.Count==60).ToList();var s15=X.FrozenCore.Strict(c15);var s60=X.FrozenCore.Strict(c60);var confirm=new Dictionary<DateTime,int>();hj=mj=-1;
  for(int i=1;i<c5.Count;i++){var a=c5[i];var at=a.End(5);while(hj+1<c60.Count&&c60[hj+1].End(60)<=at)hj++;while(mj+1<c15.Count&&c15[mj+1].End(15)<=at)mj++;if(hj<2||mj<1||(at-c15[mj].End(15)).TotalMinutes>15||(at-c60[hj].End(60)).TotalMinutes>60)continue;var b=c15[mj];int side=s60[hj];if(side!=s15[mj]||side==0)continue;if(side==1?a.Close>c5[i-1].High&&a.Close>a.Open&&b.Close>c15[mj-1].High&&b.Close>b.Open:a.Close<c5[i-1].Low&&a.Close<a.Open&&b.Close<c15[mj-1].Low&&b.Close<b.Open)confirm[at]=side;}
  int parity=0;foreach(var p in signals.Values.Take(12)){var s=(X.Signal)p.Signal;var v=X.FrozenCore.XauSignal(raw.Where(r=>r.OpenUtc<s.AtUtc).ToList(),s.AtUtc);if(v==null||v.Side!=s.Side||Math.Abs(v.Atr-s.Atr)>1e-8||Math.Abs(v.Anchor-s.Anchor)>1e-8)throw new Exception("XAU_SIGNAL_PARITY");parity++;}Console.WriteLine("XAU_SIGNAL_PARITY="+parity);return new(signals,confirm);
 }
 public static Tape EurTape(Data d){
  var raw=d.Rows.Select(r=>new E.Candle(r.At,r.Open,r.High,r.Low,r.Close)).ToList();var end=raw[^1].End(1);var m15=E.FrozenCore.Aggregate(raw,15,end);var h1=E.FrozenCore.Aggregate(raw,60,end);var atr=E.FrozenCore.Atr(m15);var hr=new List<E.H1Record>();foreach(var h in h1){double ema=hr.Count==0?h.Close:2d/51*h.Close+49d/51*hr[^1].Ema;double slope=hr.Count>=3?ema-hr[^3].Ema:0;hr.Add(new(h.End(60),ema,h.Close>ema&&slope>0?1:h.Close<ema&&slope<0?-1:0));}
  var features=new Dictionary<DateTime,E.Feature>();int hj=-1;for(int i=0;i<m15.Count;i++){var b=m15[i];var at=b.End(15);while(hj+1<hr.Count&&hr[hj+1].AtUtc<=at)hj++;features[at]=new(at,b.Open,b.High,b.Low,b.Close,b.Count,atr[i],b.High>b.Low?(b.Close-b.Open)/(b.High-b.Low):double.NaN,i>=8?m15.Skip(i-8).Take(8).Max(x=>x.High):double.NaN,i>=8?m15.Skip(i-8).Take(8).Min(x=>x.Low):double.NaN,hj>=0?hr[hj].Bias:99);}
  var sample=raw.Take(12000).ToList();int compared=0;foreach(var f in E.FrozenCore.EurFeatures(sample,sample[^1].End(1),new E.EurState())){var a=features[f.AtUtc];if(a.Bias!=f.Bias||a.Count!=f.Count||Math.Abs(a.Atr-f.Atr)>1e-12||Math.Abs(a.Body-f.Body)>1e-12||Math.Abs(a.PriorHigh-f.PriorHigh)>1e-12||Math.Abs(a.PriorLow-f.PriorLow)>1e-12||E.FrozenCore.EurSignal(a)!=E.FrozenCore.EurSignal(f))throw new Exception("EUR_FEATURE_PARITY");compared++;}
  var signals=new Dictionary<DateTime,SignalPoint>();var state=new E.EurState();for(int i=0;i<raw.Count;i++){var b=raw[i];if(i>0&&state.Virtual!=null){var result=E.FrozenCore.VirtualStep(state.Virtual,raw[i-1]);if(result!=null){state.Fast=2d/3*result.Value.R+state.Fast/3;state.Slow=2d/9*result.Value.R+7d/9*state.Slow;state.LastExitUtc=result.Value.AtUtc;state.Virtual=null;}}var s=features.TryGetValue(b.OpenUtc,out var f)?E.FrozenCore.EurSignal(f):null;if(s==null)continue;signals[b.OpenUtc]=new(s,state.Fast,state.Slow);if(state.Virtual==null&&(state.LastExitUtc==default||b.OpenUtc>state.LastExitUtc))state.Virtual=new(){AtUtc=s.AtUtc,LastUtc=s.AtUtc,LastClose=b.Open,Side=s.Side,Distance=s.Distance,Entry=b.Open+(s.Side==1?.00012:0)+s.Side*.00001};}
  Console.WriteLine("EUR_FEATURE_PARITY="+compared);return new(signals,new());
 }
 public int Lower(DateTime at){int lo=0,hi=Rows.Length;while(lo<hi){int mid=(lo+hi)/2;if(Rows[mid].At<at)lo=mid+1;else hi=mid;}return lo;}
}

sealed class Host:RizanPortfolio {}
sealed class Leg
{
 readonly Host HostClock;public EngineContext Context;public bool IsXau;public string Symbol=>IsXau?"XAUUSD":"EURUSD";public string Prefix=>IsXau?"RZXRC1":"RZEF245";public Type Type;public WebSocketClient Socket=new();public int Sent;public long Remote;public Queue<(DateTime Due,long Client)> Acks=new();public object? Tracked;public double EntryBalance;public int BudgetAborts;
 public dynamic State=>Type.GetField("_state",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(Context)!;
 public dynamic? Basket=>State.Basket;
 public bool AccountingBlocked;public bool Active=>!AccountingBlocked&&((!(bool)State.Quarantined&&Basket!=null)||Acks.Count>0||HostClock.Positions.Any(p=>p.SymbolName==Symbol));
 public Leg(EngineContext c,bool xau,Host host){HostClock=host;Context=c;IsXau=xau;Type=xau?typeof(X.RizanRobot):typeof(E.RizanRobot);object state=xau?new X.Checkpoint{ContractHash=X.FrozenContract.Xau.Hash,ExecutionModel="XAU_BATCH_SEND_REF_COOLDOWN_V1",AccountNumber=host.Account.Number,Symbol="XAUUSD",PeakEquity=host.Account.Equity}:new E.Checkpoint{ContractHash=E.F0245Policy.ConfigHash,ExecutionModel=E.EurBatchExecution.Model,AccountNumber=host.Account.Number,Symbol="EURUSD",PeakEquity=host.Account.Equity};Set("_state",state);Set("_storageKey",Prefix+" fixture");Set("_bridge",Socket);Set("_bridgeReady",true);}
 public void Set(string n,object v)=>Type.GetField(n,BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(Context,v);
 public void Call(string n,params object[] args){try{Type.GetMethod(n,BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(Context,args);}catch(TargetInvocationException e){throw e.InnerException!;}}
 public void Pump(DateTime ignored,double delay){for(int repeat=0;repeat<100;repeat++){var at=HostClock.Server.TimeInUtc;while(Sent<Socket.Sent.Count){using var doc=JsonDocument.Parse(Socket.Sent[Sent++]);if(doc.RootElement.GetProperty("type").GetString()=="save")Acks.Enqueue((at.AddSeconds(delay),doc.RootElement.GetProperty("client_revision").GetInt64()));}if(Sent==Socket.Sent.Count){Socket.Sent.Clear();Sent=0;}if(Acks.Count==0||Acks.Peek().Due>at)return;var a=Acks.Dequeue();Call("ReceiveBridge",JsonSerializer.Serialize(new{type="ack",revision=++Remote,client_revision=a.Client}));}throw new Exception("ACK_LOOP");}
}

sealed class Simulation
{
 // Every synthetic second is inspected. Execute source at endpoints, order/ACK,
 // bracket, add-depth and first 2R events. Between these events all quotes and
 // account marks are linear and there is no state transition. Slow mode is the
 // reference for proving identical ledger and drawdown results.
 static readonly bool Fast=Environment.GetEnvironmentVariable("RIZAN_REPLAY_SLOW")!="1";
 DateTime _clock,_lastDataAt;int _lastProgressMonth;long _inputSteps;long BrokerMarketEvents,BrokerRequestsWithDelay;long SyntheticSeconds,AckWaitingSeconds,MovingQuotesWhileAckPending;readonly Scenario cfg;readonly Data xd,ed,bd;readonly Dictionary<DateTime,BtcSignal> bt;readonly HashSet<long> btcClosed=new();int historyCursor;readonly Dictionary<int,DateTime> btcFunding=new();readonly List<object> curve=new();readonly List<object> cashEvents=new();double lastCash=100;readonly Tape xt,et;readonly Host host=new();readonly List<Leg> legs=new();readonly List<Trade> trades=new();readonly HashSet<string> recorded=new();readonly Dictionary<int,(double Peak,double DD)> yearRisk=new();readonly List<CashFlow> cashFlows=new();readonly Dictionary<int,double> yearBalances=new();readonly Dictionary<int,(double Peak,double DD)> yearNavRisk=new();int lastYear=Period.StartYear,nextDepositYear=2016;double units=1,navPeak=100,navDD;double minimumEquity=100;readonly HashSet<string> seenErrors=new();readonly List<object> errors=new();double peak=100,dd,closedPeak=100,closedDd,maxMargin,maxRisk;int overlap,missingActive;DateTime end;
 public object? Summary;
 public Simulation(Scenario c,Data x,Data e,Tape tx,Tape te,Data b,Dictionary<DateTime,BtcSignal> tb){bd=b;bt=tb;cfg=c;xd=x;ed=e;xt=tx;et=te;host.EnableBtc=c.Btc;host.Symbols.GetSymbol("BTCUSD").Leverage=double.Parse(Environment.GetEnvironmentVariable("RESEARCH_BTC_LEVERAGE")??"200",CultureInfo.InvariantCulture);host.Symbols.GetSymbol("BTCUSD").MarketHours.Calendar=BrokerCalendar.Open;host.EnableXau=c.Xau;host.EnableEur=c.Eur;host.EnableTrading=true;host.ExpectedAccount=host.Account.Number.ToString();host.BridgeUrl="wss://example.invalid:25345";host.BridgeToken="synthetic-only";host.PortfolioRiskPercent=c.Risk;host.BypassSharedChecks=c.Bypass;host.FeeFactor=c.Cost;host.Account.PreciseLeverage=c.Leverage;host.Symbols.GetSymbol("XAUUSD").Leverage=c.Leverage;host.Symbols.GetSymbol("EURUSD").Leverage=c.Leverage;host.BeforeMarketFill=WaitForBroker;host.CreateEngines();host.Btc?.ReplayStart();if(c.Eur)legs.Add(new(host.Eur!,false,host));if(c.Xau)legs.Add(new(host.Xau!,true,host));}
 void ApplyFlows(DateTime at){
  if(at.Year>lastYear){Console.Error.WriteLine("REPLAY_PROGRESS "+cfg.Name+" "+at.Year);for(int y=lastYear;y<at.Year;y++)yearBalances[y]=host.Account.Balance;lastYear=at.Year;}
  while(nextDepositYear<=2015&&new DateTime(nextDepositYear,1,1,0,0,0,DateTimeKind.Utc)<=at){
   host.Mark();double before=host.Account.Equity;if(before<=0)throw new Exception("NONPOSITIVE_NAV_AT_DEPOSIT");
   double nav=before/units;units+=50/nav;host.Account.Balance+=50;host.Mark();
   cashFlows.Add(new(new DateTime(nextDepositYear,1,1,0,0,0,DateTimeKind.Utc),50,host.Account.Balance,before,host.Account.Equity,nav));nextDepositYear++;
  }
 }
 void Observe(){host.Mark();if(host.Account.Balance!=lastCash){cashEvents.Add(new{At=host.Server.TimeInUtc,Balance=host.Account.Balance});lastCash=host.Account.Balance;}closedPeak=Math.Max(closedPeak,host.Account.Balance);closedDd=Math.Max(closedDd,(closedPeak-host.Account.Balance)/closedPeak);double nav=host.Account.Equity/units;navPeak=Math.Max(navPeak,nav);navDD=Math.Max(navDD,(navPeak-nav)/navPeak);int ny=host.Server.TimeInUtc.Year;var nr=yearNavRisk.GetValueOrDefault(ny,(Peak:nav,DD:0d));nr.Peak=Math.Max(nr.Peak,nav);nr.DD=Math.Max(nr.DD,(nr.Peak-nav)/nr.Peak);yearNavRisk[ny]=nr;minimumEquity=Math.Min(minimumEquity,host.Account.Equity);int year=host.Server.TimeInUtc.Year;var yr=yearRisk.GetValueOrDefault(year,(Peak:host.Account.Equity,DD:0d));yr.Peak=Math.Max(yr.Peak,host.Account.Equity);yr.DD=Math.Max(yr.DD,yr.Peak>0?(yr.Peak-host.Account.Equity)/yr.Peak:0);yearRisk[year]=yr;peak=Math.Max(peak,host.Account.Equity);dd=Math.Max(dd,(peak-host.Account.Equity)/peak);if(host.Account.Equity>0){maxMargin=Math.Max(maxMargin,100*host.Account.Margin/host.Account.Equity);maxRisk=Math.Max(maxRisk,100*host.OpenRisk()/Math.Min(host.Account.Balance,host.Account.Equity));}}
 void RecordBtc(){while(historyCursor<host.History.Count){var h=host.History[historyCursor++];if(h.SymbolName!="BTCUSD"||!btcClosed.Add(h.PositionId))continue;var entry=new DateTime(long.Parse(h.Label.Split('|')[1]),DateTimeKind.Utc);trades.Add(new(entry,host.Server.TimeInUtc,"BTCUSD",h.NetProfit,host.Account.Balance,1,0,1));}}
 void BtcMinute(DateTime at,Row row){foreach(var p in host.Positions.Where(p=>p.SymbolName=="BTCUSD")){var last=btcFunding.GetValueOrDefault(p.Id,new DateTime(long.Parse(p.Label.Split('|')[1]),DateTimeKind.Utc));if(at>last){double fee=p.VolumeInUnits*row.Open*.0003*(at-last).TotalDays*cfg.Cost;p.Swap-=fee;host.Account.Balance-=fee;}btcFunding[p.Id]=at;}}
 void Record(Leg l,DateTime at){if(l.Tracked==null)return;dynamic b=l.Tracked;int accepted=((int[])b.Accepted).Sum();long ticks=((DateTime)b.AtUtc).Ticks;string label=l.Prefix+"|"+ticks+"|";if(recorded.Contains(label)){l.Tracked=null;return;}if(!host.Positions.Any(p=>p.SymbolName==l.Symbol&&p.Label.StartsWith(label,StringComparison.Ordinal))){var history=host.History.Where(h=>h.SymbolName==l.Symbol&&h.Label.StartsWith(label,StringComparison.Ordinal)).ToArray();if(history.Length==0)return;double pnl=history.Sum(h=>h.NetProfit);int children=(int)Math.Round(history.Sum(h=>h.VolumeInUnits)/(l.IsXau?1:1000));trades.Add(new((DateTime)b.AtUtc,at,l.Symbol,pnl,host.Account.Balance,children,l.EntryBalance,accepted));recorded.Add(label);closedPeak=Math.Max(closedPeak,host.Account.Balance);closedDd=Math.Max(closedDd,(closedPeak-host.Account.Balance)/closedPeak);l.Tracked=null;}}
 void Manage(Leg l,DateTime at){l.Set("_lastBridgeAck",at);l.Call("ManagePositions",at);Record(l,at);if(l.IsXau&&l.Basket!=null&&!host.Positions.Any(p=>p.SymbolName==l.Symbol)&&(string)l.Type.GetField("_status",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(l.Context)! =="XAU_CLOSED_HISTORY_SETTLEMENT_WAIT"){
 dynamic basket=l.Basket;double expected=((int[])basket.Accepted).Sum()+((X.Checkpoint)l.State).RejectedFills.Sum(r=>r.Volume);
 double closed=host.History.Where(p=>p.SymbolName==l.Symbol&&p.Label.StartsWith(l.Prefix+"|"+((DateTime)basket.AtUtc).Ticks+"|",StringComparison.Ordinal)).Sum(p=>p.VolumeInUnits);
 if(closed>expected+1e-8)throw new Exception("SETTLEMENT_REGRESSION_OVERCOUNT");
 }if((bool)l.State.Quarantined&&errors.Count<20&&seenErrors.Add(l.Symbol+":"+(string)l.State.QuarantineReason)){Console.Error.WriteLine("SAFETY_QUARANTINE "+cfg.Name+" "+at.ToString("O")+" "+l.Symbol+" "+(string)l.State.QuarantineReason);errors.Add(new{At=at,Symbol=l.Symbol,Reason=(string)l.State.QuarantineReason});}}
 public object Run(){
  int ix=xd.Lower(new DateTime(Period.StartYear,1,1,0,0,0,DateTimeKind.Utc)),ie=ed.Lower(new DateTime(Period.StartYear,1,1,0,0,0,DateTimeKind.Utc));DateTime cutoff=new(cfg.LastYear+1,1,1,0,0,0,DateTimeKind.Utc);var signals=xt.Signals.Keys.Where(t=>cfg.Xau&&t<cutoff).Concat(et.Signals.Keys.Where(t=>cfg.Eur&&t<cutoff)).Concat(cfg.Btc?bt.Keys:Enumerable.Empty<DateTime>()).Where(t=>t.Year>=Period.StartYear).Distinct().OrderBy(t=>t).ToArray();int si=0;
  int ib=bd.Lower(new DateTime(Period.StartYear,1,1,0,0,0,DateTimeKind.Utc));
  cutoff=new[]{cutoff,xd.Rows[^1].At.AddMinutes(1),ed.Rows[^1].At.AddMinutes(1),bd.Rows[^1].At.AddMinutes(1)}.Min();
  while(ix<xd.Rows.Length||ie<ed.Rows.Length||ib<bd.Rows.Length){
   DateTime nextX=ix<xd.Rows.Length?xd.Rows[ix].At:DateTime.MaxValue,nextE=ie<ed.Rows.Length?ed.Rows[ie].At:DateTime.MaxValue;DateTime nextB=ib<bd.Rows.Length?bd.Rows[ib].At:DateTime.MaxValue;DateTime at=new[]{nextX,nextE,nextB}.Min();if(at>=cutoff)break;
   if(legs.All(l=>!l.Active)&&!host.Positions.Any(p=>p.SymbolName=="BTCUSD")){while(si<signals.Length&&signals[si]<at)si++;if(si>=signals.Length)break;if(signals[si]>at){ix=xd.Lower(signals[si]);ie=ed.Lower(signals[si]);ib=bd.Lower(signals[si]);continue;}}
   if(at<=_lastDataAt)throw new Exception("INPUT_TIME_NOT_ADVANCING:"+at.ToString("O"));_lastDataAt=at;_inputSteps++;if(at.Year*100+at.Month!=_lastProgressMonth){_lastProgressMonth=at.Year*100+at.Month;Console.Error.WriteLine("MONTH "+cfg.Name+" "+at.ToString("yyyy-MM-dd")+" balance="+host.Account.Balance+" requests="+host.Requests+" positions="+host.Positions.Count+" ack="+legs.Sum(l=>l.Acks.Count));}
   ApplyFlows(at);bool hx=nextX==at,he=nextE==at,hb=nextB==at;Row xr=hx?xd.Rows[ix]:default,er=he?ed.Rows[ie]:default;DateTime phaseTime=_clock>at?_clock:at;SetClock(phaseTime);
   if(hx){var s=host.Symbols.GetSymbol("XAUUSD");s.Bid=Path(xr,(int)(phaseTime-at).TotalSeconds,0);s.Ask=s.Bid+xr.Spread;}
   if(he){var s=host.Symbols.GetSymbol("EURUSD");s.Bid=Path(er,(int)(phaseTime-at).TotalSeconds,0);s.Ask=s.Bid+er.Spread;}
   if(hb){AdvanceBtc(phaseTime);BtcMinute(at,bd.Rows[ib]);}
   host.Mark();host.Btc?.Manage(phaseTime);RecordBtc();
   foreach(var l in legs){bool has=l.IsXau?hx:he;if(!has){if(l.Active)missingActive++;continue;}
    if(l.IsXau&&ix>0&&host.Positions.Any(p=>p.SymbolName==l.Symbol)&&xr.Roll>xd.Rows[ix-1].Roll){int days=xr.Roll-xd.Rows[ix-1].Roll;foreach(var p in host.Positions.Where(p=>p.SymbolName==l.Symbol)){double fee=p.VolumeInUnits*days*cfg.Cost;p.Swap-=fee;host.Account.Balance-=fee;}host.Mark();}
    Manage(l,phaseTime);l.State.PeakEquity=Math.Max((double)l.State.PeakEquity,host.Account.Equity);
    if(l.IsXau&&l.Basket!=null&&ix>0){dynamic b=l.Basket!;var prior=xd.Rows[ix-1];double distance=Math.Abs((double)b.Entry-(double)b.Stop);double extreme=(int)b.Side==1?prior.Low+xr.Spread:prior.High;b.MaxDepthPrevious=Math.Max((double)b.MaxDepthPrevious,(int)b.Side*((double)b.Entry-extreme)/distance);var s=host.Symbols.GetSymbol(l.Symbol);double fill=((int)b.Side==1?s.Ask:s.Bid)+(int)b.Side*.10;var ca=X.FrozenCore.Floor(at,5);if(host.Positions.Any(p=>p.SymbolName==l.Symbol)&&(int)b.QueueStage<0&&(int)b.NextStage<X.FrozenContract.Xau.Stages&&at<=((DateTime)b.AtUtc).AddMinutes(X.FrozenContract.Xau.AddMinutes)&&xt.Confirmations.GetValueOrDefault(ca)==(int)b.Side&&ca!=(DateTime)b.LastConfirmationUtc&&(double)b.MaxDepthPrevious>=X.FrozenContract.Xau.Depths[(int)b.NextStage]&&(int)b.Side*((double)b.Entry-fill)>=.05*distance){b.LastConfirmationUtc=ca;l.Call("QueueStage",(int)b.NextStage,fill);}}
    l.State.LastBarUtc=at.AddMinutes(-1);l.Call("Changed");var tape=l.IsXau?xt:et;
    SignalPoint? point=null;bool hasSignal=tape.Signals.TryGetValue(at,out point);
    if(hasSignal){var signalTime=l.IsXau?((X.Signal)point!.Signal).AtUtc:((E.Signal)point!.Signal).AtUtc;if(signalTime>phaseTime)throw new Exception("FUTURE_SIGNAL_READ");}
    if(l.Basket==null&&hasSignal&&host.PortfolioReady&&host.NoForeignExposure()&&at>(DateTime)l.State.LastRealExitUtc&&at>(DateTime)l.State.LastSignalUtc){
      if(l.IsXau){var sig=(X.Signal)point.Signal;if(!(sig.Side==1?xr.BuyOk:xr.SellOk))continue;l.Set("_snapshot",cfg.Name=="STRICT_NO_MACRO"?null!:new X.ExternalSnapshot{ProducedUtc=at,CoverageFromUtc=at.AddMinutes(-30),CoverageToUtc=at.AddMinutes(495),ForexFactoryOk=true,BlsOk=true,Dgs10=new(){Delta=-sig.Side,AvailableUtc=at},Dfii10=new(){Delta=-sig.Side,AvailableUtc=at}});}
      else{l.State.Eur.Fast=point.Fast;l.State.Eur.Slow=point.Slow;}
      l.EntryBalance=host.Account.Balance;l.Call("PrepareBasket",point.Signal,phaseTime);if(l.Basket!=null)l.Tracked=l.Basket;
    }
   }
   if(hb&&cfg.Btc&&bt.TryGetValue(at,out var bs))host.Btc?.Enter(bs,host.Server.TimeInUtc);RecordBtc();
   Observe();if(host.Positions.Any(p=>p.SymbolName=="XAUUSD")&&host.Positions.Any(p=>p.SymbolName=="EURUSD"))overlap++;
   int xside=host.Xau==null?1:(int)(legs.First(l=>l.IsXau).Basket?.Side??1),eside=host.Eur==null?1:(int)(legs.First(l=>!l.IsXau).Basket?.Side??1);
   if(legs.Any(l=>l.Active)||host.Positions.Any(p=>p.SymbolName=="BTCUSD"))for(int sec=0;sec<60;sec++){
    var time=at.AddSeconds(sec);if(time<_clock)continue;SetClock(time);SyntheticSeconds++;bool waiting=legs.Any(l=>l.Acks.Count>0);double oldX=host.Symbols.GetSymbol("XAUUSD").Bid,oldE=host.Symbols.GetSymbol("EURUSD").Bid;if(waiting)AckWaitingSeconds++;
    if(hx){var s=host.Symbols.GetSymbol("XAUUSD");s.Bid=Path(xr,sec,xside);s.Ask=s.Bid+xr.Spread;}
    if(he){var s=host.Symbols.GetSymbol("EURUSD");s.Bid=Path(er,sec,eside);s.Ask=s.Bid+er.Spread;}
    if(waiting&&(oldX!=host.Symbols.GetSymbol("XAUUSD").Bid||oldE!=host.Symbols.GetSymbol("EURUSD").Bid))MovingQuotesWhileAckPending++;
    if(hb)AdvanceBtc(time);host.Btc?.Manage(time);RecordBtc();
    if(Fast&&sec!=0&&sec!=20&&sec!=40&&sec!=59&&!Transition(time,hx,he))continue;
    Observe();foreach(var position in host.Positions.ToArray()){if(position.SymbolName=="BTCUSD"?!hb:position.SymbolName=="XAUUSD"?!hx:!he)continue;var s=host.Symbols.GetSymbol(position.SymbolName);int sign=position.TradeType==TradeType.Buy?1:-1;double exit=sign==1?s.Bid:s.Ask;if(sign*(exit-position.StopLoss!.Value)<=0||sign*(exit-position.TakeProfit!.Value)>=0)host.ClosePosition(position);}
    foreach(var l in legs){if(l.IsXau?!hx:!he)continue;time=host.Server.TimeInUtc;Manage(l,time);dynamic? b=l.Basket;if(!l.IsXau&&b!=null&&(int)b.QueueStage<0&&(int)b.NextStage<E.F0245Policy.Contract.Stages&&host.Positions.Any(p=>p.SymbolName==l.Symbol)&&time<=((DateTime)b.AtUtc).AddMinutes(E.F0245Policy.Contract.AddMinutes)){var s=host.Symbols.GetSymbol(l.Symbol);double quote=(int)b.Side==1?s.Ask:s.Bid;double depth=(int)b.Side*((double)b.Entry-quote)/Math.Abs((double)b.Entry-(double)b.Stop);if(depth>=E.F0245Policy.Contract.Depths[(int)b.NextStage])l.Call("QueueStage",(int)b.NextStage,quote);}
      l.Call("ProcessQueue",time);time=host.Server.TimeInUtc;l.Call("Persist");l.Pump(time,cfg.Delay);if(l.Basket!=null)l.Tracked=l.Basket;Record(l,time);
    }
    RecordBtc();Observe();if(legs.All(l=>!l.Active)&&!host.Positions.Any(p=>p.SymbolName=="BTCUSD"))break;
   }
   foreach(var l in legs)if(!l.Active)l.Set("_persistedRevision",(long)l.State.Revision);
   RecordBtc();if(at.Minute==0)curve.Add(new{At=at,Equity=host.Account.Equity,Balance=host.Account.Balance,Peak=peak,DD=dd*100});end=at.AddMinutes(1);if(hx)ix++;if(he)ie++;if(hb)ib++;
  }
  int terminalForcedCloses=0;RecordBtc();foreach(var l in legs){Record(l,end);Manage(l,end);}Observe();
  for(int y=lastYear;y<=cfg.LastYear;y++)yearBalances[y]=host.Account.Balance;double gain=trades.Sum(t=>Math.Max(0,t.Pnl)),loss=trades.Sum(t=>Math.Max(0,-t.Pnl));var annual=new List<object>();double previous=100;for(int year=Period.StartYear;year<=cfg.LastYear;year++){var closed=trades.Where(t=>t.Exit.Year==year).ToList();double balance=yearBalances[year],deposits=cashFlows.Where(f=>f.At.Year==year).Sum(f=>f.Amount);annual.Add(new{Year=year,AnnualEquityDDPct=100*yearRisk.GetValueOrDefault(year).DD,AnnualNavDDPct=100*yearNavRisk.GetValueOrDefault(year).DD,Start=previous,Deposits=deposits,TradingPnl=balance-previous-deposits,End=balance,ReturnOnOpeningPlusDepositsPct=100*(balance/(previous+deposits)-1),Baskets=closed.Count,XauBaskets=closed.Count(t=>t.Symbol=="XAUUSD"),EurBaskets=closed.Count(t=>t.Symbol=="EURUSD")});previous=balance;}
  if(Math.Abs(100+cashFlows.Sum(f=>f.Amount)+trades.Sum(t=>t.Pnl)+host.Positions.Sum(p=>p.Commissions+p.Swap)-host.Account.Balance)>Math.Max(1e-6,Math.Abs(host.Account.Balance)*1e-10))throw new Exception("LEDGER_CASH_CONSERVATION");
  Summary=new{cfg,TerminalForcedCloses=terminalForcedCloses,AccountingBlock=legs.Any(l=>l.AccountingBlocked),BtcFridayCloseHourUTC=BrokerCalendar.CloseHour,HistoricalBrokerSessionCertified=false,BtcWeekendBarsFiltered=false,BtcIndicatorSource="Bitstamp OHLC all seven days",NativeSevenDayFeedIntegrated=true,NativeBridgeIOExercisedInReplay=false,NativeBridgeProtocolTestedSeparately=true,SyntheticReliableHeartbeats=true,BrokerEntryDelaySeconds=Environment.GetEnvironmentVariable("RESEARCH_NEXT_M1")=="1"?-1:2,DelayPolicy=Environment.GetEnvironmentVariable("RESEARCH_NEXT_M1")=="1"?"broker fills at next M1 open for each market request; ACK remains 2 seconds":"broker 2 seconds",SpreadStressMultiplier=1,BtcLeverage=host.Symbols.GetSymbol("BTCUSD").Leverage,BrokerRequestsWithDelay,BrokerMarketEvents,ClockMonotonic=true,SyntheticSeconds,AckWaitingSeconds,MovingQuotesWhileAckPending,PathDependsOnPosition=false,RealTicks=false,MacroVintageCertified=false,EndingBalance=host.Account.Balance,TotalContributions=100+cashFlows.Sum(f=>f.Amount),TradingPnl=host.Account.Balance-100-cashFlows.Sum(f=>f.Amount),CashFlowAdjustedMaxDDPct=100*navDD,EndingNav=host.Account.Equity/units,MinimumEquity=minimumEquity,MaxEquityDDPct=100*dd,MaxClosedDDPct=100*closedDd,PF=loss>0?gain/loss:0,Baskets=trades.Count,AcceptedBaskets=trades.Count(t=>t.AcceptedChildren>0),RejectedFillBaskets=trades.Count(t=>t.AcceptedChildren==0),XauBaskets=trades.Count(t=>t.Symbol=="XAUUSD"),EurBaskets=trades.Count(t=>t.Symbol=="EURUSD"),BtcBaskets=trades.Count(t=>t.Symbol=="BTCUSD"),BtcBuys=host.History.Count(t=>t.SymbolName=="BTCUSD"&&t.TradeType==TradeType.Buy),BtcSells=host.History.Count(t=>t.SymbolName=="BTCUSD"&&t.TradeType==TradeType.Sell),EndingEquity=host.Account.Equity,OpenPositions=host.Positions.Count,ActualCutoff=cutoff,PortfolioBudgetBlocks=host.PortfolioBudgetBlocks,MaxObservedMarginPct=maxMargin,MaxObservedOpenRiskPct=maxRisk,OverlapMinutes=overlap,MissingActiveInstrumentMinutes=missingActive,Orders=host.Requests,Quarantined=legs.Any(l=>(bool)l.State.Quarantined),ErrorCount=errors.Count};
  return new{Summary,CashFlows=cashFlows,Annual=annual,Monthly=trades.GroupBy(t=>t.Exit.ToString("yyyy-MM")).Select(g=>new{Month=g.Key,Baskets=g.Count(),NetPnl=g.Sum(t=>t.Pnl),BalanceAfter=g.Last().BalanceAfter}),Ledger=trades,Curve=curve,BrokerHistory=host.History,CashEvents=cashEvents,Open=host.Positions,Errors=errors};
 }
 bool Transition(DateTime time,bool hx,bool he){

  foreach(var p in host.Positions){if(p.SymbolName!="BTCUSD"&&(p.SymbolName=="XAUUSD"?!hx:!he))continue;var s=host.Symbols.GetSymbol(p.SymbolName);int sign=p.TradeType==TradeType.Buy?1:-1;double exit=sign==1?s.Bid:s.Ask;if(sign*(exit-p.StopLoss!.Value)<=0||sign*(exit-p.TakeProfit!.Value)>=0)return true;}
  foreach(var l in legs){if(l.IsXau?!hx:!he)continue;dynamic? b=l.Basket;if(l.Acks.Count>0)return true;if(b==null)continue;if((int)b.QueueStage>=0||(string)l.State.PendingLabel!=""||time>=((DateTime)b.ExitUtc))return true;
   if(!l.IsXau&&host.Positions.Any(p=>p.SymbolName==l.Symbol)){var s=host.Symbols.GetSymbol(l.Symbol);double quote=(int)b.Side==1?s.Ask:s.Bid,exit=(int)b.Side==1?s.Bid:s.Ask;
    if(!(bool)b.BreakEvenArmed&&(int)b.Side*(exit-(double)b.Entry)>=2*(double)b.OriginalDistance)return true;
    int stage=(int)b.NextStage;if(stage<E.F0245Policy.Contract.Stages&&time<=((DateTime)b.AtUtc).AddMinutes(E.F0245Policy.Contract.AddMinutes)&&(int)b.Side*((double)b.Entry-quote)/Math.Abs((double)b.Entry-(double)b.Stop)>=E.F0245Policy.Contract.Depths[stage])return true;
   }
  }return false;
 }
 void SetClock(DateTime t){if(t<_clock)throw new Exception("SIMULATION_CLOCK_REWIND");_clock=t;host.Server.TimeInUtc=t;foreach(var l in legs)l.Set("_lastBridgeAck",t);}
 void WaitForBroker(){BrokerRequestsWithDelay++;int delay=Environment.GetEnvironmentVariable("RESEARCH_NEXT_M1")=="1"?60-_clock.Second:2;for(int step=0;step<delay;step++){var time=_clock.AddSeconds(1);SetClock(time);AdvanceQuote(xd,"XAUUSD",time);AdvanceQuote(ed,"EURUSD",time);AdvanceBtc(time);BrokerMarketEvents++;host.Mark();foreach(var pos in host.Positions.ToArray()){var sym=host.Symbols.GetSymbol(pos.SymbolName);int side=pos.TradeType==TradeType.Buy?1:-1;double price=side==1?sym.Bid:sym.Ask;if(side*(price-pos.StopLoss!.Value)<=0||side*(price-pos.TakeProfit!.Value)>=0)host.ClosePosition(pos);}Observe();}}
 void AdvanceQuote(Data d,string symbol,DateTime time){var minute=new DateTime(time.Year,time.Month,time.Day,time.Hour,time.Minute,0,DateTimeKind.Utc);int i=d.Lower(minute);if(i>=d.Rows.Length||d.Rows[i].At!=minute)return;var row=d.Rows[i];var sym=host.Symbols.GetSymbol(symbol);sym.Bid=Path(row,time.Second,0);sym.Ask=sym.Bid+row.Spread;}
 void AdvanceBtc(DateTime time){var minute=new DateTime(time.Year,time.Month,time.Day,time.Hour,time.Minute,0,DateTimeKind.Utc);int i=bd.Lower(minute);if(i>=bd.Rows.Length||bd.Rows[i].At!=minute||!BrokerCalendar.Open(time))return;var row=bd.Rows[i];var sym=host.Symbols.GetSymbol("BTCUSD");sym.Bid=Path(row,time.Second,0);sym.Ask=sym.Bid*1.0005;}
 double Path(Row r,int sec,int side){ulong key=unchecked((ulong)r.At.Ticks/600000000UL);key^=key>>17;key*=0xed5ad4bbUL;bool lowFirst=((key^(cfg.Adverse?0UL:1UL))&1)==0;double first=lowFirst?r.Low:r.High,second=lowFirst?r.High:r.Low;return sec<=20?r.Open+(first-r.Open)*sec/20d:sec<=40?first+(second-first)*(sec-20)/20d:second+(r.Close-second)*(sec-40)/19d;}
}
record Trade(DateTime Entry,DateTime Exit,string Symbol,double Pnl,double BalanceAfter,int Children,double ReferenceBalance,int AcceptedChildren);

record CashFlow(DateTime At,double Amount,double BalanceAfter,double EquityBefore,double EquityAfter,double NavAtDeposit);
static class Period {public static int StartYear=2012;}

record CacheSignal(DateTime At,int Side,double Distance,double Atr,double Anchor,double Fast,double Slow);
record CacheTape(CacheSignal[] Signals,Dictionary<DateTime,int> Confirmations);
static class TapeCache{
 public static Tape LoadOrBuild(string path,bool xau,Func<Tape> factory){
  if(File.Exists(path)){var a=JsonSerializer.Deserialize<CacheTape>(File.ReadAllText(path))!;return new(a.Signals.ToDictionary(s=>s.At,s=>new SignalPoint(xau?(object)new X.Signal(s.At,s.Side,s.Distance,s.Atr,s.Anchor):new E.Signal(s.At,s.Side,s.Distance,s.Atr,s.Anchor),s.Fast,s.Slow)),a.Confirmations);}
  var tape=factory();var signals=tape.Signals.Select(pair=>{if(xau){var s=(X.Signal)pair.Value.Signal;return new CacheSignal(s.AtUtc,s.Side,s.Distance,s.Atr,s.Anchor,pair.Value.Fast,pair.Value.Slow);}else{var s=(E.Signal)pair.Value.Signal;return new CacheSignal(s.AtUtc,s.Side,s.Distance,s.Atr,s.Anchor,pair.Value.Fast,pair.Value.Slow);}}).ToArray();File.WriteAllText(path,JsonSerializer.Serialize(new CacheTape(signals,tape.Confirmations)));return tape;
 }
}

static class BrokerCalendar {public static int CloseHour=22;public static bool Open(DateTime t)=>Environment.GetEnvironmentVariable("BTC_SEVEN_DAY")=="1"||t.DayOfWeek!=DayOfWeek.Saturday&&t.DayOfWeek!=DayOfWeek.Sunday&&(t.DayOfWeek!=DayOfWeek.Friday||t.Hour<CloseHour);}
