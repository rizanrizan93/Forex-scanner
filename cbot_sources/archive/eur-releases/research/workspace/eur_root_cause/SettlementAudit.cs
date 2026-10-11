using Rizan.Frozen;
using System.Globalization;
using System.Text.Json;
var ic=CultureInfo.InvariantCulture;
var raw=File.ReadLines(args[0]).Skip(1).Select(line=>{var p=line.Split(',');return new Candle(DateTime.Parse(p[0],ic,DateTimeStyles.AdjustToUniversal),double.Parse(p[1],ic),double.Parse(p[2],ic),double.Parse(p[3],ic),double.Parse(p[4],ic));}).ToList();
var end=raw[^1].OpenUtc.AddMinutes(1);
var m15=FrozenCore.Aggregate(raw,15,end);var h1=FrozenCore.Aggregate(raw,60,end);var atr=FrozenCore.Atr(m15);
// Equivalent causal feature construction; keep full H1 lookup only for batch replay.
var hr=new List<H1Record>();
foreach(var h in h1){double ema=hr.Count==0?h.Close:2d/51*h.Close+49d/51*hr[^1].Ema;double slope=hr.Count>=3?ema-hr[^3].Ema:0;hr.Add(new(h.End(60),ema,h.Close>ema&&slope>0?1:h.Close<ema&&slope<0?-1:0));}
var features=new Dictionary<DateTime,Feature>();int hj=-1;
for(int i=0;i<m15.Count;i++){var b=m15[i];var at=b.End(15);while(hj+1<hr.Count&&hr[hj+1].AtUtc<=at)hj++;double ph=i>=8?m15.Skip(i-8).Take(8).Max(x=>x.High):double.NaN;double pl=i>=8?m15.Skip(i-8).Take(8).Min(x=>x.Low):double.NaN;features[at]=new(at,b.Open,b.High,b.Low,b.Close,b.Count,atr[i],b.High>b.Low?(b.Close-b.Open)/(b.High-b.Low):double.NaN,ph,pl,hj>=0?hr[hj].Bias:99);}
// Check optimized feature construction against untouched core on a short warmup.
var sample=raw.Take(12000).ToList();var check=FrozenCore.EurFeatures(sample,sample[^1].OpenUtc.AddMinutes(1),new EurState());int compared=0;
foreach(var f in check){var a=features[f.AtUtc];if(a.Bias!=f.Bias||a.Count!=f.Count||Math.Abs(a.Atr-f.Atr)>1e-12||Math.Abs(a.Body-f.Body)>1e-12||Math.Abs(a.PriorHigh-f.PriorHigh)>1e-12||Math.Abs(a.PriorLow-f.PriorLow)>1e-12||FrozenCore.EurSignal(a)!=FrozenCore.EurSignal(f))throw new Exception("FEATURE_PARITY_FAIL");compared++;}
Console.WriteLine($"Loaded {raw.Count} M1; feature parity {compared}");
var reports=new List<object>();
var cases=new List<(bool Unlimited,bool Expiry,bool Paid,bool Peak,bool Gap,bool Time,bool Precise)>();
foreach(bool gap in new[]{false,true})foreach(bool time in new[]{false,true})foreach(bool precise in new[]{false,true})cases.Add((false,true,false,false,gap,time,precise));
cases.Add((true,true,true,true,true,true,true));
foreach(var spec in cases)foreach(bool adverseFirst in new[]{true,false})
{
 double factor=1;var engine=new Engine(factor,adverseFirst,spec.Unlimited?1000000:3,spec.Expiry,spec.Paid,spec.Peak,spec.Gap,spec.Time,spec.Precise);var state=new EurState();var start=new DateTime(2016,1,1,0,0,0,DateTimeKind.Utc);int signals=0,virtuals=0;
 // Fresh virtual feedback at start; indicators warm up from earliest available 2016 data. No 2015 data available.
 for(int i=0;i<raw.Count;i++){
   var b=raw[i];if(b.OpenUtc<start)continue;
   // At this minute's opening quote, previous M1 is now closed and causal.
   if(i>0&&state.Virtual!=null){var vx=FrozenCore.VirtualStep(state.Virtual,raw[i-1]);if(vx!=null){state.Fast=2d/3*vx.Value.R+1d/3*state.Fast;state.Slow=2d/9*vx.Value.R+7d/9*state.Slow;state.LastExitUtc=vx.Value.AtUtc;state.Virtual=null;virtuals++;}}
   if(i>0&&spec.Gap&&(b.OpenUtc-raw[i-1].OpenUtc).TotalMinutes>5)engine.Gap(b.OpenUtc,b.Open);
   if(i>0&&spec.Time)engine.ReferenceTime(b.OpenUtc,b.Open,raw[i-1]);
   engine.Boundary(b.OpenUtc,b.Open);
   Signal? s=features.TryGetValue(b.OpenUtc,out var f)?FrozenCore.EurSignal(f):null;
   if(s!=null){signals++;engine.Start(s,b.Open,FrozenCore.EurScale(state));if(state.Virtual==null&&(state.LastExitUtc==default||b.OpenUtc>state.LastExitUtc))state.Virtual=new(){AtUtc=s.AtUtc,LastUtc=s.AtUtc,LastClose=b.Open,Side=s.Side,Distance=s.Distance,Entry=b.Open+(s.Side==1?.00012:0)+s.Side*.00001};}
   engine.Bar(b);
 }
 engine.Finish(raw[^1]);var report=engine.Report(signals,virtuals);reports.Add(report);
 Console.WriteLine(JsonSerializer.Serialize(report));
}
File.WriteAllText(args[1],JsonSerializer.Serialize(new{Scope="C# source replay with synthetic 1-second OHLC paths; not cTrader native/tick backtest",Rows=raw.Count,FeatureParity=compared,Reports=reports},new JsonSerializerOptions{WriteIndented=true}));

sealed class Engine(double factor,bool adverseFirst,int rate,bool initialExpiry,bool paidAnchor,bool extremaPeak,bool referenceGap,bool referenceTime,bool preciseBracket)
{
 readonly FrozenContract c=FrozenContract.Eur with{Slip=.00001*factor,CommissionPerSide=FrozenContract.Eur.CommissionPerSide*factor};readonly double spread=.00001*factor;
 double cash=100,peak=100,dd=0,closedPeak=100,cdd=0,intrabarPeak=100,intrabarDd=0,before;
 Basket? basket;int live;double entries;DateTime lastExit;bool quarantined;string reason="";
 int queueCaps,budgetBlocks,totalSignals,unfunded,children,totalAdds;double maxMargin,maxRisk;readonly List<Trade> ledger=new();readonly int[] requested=new int[3];readonly double[] fillSum=new double[3];readonly DateTime[] firstFill=new DateTime[3],lastFill=new DateTime[3];readonly List<object> failures=new();
    Basket? StartDiagnostic(FrozenContract c,Signal signal,double entry,double balance,double equity,double freeMargin,double usedMargin,double marginChild,double scale,double peak)
    {
        if(!FrozenCore.Finite(usedMargin) || !new[]{entry,balance,equity,marginChild,scale,peak}.All(x=>FrozenCore.Finite(x)&&x>0) || !FrozenCore.Finite(freeMargin) || freeMargin<0 || usedMargin<0) return null;
        double distance=c.Symbol=="XAUUSD" ? Math.Max(.5,Math.Max(2.65*signal.Atr,signal.Side*(entry-signal.Anchor))) : signal.Distance;
        if(!FrozenCore.Finite(distance) || distance<=0 || signal.Side is not (1 or -1)) return null;
        double stop=entry-signal.Side*distance;double reference=Math.Min(balance,equity);
        double rc=reference*c.RiskFraction*scale;double mc=Math.Max(0,Math.Min(freeMargin,reference*c.MarginFraction*scale-usedMargin));
        double risk=paidAnchor?FrozenCore.ChildRisk(c,signal.Side,entry,stop):FrozenCore.PlannedChildRisk(c,signal.Side,entry,stop);
        int count=FrozenCore.FloorCount(Math.Min(rc/risk,mc/marginChild));
        if(c.Symbol=="XAUUSD") count=Math.Min(count,Math.Max(1,FrozenCore.FloorCount(balance/100)));
        double degear=c.Symbol=="EURUSD" && (peak-equity)/peak>=.25 ? .7 : 1;
        double budget=rc*degear;
        int initial=count>0 ? Math.Min(Math.Max(1,FrozenCore.FloorCount(count*c.InitialFraction*degear)),FrozenCore.FloorCount(budget/risk)) : 0;
        if(initial<1) return null;
        DateTime exit=signal.AtUtc.AddMinutes(c.HoldMinutes);var daily=signal.AtUtc.Date.AddHours(20).AddMinutes(c.Symbol=="XAUUSD" ? -1 : 0);if(exit>daily)exit=daily;
        return new(){AtUtc=signal.AtUtc,ExitUtc=exit,Side=signal.Side,Entry=entry,Stop=stop,Target=entry+signal.Side*distance*c.TargetR,
            ReferenceBalance=reference,RiskBudget=budget,Scale=scale,RemainingStageBudget=Math.Max(0,budget-initial*risk),InitialRiskAllocation=initial*risk,InitialWanted=initial,NextStage=0,QueueStage=0,QueueRemaining=initial};
    }

 public double Equity(double bid)=>cash+(basket==null?0:1000*basket.Side*(live*(bid+(basket.Side==-1?spread:0))-entries));
 double Margin(double bid)=>live*1000*(bid+spread)/200;
 public void Gap(DateTime at,double bid){if(basket==null)return;Cancel();if(live>0)Close(at,bid,"GAP_REFERENCE");Manage(at,bid);}
 public void ReferenceTime(DateTime at,double bid,Candle previous){if(basket!=null&&live>0&&at>=basket.ExitUtc){Cancel();Close(previous.OpenUtc,previous.Close,"TIME_REFERENCE");Manage(at,bid);}}
 public void Boundary(DateTime at,double bid){Observe(bid);Manage(at,bid);Observe(bid);var eq=Equity(bid);peak=Math.Max(peak,extremaPeak?intrabarPeak:eq);dd=Math.Max(dd,(peak-eq)/peak);}
 void Manage(DateTime at,double bid){if(basket==null)return;if(at>=basket.ExitUtc&&live>0)Close(at,bid,"TIME");if(basket!=null&&live==0&&(basket.Accepted.Sum()>0||basket.QueueStage<0||at>=basket.ExitUtc)){lastExit=FrozenCore.Floor(at,1);basket=null;}}
 public void Start(Signal s,double bid,double scale){totalSignals++;if(basket!=null||quarantined||s.AtUtc<=lastExit)return;double quote=bid+(s.Side==1?spread:0);basket=StartDiagnostic(c,s,quote+(paidAnchor?s.Side*c.Slip:0),cash,cash,cash,0,1000*quote/200,scale,peak);if(basket==null){unfunded++;return;}before=cash;live=0;entries=0;Array.Clear(requested);Array.Clear(fillSum);Array.Clear(firstFill);Array.Clear(lastFill);requested[0]=basket.InitialWanted;}
 void Cancel(){if(basket==null)return;basket.QueueRemaining=0;basket.QueueStage=-1;}
 void Fill(DateTime at,double bid){var b=basket;if(b==null||b.QueueStage<0||b.QueueRemaining<=0||quarantined)return;
  if(at>=b.ExitUtc||(initialExpiry&&b.QueueStage==0&&at>=b.AtUtc.AddMinutes(1))||(b.QueueStage>0&&at>b.AtUtc.AddMinutes(c.AddMinutes))){if(b.QueueStage==0&&b.QueueRemaining>0)queueCaps++;Cancel();return;}
  double fill=bid+(b.Side==1?spread:0),risk=FrozenCore.PlannedChildRisk(c,b.Side,fill,b.Stop),margin=1000*(bid+spread)/200,eq=Equity(bid),used=Margin(bid),reference=Math.Min(b.ReferenceBalance,eq);
  bool geometry=b.Side*(fill-b.Stop)>.00001&&b.Side*(b.Target-fill)>.00001;
  if(!FrozenCore.FillBudgetOk(c,b,b.QueueStage,fill,eq,eq-used,used,margin,spread)){Cancel();budgetBlocks++;return;}
  if(!geometry||b.StageRisk[b.QueueStage]+risk>FrozenCore.StageAllocation(c,b,b.QueueStage)+1e-8||b.UsedRisk+risk>Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8||used+margin>reference*c.MarginFraction*b.Scale+1e-8||eq-used<margin+c.CommissionPerSide){Cancel();budgetBlocks++;return;}
  double actual=fill+b.Side*c.Slip,ar=FrozenCore.ChildRisk(c,b.Side,actual,b.Stop);
  // Broker fills incur entry commission immediately, then post-fill guards run.
  cash-=c.CommissionPerSide;live++;entries+=actual;
  if(!FrozenCore.ActualFillBudgetOk(c,b,b.QueueStage,actual,Equity(bid),Margin(bid))){failures.Add(new{AtUtc=at,Stage=b.QueueStage,FillQuote=fill,ActualFill=actual,PlannedChildRisk=risk,ActualChildRisk=ar,StageRiskBefore=b.StageRisk[b.QueueStage],StageAllocation=FrozenCore.StageAllocation(c,b,b.QueueStage),UsedRiskBefore=b.UsedRisk,RiskBudget=b.RiskBudget,MarginAfter=Margin(bid),MarginLimitAfter=Math.Min(b.ReferenceBalance,Equity(bid))*c.MarginFraction*b.Scale,PreviousAccepted=b.Accepted.ToArray()});cash+=1000*b.Side*((bid+(b.Side==-1?spread:0)-b.Side*c.Slip)-actual)-c.CommissionPerSide;live--;entries-=actual;Cancel();return;}
  fillSum[b.QueueStage]+=actual;if(firstFill[b.QueueStage]==default)firstFill[b.QueueStage]=at;lastFill[b.QueueStage]=at;b.Accepted[b.QueueStage]++;b.UsedRisk+=ar;b.StageRisk[b.QueueStage]+=ar;b.QueueRemaining--;children++;
  if(b.QueueRemaining==0){b.NextStage=Math.Max(b.NextStage,b.QueueStage+1);b.QueueStage=-1;}
  maxMargin=Math.Max(maxMargin,Margin(bid)/Math.Max(.01,Math.Min(b.ReferenceBalance,Equity(bid)))*100);maxRisk=Math.Max(maxRisk,b.UsedRisk/b.ReferenceBalance*100);
 }
 void Close(DateTime at,double bid,string tag){if(basket==null)return;double exit=bid+(basket.Side==-1?spread:0)-basket.Side*c.Slip;cash+=1000*basket.Side*(live*exit-entries)-live*c.CommissionPerSide;ledger.Add(new(basket.AtUtc,at,before,cash,cash-before,basket.Side,basket.Accepted.Take(3).ToArray(),tag,quarantined,basket.InitialWanted,requested.ToArray(),fillSum.Select((v,i)=>basket.Accepted[i]>0?v/basket.Accepted[i]:0).ToArray(),firstFill.ToArray(),lastFill.ToArray(),basket.Entry,basket.Stop,basket.Target,basket.Scale,basket.RiskBudget/(before*c.RiskFraction*basket.Scale)));totalAdds+=basket.Accepted.Skip(1).Any(x=>x>0)?1:0;live=0;entries=0;closedPeak=Math.Max(closedPeak,cash);cdd=Math.Max(cdd,(closedPeak-cash)/closedPeak);}
 void Observe(double bid){double eq=Equity(bid);intrabarPeak=Math.Max(intrabarPeak,eq);intrabarDd=Math.Max(intrabarDd,(intrabarPeak-eq)/intrabarPeak);}
 void Tick(DateTime at,double bid){Observe(bid);TickInner(at,bid);Observe(bid);}
 void TickInner(DateTime at,double bid){Manage(at,bid);var b=basket;if(b==null)return;
  // Existing broker brackets are evaluated before the timer sends new children.
  double exitQuote=bid+(b.Side==-1?spread:0);
  if(live>0&&(b.Side*(exitQuote-b.Stop)<=0||b.Side*(exitQuote-b.Target)>=0)){bool stopHit=b.Side*(exitQuote-b.Stop)<=0;double ideal=stopHit?b.Stop:b.Target;double settle=preciseBracket?(stopHit&&at.Second==0?bid:ideal-(b.Side==-1?spread:0)):bid;Close(at,settle,stopHit?"STOP":"TARGET");Manage(at,bid);return;}
  if(!quarantined&&live>0&&b.QueueStage<0&&b.NextStage<c.Stages&&at<=b.AtUtc.AddMinutes(c.AddMinutes)){
   double quote=bid+(b.Side==1?spread:0),depth=b.Side*(b.Entry-quote)/Math.Abs(b.Entry-b.Stop);
   if(depth>=c.Depths[b.NextStage]){int stage=b.NextStage;b.QueueStage=stage;b.QueueRemaining=FrozenCore.StageWanted(c,b,stage,quote,Equity(bid),Equity(bid)-Margin(bid),1000*(bid+spread)/200,Margin(bid));if(stage>0)requested[stage]=b.QueueRemaining;b.NextStage++;if(b.QueueRemaining==0)b.QueueStage=-1;}
  }
  for(int j=0;j<rate&&basket!=null&&basket.QueueStage>=0&&basket.QueueRemaining>0;j++)Fill(at,bid);
  double eq=Equity(bid);intrabarPeak=Math.Max(intrabarPeak,eq);intrabarDd=Math.Max(intrabarDd,(intrabarPeak-eq)/intrabarPeak);
 }
 public void Bar(Candle b){if(basket==null)return;int side=basket.Side;double first=adverseFirst?(side==1?b.Low:b.High):(side==1?b.High:b.Low);double second=first==b.Low?b.High:b.Low;
  for(int sec=0;sec<60;sec++){double bid=sec<=20?b.Open+(first-b.Open)*sec/20d:sec<=40?first+(second-first)*(sec-20)/20d:second+(b.Close-second)*(sec-40)/19d;Tick(b.OpenUtc.AddSeconds(sec),bid);if(basket==null)break;}}
 public void Finish(Candle b){if(live>0)Close(b.OpenUtc.AddMinutes(1),b.Close,"END");Boundary(b.OpenUtc.AddMinutes(1),b.Close);}
 public object Report(int signals,int virtuals){double gains=ledger.Sum(x=>Math.Max(0,x.Pnl)),loss=ledger.Sum(x=>Math.Max(0,-x.Pnl));return new{ReferenceGap=referenceGap,ReferenceTime=referenceTime,PreciseBracket=preciseBracket,Rate=rate,InitialExpiry=initialExpiry,PaidAnchor=paidAnchor,ExtremaPeak=extremaPeak,Factor=factor,Path=adverseFirst?"ADVERSE_FIRST":"FAVORABLE_FIRST",EndingBalance=cash,ProfitFactor=loss>0?gains/loss:0,DD_M1_Boundary_Percent=dd*100,DD_Synthetic_Seconds_Percent=intrabarDd*100,DD_Closed_Percent=cdd*100,Baskets=ledger.Count,Wins=ledger.Count(x=>x.Pnl>0),WinRate=ledger.Count>0?100d*ledger.Count(x=>x.Pnl>0)/ledger.Count:0,BasketsPerMonth=ledger.Count/120d,Children=children,BasketsWithAdds=totalAdds,QueueMinuteCaps=queueCaps,BudgetBlocks=budgetBlocks,NoFunds=unfunded,MaxMarginPercent=maxMargin,MaxPlannedRiskPercent=maxRisk,Quarantined=quarantined,QuarantineReason=reason,Signals=signals,VirtualTrades=virtuals,Annual=ledger.GroupBy(x=>x.Entry.Year).Select(g=>new{Year=g.Key,Baskets=g.Count(),EndBalance=g.Last().After,Pnl=g.Sum(x=>x.Pnl)}).ToArray(),Ledger=ledger,Failures=failures};}
}
record Trade(DateTime Entry,DateTime Exit,double Before,double After,double Pnl,int Side,int[] StageQuantities,string Reason,bool Quarantined,int InitialWanted,int[] RequestedStages,double[] MeanFill,DateTime[] FirstFill,DateTime[] LastFill,double BasketAnchor,double Stop,double Target,double Scale,double Degear);
