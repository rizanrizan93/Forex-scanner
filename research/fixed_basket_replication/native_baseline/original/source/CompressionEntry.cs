using System;
using System.Collections.Generic;
using System.Linq;
using X=Rizan.Portfolio.Xau;
namespace Rizan.Portfolio;

// Frozen asymmetric compression. Admission/news gates run in the XAU engine.
public static class CompressionEntry
{
    public static X.Signal? Extra(IReadOnlyList<X.Candle> m1,DateTime available)
    {
        if(!EligibleTime(available))return null;
        var m=X.FrozenCore.Aggregate(m1,5,available);var h=X.FrozenCore.Aggregate(m1,60,available);
        if(m.Count<15||h.Count<200||m[^1].End(5)!=available)return null;
        return Evaluate(m,X.FrozenCore.Atr(m),m.Count-1,X.FrozenCore.Strict(h)[^1],available,h[^1].Count);
    }
    public static bool EligibleTime(DateTime at)=>at.Minute%5==0&&at.Second==0&&at.Ticks%TimeSpan.TicksPerSecond==0&&at.Hour>=12&&at.Hour<17&&at.Year>=2019&&at.DayOfWeek is not(DayOfWeek.Saturday or DayOfWeek.Sunday);
    public static X.Signal? Evaluate(IReadOnlyList<X.Candle> m,double[] atr,int i,int bias,DateTime available,int h1Count=60)
    {
        if(!EligibleTime(available)||i<14||i>=m.Count||atr.Length!=m.Count||m[i].End(5)!=available)return null;
        double a=atr[i];
        if(!double.IsFinite(a)||a<=0||!double.IsFinite(atr[i-1])||atr[i-1]<=0)return null;
        double mean=m.Skip(i-6).Take(6).Average(b=>b.High-b.Low);
        double lo=m.Skip(i-6).Take(6).Min(b=>b.Low),hi=m.Skip(i-6).Take(6).Max(b=>b.High);var b=m[i];
        if(b.High<=b.Low)return null;double body=(b.Close-b.Open)/(b.High-b.Low);
        bool buy=mean<.7*atr[i-1]&&b.Close>hi&&body>.5&&bias==1;
        bool sell=b.Count==5&&h1Count>=48&&mean<.8*atr[i-1]&&b.Close<lo&&body<=-.7&&bias==-1;
        int side=buy?1:sell?-1:0;
        return side==0?null:new(available,side,0,a,side>0?lo-.1*a:hi+.1*a);
    }
    public static X.Signal? Signal(IReadOnlyList<X.Candle> m1,DateTime at)
    {
        // Original R3 timestamp has priority. Never reuse a completed M5 signal on later M1 opens.
        if(!EligibleTime(at))return null;
        var original=X.FrozenCore.XauSignal(m1,at);
        return original?.AtUtc==at?original:Extra(m1,at);
    }
}

