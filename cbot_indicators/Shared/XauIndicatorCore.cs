using System;
using System.Collections.Generic;
using System.Linq;
using X = Rizan.Portfolio.Xau;

namespace Rizan.Indicators;

// Display projection only. FrozenCore is linked unchanged, never a Robot.
public sealed record XauIndicatorFrame(DateTime AtUtc, double Open, double High, double Low,
    double Close, double Atr, int H1Bias, int M15Bias, bool Warm, bool SessionOpen,
    double BuyTriggerNext, bool BuyPriorEligible, double SellSweepNext,
    double? SellTriggerEstimate, DateTime? SellSetupAtUtc, DateTime? SellSetupExpiresUtc,
    int SignalSide, double SignalAnchor)
{
    static double? Number(double n) => X.FrozenCore.Finite(n) ? n : null;
    public object Display() => new {
        at_utc=AtUtc, open=Open, high=High, low=Low, close=Close, atr=Number(Atr),
        h1_bias=H1Bias, m15_bias=M15Bias, warm=Warm, session_open=SessionOpen,
        buy_trigger_next=Number(BuyTriggerNext), buy_prior_eligible=BuyPriorEligible,
        sell_sweep_next=Number(SellSweepNext), sell_trigger_estimate=SellTriggerEstimate,
        sell_setup_at=SellSetupAtUtc, sell_setup_expires=SellSetupExpiresUtc,
        signal_side=SignalSide, signal_anchor=Number(SignalAnchor),
        execution_authority=false, execution_influence=false
    };
}

public static class XauIndicatorCore
{
    public const string ContractHash="44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c";
    public static bool Session(DateTime at) => at.Hour>=12 && at.Hour<17 &&
        at.DayOfWeek!=DayOfWeek.Saturday && at.DayOfWeek!=DayOfWeek.Sunday;

    public static List<XauIndicatorFrame> Build(IReadOnlyList<X.Candle> input,DateTime available)
    {
        var m1=input.Where(b=>b.End(1)<=available).OrderBy(b=>b.OpenUtc).ToList();
        var m5=X.FrozenCore.Aggregate(m1,5,available);
        var m15=X.FrozenCore.Aggregate(m1,15,available);
        var h1=X.FrozenCore.Aggregate(m1,60,available);
        var atr=X.FrozenCore.Atr(m5);
        var hb=X.FrozenCore.AlignStrict(h1,60,m5);var mb=X.FrozenCore.AlignStrict(m15,15,m5);
        var raw=X.FrozenCore.XauRaw(m5,atr,hb,mb);
        var band=Enumerable.Repeat(double.NaN,m5.Count).ToArray();
        for(int i=47;i<m5.Count;i++)
        {
            double mean=0,weighted=0;
            for(int j=0;j<48;j++){double v=m5[i-47+j].Close;mean+=v/48;weighted+=j*v;}
            double slope=(weighted-48d*47/2*mean)/(48d*(48d*48-1)/12);
            double fit=mean+slope*47/2;double variance=0;
            for(int j=i-47;j<=i;j++)variance+=Math.Pow(m5[j].Close-mean,2)/48;
            band[i]=fit-1.5*Math.Sqrt(variance);
        }
        int sc=-100,hc=0,mc=0;double sweepLow=0;var result=new List<XauIndicatorFrame>();
        for(int i=0;i<m5.Count;i++)
        {
            var b=m5[i];var at=b.End(5);
            while(hc<h1.Count && h1[hc].End(60)<=at)hc++;
            while(mc<m15.Count && m15[mc].End(15)<=at)mc++;
            // Same consumption/replacement order as XauRaw. This state is preparation only.
            if(X.FrozenCore.Finite(atr[i]))
            {
                if(i-sc>0 && i-sc<=3 && b.Close<sweepLow-.05*atr[i] && b.Close<b.Open)sc=-100;
                if(i>=24 && b.High>m5.Skip(i-24).Take(24).Max(x=>x.High) &&
                   b.Close<m5.Skip(i-24).Take(24).Max(x=>x.High)){sc=i;sweepLow=b.Low;}
            }
            bool pending=sc>=0 && i-sc<=2 && X.FrozenCore.Finite(atr[i]);
            bool warm=i+1>=100 && hc>=200 && mc>=200;
            int side=warm && Session(at) ? (raw[i].Sell ? -1 : raw[i].Buy ? 1 : 0) : 0;
            result.Add(new(at,b.Open,b.High,b.Low,b.Close,atr[i],hb[i],mb[i],warm,Session(at),
                band[i],i>=1 && b.Close<=band[i-1],
                i>=23 ? m5.Skip(i-23).Take(24).Max(x=>x.High) : double.NaN,
                pending ? sweepLow-.05*atr[i] : null,
                pending ? m5[sc].End(5) : null,pending ? m5[sc].End(5).AddMinutes(15) : null,
                side,side==1 ? raw[i].BuyAnchor : side==-1 ? raw[i].SellAnchor : double.NaN));
        }
        return result;
    }

    public static (double Entry,double Stop,double Target) Reference(XauIndicatorFrame f,double bid,double ask)
    {
        if(f.SignalSide==0 || !new[]{bid,ask,f.Atr,f.SignalAnchor}.All(X.FrozenCore.Finite) ||
            bid<=0 || ask<bid)throw new ArgumentException("INVALID_TECHNICAL_REFERENCE");
        int side=f.SignalSide;double spread=ask-bid;
        double entry=(side==1 ? ask : bid)+side*.10;
        double anchor=f.SignalAnchor+(side==-1 ? spread : 0);
        double distance=Math.Max(.5,Math.Max(X.FrozenContract.Xau.StopAtrMultiplier*f.Atr,side*(entry-anchor)));
        return(entry,entry-side*distance,entry+side*X.FrozenContract.Xau.TargetR*distance);
    }
}
