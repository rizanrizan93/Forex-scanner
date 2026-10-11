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
var state=new EurState();var sigs=new List<object>();var exits=new List<object>();
for(int i=0;i<raw.Count;i++){
 var b=raw[i];
 if(i>0&&state.Virtual!=null){var vx=FrozenCore.VirtualStep(state.Virtual,raw[i-1]);if(vx!=null){exits.Add(new{Entry=state.Virtual.AtUtc,Exit=vx.Value.AtUtc,R=vx.Value.R});state.Fast=2d/3*vx.Value.R+1d/3*state.Fast;state.Slow=2d/9*vx.Value.R+7d/9*state.Slow;state.LastExitUtc=vx.Value.AtUtc;state.Virtual=null;}}
 Signal? sig=features.TryGetValue(b.OpenUtc,out var f)?FrozenCore.EurSignal(f):null;
 if(sig!=null){bool eligible=state.Virtual==null&&(state.LastExitUtc==default||b.OpenUtc>state.LastExitUtc);sigs.Add(new{At=sig.AtUtc,Side=sig.Side,Distance=sig.Distance,Scale=FrozenCore.EurScale(state),Fast=state.Fast,Slow=state.Slow,VirtualEligible=eligible});if(eligible)state.Virtual=new(){AtUtc=sig.AtUtc,LastUtc=sig.AtUtc,LastClose=b.Open,Side=sig.Side,Distance=sig.Distance,Entry=b.Open+(sig.Side==1?.00012:0)+sig.Side*.00001};}
}
File.WriteAllText(args[1],JsonSerializer.Serialize(new{Signals=sigs,Virtuals=exits},new JsonSerializerOptions{WriteIndented=true}));
