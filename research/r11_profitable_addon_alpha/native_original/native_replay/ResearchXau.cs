using System.Text.Json;
using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;

// Market-driver tape adapter only. Trade calculations use linked production source.
static class ResearchXau {
 static HashSet<DateTime> added=new(), original=new();
 static Dictionary<DateTime,int> directions=new();
 public static bool IsAdded(DateTime at)=>added.Contains(at);
 public static bool IsOriginal(DateTime at)=>original.Contains(at);
 public static X.FrozenContract Contract(X.FrozenContract c,DateTime at)=>EntryFamilies.XauContract(c,IsAdded(at)?EntryFamilies.XauDisplacement:EntryFamilies.Incumbent,directions.GetValueOrDefault(at));
 public static Tape Attach(Tape primary,Tape extra,string path){
  original=new(primary.Signals.Keys);var combined=new Dictionary<DateTime,SignalPoint>(primary.Signals);
  foreach(var p in extra.Signals)if(!combined.ContainsKey(p.Key)){
   var s=((X.Signal)p.Value.Signal) with {Origin=EntryFamilies.XauDisplacement};
   combined[p.Key]=new(s,p.Value.Fast,p.Value.Slow);added.Add(p.Key);directions[p.Key]=s.Side;
  }
  return new(combined,primary.Confirmations);
 }
 public static Tape Generate(Data data){
  var h=BtcCore.Aggregate(data.Rows.Select(r=>new BtcBar(r.At,r.Open,r.High,r.Low,r.Close)).ToList(),60);
  var f=EntryFamilies.Features(h);var sig=new Dictionary<DateTime,SignalPoint>();
  for(int i=100;i<f.Count;i++){var at=f[i].Bar.At.AddHours(1);var s=EntryFamilies.XauEvaluate(f,i,at);if(s!=null)sig[at]=new(s);}
  return new(sig,new());
 }
 public static void Handoff(DateTime at,DateTime entry){}
}
