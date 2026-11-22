using cAlgo.API;
using Rizan.Portfolio;
static class AddonSettings { public static SeedConfig? Current; }
sealed class XauAddonController {
 readonly Host host;readonly SeedConfig? c;readonly double friction;readonly Action<HistoricalTrade> record;
 readonly Dictionary<DateTime,List<SeedPoint>> tape=new();readonly HashSet<long> recorded=new();
 static readonly double[] Stops={.35,.75,1.25},Targets={1.5,2,3,4},Risks={.02,.03,.04,.05,.06,.08},Thresholds={150,200,300,500};
 static readonly int[] Holds={30,60,120,240},Days={1,2,4},Universes={7,1,2,4,3,6};static readonly string[] Symbols={"EURUSD","XAUUSD","BTCUSD"};
 DateTime deadline,nextEntry,day;int count;double peak=100,dd;bool halted;int requests,unaffordable,postfillCloses,entries;DateTime? graduated;double graduationBalance;
 double Goal=>c!.HandoffEquity>100?c.HandoffEquity:Thresholds[c.Threshold];
 public bool Enabled=>c!=null;public bool GrowthEnabled=>c==null||graduated!=null&&!c.SeedOnly;
 public IEnumerable<DateTime> SignalTimes=>tape.Keys;public bool Active=>host.Positions.Any(p=>p.Label.StartsWith("RZADDON|"));
 public XauAddonController(Host host,double friction,Action<HistoricalTrade> record){this.host=host;this.friction=friction;this.record=record;c=AddonSettings.Current;if(c==null)return;
  string root=Environment.GetEnvironmentVariable("SEED_DATA")??throw new Exception("SEED_DATA_MISSING");
  for(int sid=0;sid<3;sid++){if((Universes[c.Universe]&(1<<sid))==0)continue;using var r=new BinaryReader(File.OpenRead(Path.Combine(root,$"base{c.Base}_symbol{sid}.bin")));if(r.BaseStream.Length%40!=0)throw new Exception("SEED_TAPE_LAYOUT");
   while(r.BaseStream.Position<r.BaseStream.Length){long minute=r.ReadInt64();r.ReadInt32();int symbol=r.ReadInt32(),side=r.ReadInt32(),trend=r.ReadInt32();double atr=r.ReadDouble(),anchor=r.ReadDouble();var at=DateTime.UnixEpoch.AddMinutes(minute);
    if((at.Year<Period.StartYear||at.Year>SeedSettings.LastYear)||(trend&(1<<c.Trend))==0||c.Direction==1&&side<0||c.Direction==2&&side>0||!InSession(at,sid,c.Session))continue;
    if(symbol!=sid||!double.IsFinite(atr)||atr<=0)throw new Exception("SEED_TAPE_INVALID");
    if(!tape.TryGetValue(at,out var list))tape[at]=list=new();list.Add(new(at,symbol,side,trend,atr,anchor));
   }
  }
  foreach(var a in tape.Values)a.Sort((a,b)=>a.Symbol.CompareTo(b.Symbol));
 }
 static bool InSession(DateTime at,int s,int z)=>z==0?at.Hour<20:z==1?s==0?at.Hour>=7&&at.Hour<12:s==1?at.Hour>=12&&at.Hour<17:at.Hour<20:z==2?at.Hour>=7&&at.Hour<12:at.Hour>=12&&at.Hour<17;
 public void Observe(){if(c==null||GrowthEnabled)return;peak=Math.Max(peak,host.Account.Equity);dd=Math.Max(dd,(peak-host.Account.Equity)/peak);}
 public void Manage(DateTime at){if(c==null||graduated!=null)return;
  if(Active&&at>=deadline)foreach(var p in host.Positions.Where(p=>p.Label.StartsWith("RZADDON|")).ToArray())if(!host.ClosePosition(p).IsSuccessful)throw new Exception("SEED_EXPIRY_CLOSE");
  foreach(var h in host.History.Where(h=>h.Label.StartsWith("RZADDON|")&&!recorded.Contains(h.PositionId)).ToArray()){
   recorded.Add(h.PositionId);record(h);nextEntry=h.ClosingTime.AddMinutes(h.NetProfit<0?60:5);
  }
  Observe();if(Active||graduated!=null)return;
  if(host.Account.Balance>=Goal&&host.Account.Equity>=Goal){graduated=at;graduationBalance=host.Account.Balance;return;}
  if(dd>=.6||host.Account.Balance<=0)halted=true;
 }
 static double Slip(int s,double p,double f)=>(s==0?.00001:s==1?.05:p*.0001)*f;
 static double Fee(int s,double p,double f)=>(s==0?.00003:s==1?.03:p*.0005)*f;
 public void Enter(DateTime at){if(c==null||GrowthEnabled||graduated!=null||halted||Active||host.Positions.Count!=0||at<nextEntry||!host.PortfolioReady||!host.NoForeignExposure()||!tape.TryGetValue(at,out var signals))return;
  if(at.Date!=day){day=at.Date;count=0;}if(count>=Days[c.Day])return;
  foreach(var p in signals){var sym=host.Symbols.GetSymbol(Symbols[p.Symbol]);if(!sym.MarketHours.IsOpened(host.Server.TimeInUtc))continue;int sign=p.Side;double bid=sym.Bid,spread=sym.Ask-bid,entry=(sign>0?sym.Ask:bid)+sign*Slip(p.Symbol,bid,friction),anchor=p.Anchor+(sign<0?spread:0);
   if(sign*(bid-p.Anchor)<=0)continue;
   double distance=Math.Max(Math.Max(Stops[c.Sl]*p.Atr,sign*(entry-anchor)),p.Symbol==0?.00005:p.Symbol==1?.5:1),stop=entry-sign*distance,target=entry+sign*Targets[c.Tp]*distance;
   double ef=Fee(p.Symbol,entry,friction),xf=Fee(p.Symbol,target,friction),funding=p.Symbol==2?entry*.0003*Holds[c.Hold]/1440d*friction:0;
   double perRisk=distance+ef+xf+Slip(p.Symbol,bid,friction)+funding,entryCost=spread+Slip(p.Symbol,bid,friction)+ef;
   if((Targets[c.Tp]*distance-ef-xf-Slip(p.Symbol,bid,friction))/perRisk<.8)continue;
   double reference=Math.Min(host.Account.Balance,host.Account.Equity),risk=Risks[c.Risk],marginUnit=sym.GetEstimatedMargin(sign>0?TradeType.Buy:TradeType.Sell,sym.VolumeInUnitsMin)/sym.VolumeInUnitsMin;
   double units=sym.NormalizeVolumeInUnits(Math.Min(sym.VolumeInUnitsMax,Math.Min(reference*risk/(perRisk+risk*entryCost),reference*.5/(marginUnit+.5*entryCost))),RoundingMode.Down);
   if(units<sym.VolumeInUnitsMin){unaffordable++;continue;}
   deadline=new[]{at.AddMinutes(Holds[c.Hold]),at.Date.AddHours(20)}.Min();requests++;
   var result=host.Send(sign>0?TradeType.Buy:TradeType.Sell,sym.Name,units,$"RZADDON|{at.Ticks}|0|{requests}",distance/sym.PipSize,Targets[c.Tp]*distance/sym.PipSize,"annual seed research");
   count++;if(!result.IsSuccessful||result.Position==null){nextEntry=host.Server.TimeInUtc.AddMinutes(5);return;}
   var pos=result.Position;entries++;
   if(!host.Protect(pos,stop,target,ProtectionType.Absolute).IsSuccessful)throw new Exception("SEED_PROTECTION_FAILED");
   double actualRisk=pos.VolumeInUnits*(Math.Max(0,sign*(pos.EntryPrice-stop))+Fee(p.Symbol,pos.EntryPrice,friction)+Fee(p.Symbol,stop,friction)+Slip(p.Symbol,bid,friction)+funding);
   if(actualRisk>reference*risk+1e-8||host.Account.Margin>host.Account.Equity*.5+1e-8||sign*(target-(sign>0?sym.Bid:sym.Ask))<=0||sign*((sign>0?sym.Bid:sym.Ask)-stop)<=0){postfillCloses++;if(!host.ClosePosition(pos).IsSuccessful)throw new Exception("SEED_POSTFILL_CLOSE_FAILED");}
   Manage(host.Server.TimeInUtc);return;
  }
 }
 public object Audit()=>new{Enabled,c,HandoffEquity=c==null?0:Goal,Entries=entries,Requests=requests,UnaffordableMinLot=unaffordable,PostfillBudgetCloses=postfillCloses,GraduatedUtc=graduated,GraduationBalance=graduationBalance,GrowthEnabled,Halted=halted,SeedMaxEquityDDPct=dd*100,SignalTimes=tape.Count};
}
