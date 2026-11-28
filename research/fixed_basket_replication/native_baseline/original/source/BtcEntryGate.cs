using System;
using System.Collections.Generic;
namespace Rizan.Portfolio;

// Apply after baseline conflict resolution. Only closed source bars are read.
public static class BtcEntryGate
{
    public static double Efficiency(IReadOnlyList<BtcBar> bars,int i)
    {
        if(i<20||i>=bars.Count)return double.NaN;
        double total=0;
        for(int j=i-19;j<=i;j++)total+=Math.Abs(bars[j].Close-bars[j-1].Close);
        return total>0?Math.Abs(bars[i].Close-bars[i-20].Close)/total:double.NaN;
    }
    public static bool BuyAllowed(double efficiency,int count)=>double.IsFinite(efficiency)&&efficiency>=.2&&count>=192;
    public static bool SellAllowed(double rsi,int count)=>double.IsFinite(rsi)&&rsi>=30&&count>=48;
    public static Dictionary<DateTime,BtcSignal> Apply(Dictionary<DateTime,BtcSignal> original,IReadOnlyList<BtcBar> h,IReadOnlyList<BtcBar> q)
    {
        var hi=new Dictionary<DateTime,(double Rsi,int Count)>();double up=0,dn=0;
        for(int i=0;i<h.Count;i++){
            if(i>0){double change=h[i].Close-h[i-1].Close;up+=(Math.Max(change,0)-up)/14;dn+=(Math.Max(-change,0)-dn)/14;}
            hi[h[i].At.AddHours(1)]=(dn>0?100-100/(1+up/dn):100,h[i].Count);
        }
        var qi=new Dictionary<DateTime,int>();for(int i=0;i<q.Count;i++)qi[q[i].At.AddHours(4)]=i;
        var result=new Dictionary<DateTime,BtcSignal>();
        foreach(var pair in original){var s=pair.Value;
            if(s.Side>0){if(qi.TryGetValue(s.At,out int i)&&BuyAllowed(Efficiency(q,i),q[i].Count))result.Add(pair.Key,s);}
            else if(hi.TryGetValue(s.At,out var f)&&SellAllowed(f.Rsi,f.Count))result.Add(pair.Key,s);
        }
        return result;
    }
}

