using System;
using System.Collections.Generic;
using System.Linq;
using X=Rizan.Portfolio.Xau;
namespace Rizan.Portfolio;

// Computed exclusively from completed bars. No historical timestamp membership,
// environment-selected strategies, broker requests or mutable global signal state.
public static class EntryFamilies
{
    public const string Incumbent="INCUMBENT", XauDisplacement="XAU_H1_DISPLACEMENT", BtcBreak40="BTC_H4_BREAK40_ALL";
    public static bool ValidOrigin(string origin)=>origin==Incumbent||origin==XauDisplacement;
    public static bool ValidBtcOrigin(string origin)=>origin==Incumbent||origin==BtcBreak40;
    public static bool IsAdded(string origin)=>origin==XauDisplacement||origin==BtcBreak40;
    public static X.FrozenContract XauContract(X.FrozenContract c,string origin,int side=0)=>origin==XauDisplacement
        ?c with{RiskFraction=Math.Min(c.RiskFraction,side==1?.05:.19965),MarginFraction=Math.Min(c.MarginFraction,.5),TargetR=side==1?12:2,StopAtrMultiplier=side==1?1.25:1.5,HoldMinutes=480,Stages=1,Depths=new[]{0d,-1d,-2d},InitialFraction=1}:c;
    public sealed record Feature(BtcBar Bar,double Atr,double E20,double E80,double Rsi,double Efficiency);
    public static List<Feature> Features(IReadOnlyList<BtcBar> bars)
    {
        var f=new List<Feature>();double atr=0,up=0,dn=0,fast=0,slow=0;
        for(int i=0;i<bars.Count;i++)
        {
            var b=bars[i];double pc=i>0?bars[i-1].Close:b.Open;
            double tr=Math.Max(b.High-b.Low,Math.Max(Math.Abs(b.High-pc),Math.Abs(b.Low-pc)));
            atr=i==0?tr:atr+(tr-atr)/14;
            up=i==0?0:up+(Math.Max(0,b.Close-pc)-up)/14;
            dn=i==0?0:dn+(Math.Max(0,pc-b.Close)-dn)/14;
            fast=i==0?b.Close:fast+2d/21*(b.Close-fast);slow=i==0?b.Close:slow+2d/81*(b.Close-slow);
            double travel=0;if(i>=20)for(int j=i-19;j<=i;j++)travel+=Math.Abs(bars[j].Close-bars[j-1].Close);
            double er=i>=20&&travel>0?Math.Abs(b.Close-bars[i-20].Close)/travel:double.NaN;
            f.Add(new(b,atr,fast,slow,dn>0?100-100/(1+up/dn):100,er));
        }
        return f;
    }
    public static bool Complete(IReadOnlyList<Feature> f,int i,int lookback,int minutes)
    {
        if(i<lookback||i>=f.Count)return false;
        for(int j=i-lookback;j<=i;j++)if(f[j].Bar.Count!=minutes||(j>i-lookback&&f[j].Bar.At-f[j-1].Bar.At!=TimeSpan.FromMinutes(minutes)))return false;
        return true;
    }
    public static X.Signal? XauEvaluate(IReadOnlyList<Feature> f,int i,DateTime at)
    {
        if(i<100||i>=f.Count||at!=f[i].Bar.At.AddHours(1)||at.Minute!=0||at.Second!=0||at.Year<2019||at.Hour<5||at.Hour>=17||at.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday||!Complete(f,i,10,60))return null;
        var v=f[i];var b=v.Bar;
        if(!double.IsFinite(v.Atr)||v.Atr<=0||!double.IsFinite(v.Efficiency)||v.Efficiency<.2||b.High<=b.Low)return null;
        double mean=0;for(int j=i-10;j<i;j++)mean+=Math.Abs(f[j].Bar.Close-f[j].Bar.Open)/10;
        if(Math.Abs(b.Close-b.Open)<1.5*mean)return null;
        bool buy=(b.Close-b.Open)/v.Atr>=1&&v.Rsi>=35&&v.Rsi<=85&&b.Close>v.E80&&v.E20>v.E80&&b.Close>f[i-1].Bar.High&&(b.Close-b.Low)/(b.High-b.Low)>=.55;
        bool sell=(b.Open-b.Close)/v.Atr>=1&&v.Rsi>=15&&v.Rsi<=65&&b.Close<f[i-1].Bar.Low&&(b.High-b.Close)/(b.High-b.Low)>=.55;
        int side=buy?1:sell?-1:0;
        return side==0?null:new(at,side,0,v.Atr,b.Close,XauDisplacement);
    }
    public static X.Signal? XauSignal(IReadOnlyList<X.Candle> m1,DateTime available)
    {
        if(available.Minute!=0||available.Hour<5||available.Hour>=17)return null;
        var h=X.FrozenCore.Aggregate(m1,60,available).Select(b=>new BtcBar(b.OpenUtc,b.Open,b.High,b.Low,b.Close,b.Count)).ToList();
        var f=Features(h);return XauEvaluate(f,f.Count-1,available);
    }
    public static BtcSignal? BtcEvaluate(IReadOnlyList<Feature> f,int i)
    {
        if(i<100||i>=f.Count||!Complete(f,i,40,240))return null;
        var v=f[i];var b=v.Bar;var at=b.At.AddHours(4);
        if(at.Year<2019||at.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday||v.Atr<=0||!double.IsFinite(v.Efficiency)||v.Efficiency<.2||b.Close<=v.E80||v.E20<=v.E80||v.Rsi<50||v.Rsi>75||b.High<=b.Low||(b.Close-b.Open)/v.Atr<.75||(b.Close-b.Low)/(b.High-b.Low)<.75)return null;
        double high=double.NegativeInfinity;for(int j=i-40;j<i;j++)high=Math.Max(high,f[j].Bar.High);
        return b.Close>high+.05*v.Atr?new(at,1,v.Atr,b.Close,BtcBreak40):null;
    }
    public static void MergeBtc(Dictionary<DateTime,BtcSignal> original,IReadOnlyList<BtcBar> fourHourly)
    {
        var f=Features(fourHourly);for(int i=100;i<f.Count;i++){var s=BtcEvaluate(f,i);if(s!=null)original.TryAdd(s.At,s);}
    }
}

