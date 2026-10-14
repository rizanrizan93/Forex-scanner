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
foreach(int leverage in new[]{30,100,200})foreach(double factor in new[]{1d,2d})foreach(bool adverseFirst in new[]{true,false})
{
 var engine=new Engine(factor,adverseFirst,leverage);var state=new EurState();var start=new DateTime(2016,1,1,0,0,0,DateTimeKind.Utc);int signals=0,virtuals=0;
 // Fresh virtual feedback at start; indicators warm up from earliest available 2016 data. No 2015 data available.
 for(int i=0;i<raw.Count;i++){
   var b=raw[i];if(b.OpenUtc<start)continue;
   // At this minute's opening quote, previous M1 is now closed and causal.
   if(i>0&&state.Virtual!=null){var vx=FrozenCore.VirtualStep(state.Virtual,raw[i-1]);if(vx!=null){state.Fast=2d/3*vx.Value.R+1d/3*state.Fast;state.Slow=2d/9*vx.Value.R+7d/9*state.Slow;state.LastExitUtc=vx.Value.AtUtc;state.Virtual=null;virtuals++;}}
   engine.Boundary(b.OpenUtc,b.Open);
   Signal? s=features.TryGetValue(b.OpenUtc,out var f)?FrozenCore.EurSignal(f):null;
   if(s!=null){signals++;engine.Start(s,b.Open,FrozenCore.EurScale(state));if(state.Virtual==null&&(state.LastExitUtc==default||b.OpenUtc>state.LastExitUtc))state.Virtual=new(){AtUtc=s.AtUtc,LastUtc=s.AtUtc,LastClose=b.Open,Side=s.Side,Distance=s.Distance,Entry=b.Open+(s.Side==1?.00012:0)+s.Side*.00001};}
   engine.Bar(b);
 }
 engine.Finish(raw[^1]);var report=engine.Report(signals,virtuals);reports.Add(report);
 Console.WriteLine(JsonSerializer.Serialize(report));
}
File.WriteAllText(args[1],JsonSerializer.Serialize(new{Scope="C# source replay with synthetic 1-second OHLC paths; not cTrader native/tick backtest",Rows=raw.Count,FeatureParity=compared,Reports=reports},new JsonSerializerOptions{WriteIndented=true}));

sealed class Engine(double factor,bool adverseFirst,int leverage)
{
 readonly FrozenContract c=FrozenContract.Eur with{Slip=.00001*factor,CommissionPerSide=FrozenContract.Eur.CommissionPerSide*factor};readonly double spread=.00001*factor;
 double cash=100,peak=100,dd=0,closedPeak=100,cdd=0,intrabarPeak=100,intrabarDd=0,before;
 Basket? basket;int live;double entries;DateTime lastExit;bool quarantined;string reason="";
 int orders,zoneCancels;int queueCaps,budgetBlocks,totalSignals,unfunded,children,totalAdds;double maxMargin,maxRisk;readonly List<Trade> ledger=new();readonly int[] requested=new int[3];readonly double[] fillSum=new double[3];readonly DateTime[] firstFill=new DateTime[3],lastFill=new DateTime[3];readonly List<object> failures=new();
 public double Equity(double bid)=>cash+(basket==null?0:1000*basket.Side*(live*(bid+(basket.Side==-1?spread:0))-entries));
 double Margin(double bid)=>live*1000*(bid+spread)/leverage;
 public void Boundary(DateTime at,double bid){Observe(bid);Manage(at,bid);Observe(bid);var eq=Equity(bid);peak=Math.Max(peak,eq);dd=Math.Max(dd,(peak-eq)/peak);}
 void Manage(DateTime at,double bid){if(basket==null)return;if(at>=basket.ExitUtc&&live>0)Close(at,bid,"TIME");if(basket!=null&&live==0&&(basket.Accepted.Sum()>0||basket.QueueStage<0||at>=basket.ExitUtc)){lastExit=FrozenCore.Floor(at,1);basket=null;}}
 public void Start(Signal s,double bid,double scale){totalSignals++;if(basket!=null||quarantined||s.AtUtc<=lastExit)return;double quote=bid+(s.Side==1?spread:0);basket=EurBatchExecution.Start(c,s,quote,cash,cash,cash,0,1000*quote/leverage,scale,peak);if(basket==null){unfunded++;return;}before=cash;live=0;entries=0;Array.Clear(requested);Array.Clear(fillSum);Array.Clear(firstFill);Array.Clear(lastFill);requested[0]=basket.InitialWanted;}
 void Cancel(){if(basket==null)return;basket.QueueRemaining=0;basket.QueueStage=-1;}
 void Fill(DateTime at,double bid){var b=basket;if(b==null||b.QueueStage<0||b.QueueRemaining<=0)return;
  if(at>=b.ExitUtc||(b.QueueStage==0&&at>=b.AtUtc.AddMinutes(1))||(b.QueueStage>0&&at>b.AtUtc.AddMinutes(c.AddMinutes))){if(b.QueueStage==0&&b.QueueRemaining>0)queueCaps++;Cancel();return;}
  double quote=bid+(b.Side==1?spread:0),eq=Equity(bid),used=Margin(bid);int stage=b.QueueStage;bool first=b.Accepted.Sum()==0;
  if(!EurBatchExecution.InZone(c,b,stage,quote)||b.Side*(quote-b.Stop)<=.00001||b.Side*(b.Target-quote)<=.00001){Cancel();zoneCancels++;return;}
  int qty=EurBatchExecution.Count(c,b,stage,quote,eq,eq-used,used,spread,Math.Min(EurBatchExecution.MaxChildren,b.QueueRemaining),first,q=>q*1000*(bid+spread)/leverage);
  if(qty<1){Cancel();budgetBlocks++;return;}
  double actual=quote+b.Side*c.Slip;cash-=qty*c.CommissionPerSide;live+=qty;entries+=qty*actual;
  if(first)EurBatchExecution.AnchorFirstFill(c,b,actual);
  if(!EurBatchExecution.ActualOk(c,b,stage,actual,Equity(bid),Margin(bid),qty)){failures.Add(new{AtUtc=at,Stage=stage,Quantity=qty});cash+=qty*(1000*b.Side*((bid+(b.Side==-1?spread:0)-b.Side*c.Slip)-actual)-c.CommissionPerSide);live-=qty;entries-=qty*actual;Cancel();return;}
  fillSum[stage]+=qty*actual;if(firstFill[stage]==default)firstFill[stage]=at;lastFill[stage]=at;
  EurBatchExecution.Accept(c,b,stage,actual,qty);children+=qty;orders++;
  maxMargin=Math.Max(maxMargin,Margin(bid)/Math.Max(.01,Math.Min(b.ReferenceBalance,Equity(bid)))*100);maxRisk=Math.Max(maxRisk,b.UsedRisk/b.ReferenceBalance*100);
 }
 void Close(DateTime at,double bid,string tag){if(basket==null)return;double exit=bid+(basket.Side==-1?spread:0)-basket.Side*c.Slip;cash+=1000*basket.Side*(live*exit-entries)-live*c.CommissionPerSide;ledger.Add(new(basket.AtUtc,at,before,cash,cash-before,basket.Side,basket.Accepted.Take(3).ToArray(),tag,quarantined,basket.InitialWanted,requested.ToArray(),fillSum.Select((v,i)=>basket.Accepted[i]>0?v/basket.Accepted[i]:0).ToArray(),firstFill.ToArray(),lastFill.ToArray(),basket.Entry,basket.Stop,basket.Target,basket.Scale,basket.RiskBudget/(before*c.RiskFraction*basket.Scale)));totalAdds+=basket.Accepted.Skip(1).Any(x=>x>0)?1:0;live=0;entries=0;closedPeak=Math.Max(closedPeak,cash);cdd=Math.Max(cdd,(closedPeak-cash)/closedPeak);}
 void Observe(double bid){double eq=Equity(bid);intrabarPeak=Math.Max(intrabarPeak,eq);intrabarDd=Math.Max(intrabarDd,(intrabarPeak-eq)/intrabarPeak);}
 void Tick(DateTime at,double bid){Observe(bid);TickInner(at,bid);Observe(bid);}
 void TickInner(DateTime at,double bid){Manage(at,bid);var b=basket;if(b==null)return;
  // Existing broker brackets are evaluated before the timer sends new children.
  double exitQuote=bid+(b.Side==-1?spread:0);
  if(live>0&&(b.Side*(exitQuote-b.Stop)<=0||b.Side*(exitQuote-b.Target)>=0)){Close(at,bid,b.Side*(exitQuote-b.Stop)<=0?"STOP":"TARGET");Manage(at,bid);return;}
  if(!quarantined&&live>0&&b.QueueStage<0&&b.NextStage<c.Stages&&at<=b.AtUtc.AddMinutes(c.AddMinutes)){
   double quote=bid+(b.Side==1?spread:0),depth=b.Side*(b.Entry-quote)/Math.Abs(b.Entry-b.Stop);
   if(depth>=c.Depths[b.NextStage]){int stage=b.NextStage;b.QueueStage=stage;b.QueueRemaining=FrozenCore.StageWanted(c,b,stage,quote,Equity(bid),Equity(bid)-Margin(bid),1000*(bid+spread)/leverage,Margin(bid));if(stage>0)requested[stage]=b.QueueRemaining;b.NextStage++;if(b.QueueRemaining==0)b.QueueStage=-1;}
  }
  Fill(at,bid);
  double eq=Equity(bid);intrabarPeak=Math.Max(intrabarPeak,eq);intrabarDd=Math.Max(intrabarDd,(intrabarPeak-eq)/intrabarPeak);
 }
 public void Bar(Candle b){if(basket==null)return;int side=basket.Side;double first=adverseFirst?(side==1?b.Low:b.High):(side==1?b.High:b.Low);double second=first==b.Low?b.High:b.Low;
  for(int sec=0;sec<60;sec++){double bid=sec<=20?b.Open+(first-b.Open)*sec/20d:sec<=40?first+(second-first)*(sec-20)/20d:second+(b.Close-second)*(sec-40)/19d;Tick(b.OpenUtc.AddSeconds(sec),bid);if(basket==null)break;}}
 public void Finish(Candle b){if(live>0)Close(b.OpenUtc.AddMinutes(1),b.Close,"END");Boundary(b.OpenUtc.AddMinutes(1),b.Close);}
 public object Report(int signals,int virtuals){double gains=ledger.Sum(x=>Math.Max(0,x.Pnl)),loss=ledger.Sum(x=>Math.Max(0,-x.Pnl));return new{Name=EurBatchExecution.Model,Leverage=leverage,BatchSize=EurBatchExecution.MaxChildren,Orders=orders,ZoneCancels=zoneCancels,Rate=1,Factor=factor,Path=adverseFirst?"ADVERSE_FIRST":"FAVORABLE_FIRST",EndingBalance=cash,ProfitFactor=loss>0?gains/loss:0,DD_M1_Boundary_Percent=dd*100,DD_Synthetic_Seconds_Percent=intrabarDd*100,DD_Closed_Percent=cdd*100,Baskets=ledger.Count,Wins=ledger.Count(x=>x.Pnl>0),WinRate=ledger.Count>0?100d*ledger.Count(x=>x.Pnl>0)/ledger.Count:0,BasketsPerMonth=ledger.Count/120d,Children=children,BasketsWithAdds=totalAdds,QueueMinuteCaps=queueCaps,BudgetBlocks=budgetBlocks,NoFunds=unfunded,MaxMarginPercent=maxMargin,MaxPlannedRiskPercent=maxRisk,Quarantined=quarantined,QuarantineReason=reason,Signals=signals,VirtualTrades=virtuals,Annual=ledger.GroupBy(x=>x.Entry.Year).Select(g=>new{Year=g.Key,Baskets=g.Count(),EndBalance=g.Last().After,Pnl=g.Sum(x=>x.Pnl)}).ToArray(),Ledger=ledger,Failures=failures};}
}
record Trade(DateTime Entry,DateTime Exit,double Before,double After,double Pnl,int Side,int[] StageQuantities,string Reason,bool Quarantined,int InitialWanted,int[] RequestedStages,double[] MeanFill,DateTime[] FirstFill,DateTime[] LastFill,double BasketAnchor,double Stop,double Target,double Scale,double Degear);
