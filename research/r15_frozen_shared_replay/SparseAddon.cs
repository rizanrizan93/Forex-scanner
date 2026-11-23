using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;

record SparsePoint(DateTime At,int Candidate,int Side,double Atr,double Anchor,double StopMult,double TargetR,int Hold,double MaxSpreadAtr,bool OriginalFlagAllowed);
sealed class SparseAddon {
 readonly Host host;readonly double cost;readonly Action<HistoricalTrade> record;
 readonly Dictionary<DateTime,List<SparsePoint>> tape=new();readonly HashSet<long> seen=new();
 readonly Dictionary<string,int> rejects=new();readonly Dictionary<int,DateTime> deadlines=new();
 readonly List<object> decisions=new();readonly string mode;DateTime nextEntry;int entries,requests,closed,observedCoreConflicts,historyCursor;
 public bool Active=>host.Positions.Any(p=>p.Label.StartsWith("RZSPARSE|"));
 public IEnumerable<DateTime> SignalTimes=>tape.Keys;
 void Reject(string why)=>rejects[why]=rejects.GetValueOrDefault(why)+1;
 public SparseAddon(Host h,double fee,Action<HistoricalTrade> callback){
  host=h;cost=fee;record=callback;mode=Environment.GetEnvironmentVariable("R15_ADDON_MODE")??"off";
  if(host.Account.IsLive)throw new Exception("R15_RESEARCH_ONLY_LIVE_FORBIDDEN");
  if(mode=="off")return;
  string root=Environment.GetEnvironmentVariable("R15_SIGNAL_DIR")??throw new Exception("R15_SIGNAL_DIR_MISSING");
  int[] ids=mode=="pds"?new[]{1736543}:mode=="breakout"?new[]{27615}:mode=="both"?new[]{1736543,27615}:throw new Exception("INVALID_R15_MODE");
  foreach(int id in ids)foreach(var p in JsonSerializer.Deserialize<SparsePoint[]>(File.ReadAllText(Path.Combine(root,$"candidate_{id}.json")))!){
   if(p.At.Second!=0||p.At.Minute%(id==1736543?30:5)!=0||p.Side is not(1 or -1)||p.Atr<=0||!double.IsFinite(p.Atr)||!double.IsFinite(p.Anchor))throw new Exception("INVALID_SPARSE_TAPE");
   if(!tape.TryGetValue(p.At,out var points))tape[p.At]=points=new();points.Add(p);
  }
 }
 public void ObserveCore(DateTime at,string symbol,bool hasSignal){if(Active&&hasSignal&&symbol=="XAUUSD")observedCoreConflicts++;}
 public void Manage(DateTime at){
  if(mode=="off")return;
  foreach(var p in host.Positions.Where(p=>p.Label.StartsWith("RZSPARSE|")&&deadlines.GetValueOrDefault(p.Id,DateTime.MaxValue)<=at).ToArray())
   if(!host.ClosePosition(p).IsSuccessful)throw new Exception("R15_TIME_CLOSE_FAILED");
  while(historyCursor<host.History.Count){
   var h=host.History[historyCursor++];if(!h.Label.StartsWith("RZSPARSE|")||!seen.Add(h.PositionId))continue;
   record(h);closed++;nextEntry=h.ClosingTime.AddMinutes(5);
  }
 }
 public void Enter(DateTime at,bool growth,bool queuesEmpty){
  if(!tape.TryGetValue(at,out var signals))return;
  if(!growth){Reject("bootstrap_not_graduated");return;}
  if(Active||host.Positions.Count!=0||!queuesEmpty){Reject("core_position_or_queue_priority");return;}
  if(host.Server.TimeInUtc>at.AddSeconds(60)){Reject("signal_expired");return;}
  if(host.Server.TimeInUtc<nextEntry){Reject("post_settlement_embargo");return;}
  if(!host.PortfolioReady||!host.NoForeignExposure()){Reject("portfolio_not_ready");return;}
  foreach(var p in signals){
   if(!p.OriginalFlagAllowed){Reject("original_xau_direction_flag");continue;}
   var sym=host.Symbols.GetSymbol("XAUUSD");if(!sym.MarketHours.IsOpened(host.Server.TimeInUtc)){Reject("market_closed");continue;}
   double reference=Math.Min(host.Account.Balance,host.Account.Equity),spread=sym.Ask-sym.Bid;
   if(reference<125){Reject("growth_cash_below_125");continue;}
   if(spread<0||spread>p.MaxSpreadAtr*p.Atr){Reject("observed_spread_gate");continue;}
   double entry=(p.Side==1?sym.Ask:sym.Bid)+p.Side*.05*cost;
   double distance=Math.Max(p.StopMult*p.Atr,p.Side*(entry-p.Anchor));
   if(!double.IsFinite(distance)||distance<=0){Reject("invalid_stop");continue;}
   double stop=entry-p.Side*distance,target=entry+p.Side*p.TargetR*distance;
   // No enlargement of the Frozen shared caps. Reserve unallocated room for core.
   double budget=Math.Min(reference*.03,Math.Max(0,host.SharedRiskBudget(reference)-host.GuardOpenRisk()-reference*.04));
   double marginBudget=Math.Min(reference*.4,Math.Max(0,host.SharedMarginBudget(reference)-host.Account.Margin-reference*.10));
   double unitRisk=distance+.16*cost,entryCost=spread+.08*cost;
   double marginUnit=sym.GetEstimatedMargin(p.Side==1?TradeType.Buy:TradeType.Sell,sym.VolumeInUnitsMin)/sym.VolumeInUnitsMin;
   double units=sym.NormalizeVolumeInUnits(Math.Min(sym.VolumeInUnitsMax,Math.Min(
      budget/(unitRisk+.03*entryCost),marginBudget/(marginUnit+.4*entryCost))),RoundingMode.Down);
   if(budget<=0||marginBudget<=0){Reject("shared_guard_or_reserve");continue;}
   if(units<sym.VolumeInUnitsMin){Reject("unaffordable_minimum_volume");continue;}
   requests++;
   var fill=host.Send(p.Side==1?TradeType.Buy:TradeType.Sell,"XAUUSD",units,$"RZSPARSE|{at.Ticks}|{p.Candidate}|{requests}",distance/sym.PipSize,p.TargetR*distance/sym.PipSize,"R15 shared-account research");
   if(!fill.IsSuccessful||fill.Position==null){Reject("broker_fill_rejected");continue;}
   var pos=fill.Position;entries++;deadlines[pos.Id]=new[]{at.AddMinutes(p.Hold),at.Date.AddHours(20)}.Min();
   if(!host.Protect(pos,stop,target,ProtectionType.Absolute).IsSuccessful)throw new Exception("R15_PROTECTION_FAILED");
   double after=Math.Min(host.Account.Balance,host.Account.Equity);
   double actualRisk=pos.VolumeInUnits*(Math.Max(0,p.Side*(pos.EntryPrice-stop))+.16*cost);
   if(actualRisk>reference*.03+1e-8||host.GuardOpenRisk()>host.SharedRiskBudget(after)+1e-8||host.Account.Margin>Math.Min(after*.4,host.SharedMarginBudget(after))+1e-8||p.Side*((p.Side==1?sym.Bid:sym.Ask)-stop)<=0||p.Side*(target-(p.Side==1?sym.Bid:sym.Ask))<=0){
    Reject("postfill_risk_margin_or_bracket");if(!host.ClosePosition(pos).IsSuccessful)throw new Exception("R15_POSTFILL_CLOSE_FAILED");
   }
   decisions.Add(new{At=at,Now=host.Server.TimeInUtc,p.Candidate,p.Side,Reference=reference,Units=units,Budget=budget,MarginBudget=marginBudget,ActualRisk=actualRisk,Entry=pos.EntryPrice,Stop=stop,Target=target});
   Manage(host.Server.TimeInUtc);return;
  }
 }
 public object Audit()=>new{Mode=mode,Entries=entries,Requests=requests,Settlements=closed,SignalTimes=tape.Count,Rejects=rejects,ObservedXauCoreSignalsDuringAddon=observedCoreConflicts,
  RiskFraction=.03,UnallocatedRiskReserve=.04,UnallocatedMarginReserve=.10,ProductionEnabled=false,Decisions=decisions};
}
