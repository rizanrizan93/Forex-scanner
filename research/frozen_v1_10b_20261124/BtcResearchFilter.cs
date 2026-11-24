using Rizan.Portfolio;
static class BtcResearchFilter {
 static Dictionary<DateTime,EntryFamilies.Feature> h=new(),q=new();
 internal static double RsiMax=100,EfficiencyMin=.2,SellRsiMin=30;
 internal static int BuyRejected,SellRejected;
 internal static void Initialize(Data d){
  var rows=d.Rows.Select(r=>new BtcBar(r.At,r.Open,r.High,r.Low,r.Close)).ToList();
  h=EntryFamilies.Features(BtcCore.Aggregate(rows,60)).ToDictionary(f=>f.Bar.At.AddHours(1));
  q=EntryFamilies.Features(BtcCore.Aggregate(rows,240)).ToDictionary(f=>f.Bar.At.AddHours(4));
 }
 internal static void Configure(double r,double e,double s){RsiMax=r;EfficiencyMin=e;SellRsiMin=s;BuyRejected=SellRejected=0;}
 internal static bool Allow(BtcSignal s){
  if(RsiMax>=100&&EfficiencyMin<=.2&&SellRsiMin<=30)return true;
  bool ok;
  if(s.Side>0){ok=q.TryGetValue(new DateTime(s.At.Ticks-s.At.Ticks%TimeSpan.FromHours(4).Ticks,DateTimeKind.Utc),out var f)&&f.Rsi<=RsiMax&&f.Efficiency>=EfficiencyMin;if(!ok)BuyRejected++;}
  else {ok=h.TryGetValue(s.At,out var f)&&f.Rsi>=SellRsiMin;if(!ok)SellRejected++;}
  return ok;
 }
 internal static void SelfTest(){
  var start=new DateTime(2019,1,1,0,0,0,DateTimeKind.Utc);
  Row Make(int i){double v=4000+i*.03+15*Math.Sin(i/80d);return new(start.AddMinutes(i),v,v+2,v-2,v+.1,0,0,false,false);}
  var rows=Enumerable.Range(0,24000).Select(Make).ToArray();var cut=start.AddMinutes(24000);
  Initialize(new Data{Rows=rows});var old=q.Where(p=>p.Key<=cut).ToDictionary(p=>p.Key,p=>(p.Value.Rsi,p.Value.Efficiency));
  Initialize(new Data{Rows=rows.Concat(Enumerable.Range(24000,1440).Select(i=>Make(i) with{Close=1000000+i})).ToArray()});
  foreach(var p in old){var f=q[p.Key];if(f.Rsi!=p.Value.Rsi||!(f.Efficiency==p.Value.Efficiency||double.IsNaN(f.Efficiency)&&double.IsNaN(p.Value.Efficiency)))throw new Exception("FUTURE_DATA_CHANGED_CLOSED_FEATURE");}
  Configure(100,.2,30);if(!Allow(new BtcSignal(start.AddYears(-1),1,1,1)))throw new Exception("DEFAULT_CONTROL_FILTER_CHANGED");
  Configure(80,.2,30);if(Allow(new BtcSignal(start.AddYears(-1),1,1,1)))throw new Exception("MISSING_FEATURE_MUST_BLOCK");
  Console.WriteLine("PASS BTC closed-feature causality, default-control identity, missing-feature rejection; real_orders=0");
 }
}
