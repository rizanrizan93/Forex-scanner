using cAlgo.API;
// Observational only. Called at the same native Observe marks as equity DD.
sealed class ReplayDiagnostics {
 readonly double[] levels={125,250,500,1000,10000,100000,1000000,10000000,100000000,1000000000,10000000000};
 readonly Dictionary<double,object> milestones=new();
 double peak=100,maxDD,minimumMarginLevel=double.PositiveInfinity;
 DateTime? peakAt,ddPeakAt,ddTroughAt,ddRecoveredAt;DateTime last;
 TimeSpan longestUnderwater=TimeSpan.Zero;int maxPositions,maxSymbols;
 bool equityBelowMargin;double maxGrossNotional;
 public void Observe(DateTime at,double balance,double equity,double margin,IReadOnlyList<Position> positions){
  last=at;if(peakAt==null)peakAt=at;
  foreach(double level in levels)if(!milestones.ContainsKey(level)&&balance>=level&&equity>=level)milestones[level]=new{At=at,Balance=balance,Equity=equity,MaxFloatingDDPct=100*maxDD};
  double dd=(peak-equity)/peak;
  if(dd>maxDD){maxDD=dd;ddPeakAt=peakAt;ddTroughAt=at;ddRecoveredAt=null;}
  if(equity>=peak){if(ddRecoveredAt==null&&ddPeakAt==peakAt&&ddTroughAt!=null)ddRecoveredAt=at;peak=equity;peakAt=at;}
  else if(at-peakAt.Value>longestUnderwater)longestUnderwater=at-peakAt.Value;
  if(margin>0){minimumMarginLevel=Math.Min(minimumMarginLevel,100*equity/margin);if(equity<margin)equityBelowMargin=true;}
  maxPositions=Math.Max(maxPositions,positions.Count);maxSymbols=Math.Max(maxSymbols,positions.Select(p=>p.SymbolName).Distinct().Count());
  maxGrossNotional=Math.Max(maxGrossNotional,positions.Sum(p=>p.VolumeInUnits*p.EntryPrice));
 }
 public object Result()=>new{Milestones=milestones,PeakEquity=peak,PeakEquityAt=peakAt,MaximumFloatingDDPct=100*maxDD,MaxDDPeakAt=ddPeakAt,MaxDDTroughAt=ddTroughAt,MaxDDRecoveredAt=ddRecoveredAt,MaxDDRecoveryDays=ddRecoveredAt!=null&&ddPeakAt!=null?(double?)(ddRecoveredAt.Value-ddPeakAt.Value).TotalDays:null,LongestObservedUnderwaterDays=longestUnderwater.TotalDays,UnrecoveredAtEnd=last>peakAt,MinimumMarginLevelPct=double.IsFinite(minimumMarginLevel)?(double?)minimumMarginLevel:null,EquityBelowRequiredMarginObserved=equityBelowMargin,MaximumSimultaneousPositions=maxPositions,MaximumSimultaneousSymbols=maxSymbols,MaximumGrossEntryNotionalUSD=maxGrossNotional,StopOutPolicyImplemented=false};
}
