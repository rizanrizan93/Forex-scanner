using System;
using System.Collections.Generic;
using System.Linq;
namespace Rizan.Portfolio;
public record BtcBar(DateTime At,double Open,double High,double Low,double Close,int Count=1);
public record BtcSignal(DateTime At,int Side,double Atr,double Reference);
public static class BtcCore
{
    sealed record Feature(BtcBar Bar,double Atr,double E20,double E80,double Rsi);
    static List<Feature> Features(IEnumerable<BtcBar> input)
    {
        var a=new List<Feature>();double atr=0,up=0,dn=0;
        foreach(var b in input){double pc=a.Count>0?a[^1].Bar.Close:b.Open;
            double tr=Math.Max(b.High-b.Low,Math.Max(Math.Abs(b.High-pc),Math.Abs(b.Low-pc)));
            atr=a.Count==0?tr:atr+(tr-atr)/14;
            up=a.Count==0?0:up+(Math.Max(0,b.Close-pc)-up)/14;dn=a.Count==0?0:dn+(Math.Max(0,pc-b.Close)-dn)/14;
            a.Add(new(b,atr,a.Count==0?b.Close:a[^1].E20+2d/21*(b.Close-a[^1].E20),a.Count==0?b.Close:a[^1].E80+2d/81*(b.Close-a[^1].E80),dn>0?100-100/(1+up/dn):100));
        }return a;
    }
    public static List<BtcBar> Aggregate(IEnumerable<BtcBar> input,int width)
    {
        var result=new List<BtcBar>();long ticks=TimeSpan.FromMinutes(width).Ticks;
        foreach(var b in input){var at=new DateTime(b.At.Ticks-b.At.Ticks%ticks,DateTimeKind.Utc);
            if(result.Count==0||result[^1].At!=at)result.Add(b with{At=at});
            else {var x=result[^1];result[^1]=x with{High=Math.Max(x.High,b.High),Low=Math.Min(x.Low,b.Low),Close=b.Close,Count=x.Count+b.Count};}
        }return result;
    }
    public static Dictionary<DateTime,BtcSignal> Signals(IReadOnlyList<BtcBar> hourly,IReadOnlyList<BtcBar> fourHourly)
    {
        var h=Features(hourly);var q=Features(fourHourly);var result=new Dictionary<DateTime,BtcSignal>();var conflicts=new HashSet<DateTime>();
        void Add(BtcSignal s){if(conflicts.Contains(s.At))return;if(result.ContainsKey(s.At)){result.Remove(s.At);conflicts.Add(s.At);}else result[s.At]=s;}
        int Trend(Feature f)=>f.Bar.Close>f.E80&&f.E20>f.E80?1:f.Bar.Close<f.E80&&f.E20<f.E80?-1:0;
        // Indicator seed begins at 2019-01-01, matching the frozen research input.
        for(int i=100;i<q.Count;i++){var f=q[i];var at=f.Bar.At.AddHours(4);if(f.Bar.Count<192||at.Hour>=8||Trend(f)!=1||f.Atr<=0)continue;
            if((f.Bar.Close-f.Bar.Open)/f.Atr>1.4&&f.Bar.Close>q[i-1].Bar.High)Add(new(at,1,f.Atr,f.Bar.Close));}
        int qi=-1;
        for(int i=100;i<h.Count;i++){var f=h[i];var at=f.Bar.At.AddHours(1);while(qi+1<q.Count&&q[qi+1].Bar.At.AddHours(4)<=at)qi++;
            if(qi<12||Trend(q[qi])!=-1||f.Bar.Count<48||f.Atr<=0)continue;
            double lo=double.PositiveInfinity,hi=double.NegativeInfinity,range=0;for(int j=i-16;j<i;j++){lo=Math.Min(lo,h[j].Bar.Low);hi=Math.Max(hi,h[j].Bar.High);}for(int j=i-4;j<i;j++)range+=h[j].Bar.High-h[j].Bar.Low;
            // Reject a simultaneous upward breakout exactly as the original ternary rule.
            if(range/4>=h[i-1].Atr*.7||f.Bar.Close>hi+.1*f.Atr||f.Bar.Close>=lo-.1*f.Atr)continue;
            double ratio=f.Atr/Math.Max(h[i-20].Atr,1e-12);if(Math.Abs(f.Bar.Close-f.Bar.Open)>2.5*f.Atr||f.Rsi<25||ratio<.6||ratio>1.8)continue;
            Add(new(at,-1,f.Atr,f.Bar.Close));
        }return result;
    }
}
