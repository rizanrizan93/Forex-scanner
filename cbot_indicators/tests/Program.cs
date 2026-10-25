using System.Globalization;
using System.Text.Json;
using Rizan.Indicators;
using X=Rizan.Portfolio.Xau;

void Check(bool ok,string name){if(!ok)throw new Exception(name);}
var culture=CultureInfo.InvariantCulture;
var bars=File.ReadLines(args[0]).Skip(1).Select(line=>{
    var v=line.Split(',');return new X.Candle(DateTimeOffset.Parse(v[0],culture).UtcDateTime,
        double.Parse(v[1],culture),double.Parse(v[2],culture),double.Parse(v[3],culture),double.Parse(v[4],culture));
}).ToList();
var available=bars[^1].End(1);var frames=XauIndicatorCore.Build(bars,available);
var eligible=frames.Where(f=>f.Warm).ToList();
Check(eligible.Count>0,"warmup fixture");
var samples=eligible.Where((_,i)=>i%Math.Max(1,eligible.Count/12)==0)
    .Concat(eligible.Where(f=>f.SignalSide!=0).Take(24)).Append(eligible[^1]).DistinctBy(f=>f.AtUtc).ToList();
int confirmed=0,buy=0,sell=0;
foreach(var f in samples)
{
    var prefix=bars.Where(b=>b.End(1)<=f.AtUtc).ToList();
    var native=X.FrozenCore.XauSignal(prefix,f.AtUtc);
    Check((native?.Side??0)==f.SignalSide,"native signal side at "+f.AtUtc);
    if(native!=null){confirmed++;if(native.Side==1)buy++;else sell++;
        Check(Math.Abs(native.Anchor-f.SignalAnchor)<1e-8 && Math.Abs(native.Atr-f.Atr)<1e-8,"native geometry");}
    if(f.SignalSide!=0)
    {
        double bid=f.Close,ask=bid+.2;
        var plan=XauIndicatorCore.Reference(f,bid,ask);
        var contract=X.FrozenContract.Xau;
        double expected=(f.SignalSide==1 ? ask : bid)+f.SignalSide*.10;
        double anchor=f.SignalAnchor+(f.SignalSide==-1 ? ask-bid : 0);
        double distance=Math.Max(.5,Math.Max(contract.StopAtrMultiplier*f.Atr,f.SignalSide*(expected-anchor)));
        Check(Math.Abs(plan.Entry-expected)<1e-8 && Math.Abs(plan.Stop-(expected-f.SignalSide*distance))<1e-8 &&
              Math.Abs(plan.Target-(expected+f.SignalSide*contract.TargetR*distance))<1e-8,"original fixed exit reference");
        Check(contract.TargetR==5.5 && contract.HoldMinutes==480,"original exit contract");
    }
    // Full-history evaluation cannot change the already-known prefix result.
    var replay=XauIndicatorCore.Build(bars,f.AtUtc).Last();
    Check(JsonSerializer.Serialize(replay.Display())==JsonSerializer.Serialize(f.Display()),"future bars affect frame");
    // Independent next-candle channel threshold from LAST 48 closed M5 bars.
    var m5=X.FrozenCore.Aggregate(prefix,5,f.AtUtc);var win=m5.TakeLast(48).Select(b=>b.Close).ToArray();
    double mean=win.Average(),weighted=win.Select((x,i)=>i*x).Sum();
    double slope=(weighted-48d*47/2*mean)/(48d*(48d*48-1)/12);
    double band=mean+slope*47/2-1.5*Math.Sqrt(win.Average(x=>Math.Pow(x-mean,2)));
    Check(Math.Abs(f.BuyTriggerNext-band)<1e-8,"next-bar threshold");
}
Check(confirmed>0,"fixture must include confirmed signals");
Console.WriteLine(JsonSerializer.Serialize(new{status="PASS",frames=frames.Count,warm_frames=eligible.Count,
    native_prefix_comparisons=samples.Count,confirmed,buy,sell,
    checks=new[]{"native signal/ATR/anchor parity","prefix invariance","next-candle band", "original fixed exit reference"}}));
