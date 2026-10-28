using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Rizan.Portfolio.Eur;

public sealed class UtcDateTimeConverter : JsonConverter<DateTime>
{
    public override DateTime Read(ref Utf8JsonReader reader,Type type,JsonSerializerOptions options)
    {
        var text=reader.GetString() ?? throw new JsonException("UTC_TIMESTAMP_REQUIRED");
        if(!text.EndsWith("Z",StringComparison.OrdinalIgnoreCase) && !(text.Length>=6 && (text[^6]=='+' || text[^6]=='-')))throw new JsonException("TIMESTAMP_OFFSET_REQUIRED");
        return DateTimeOffset.Parse(text,System.Globalization.CultureInfo.InvariantCulture).UtcDateTime;
    }
    public override void Write(Utf8JsonWriter writer,DateTime value,JsonSerializerOptions options) => writer.WriteStringValue(DateTime.SpecifyKind(value,DateTimeKind.Utc));
}
public record Candle(DateTime OpenUtc, double Open, double High, double Low, double Close, int Count = 1)
{
    public DateTime End(int minutes) => OpenUtc.AddMinutes(minutes);
}
public record Signal(DateTime AtUtc, int Side, double Distance, double Atr = 0, double Anchor = 0);
public record Feature(DateTime AtUtc, double Open, double High, double Low, double Close,
    int Count, double Atr, double Body, double PriorHigh, double PriorLow, int Bias);
public record H1Record(DateTime AtUtc, double Ema, int Bias);
public sealed class VirtualTrade
{
    public DateTime AtUtc { get; set; }
    public DateTime LastUtc { get; set; }
    public double LastClose { get; set; }
    public int Side { get; set; }
    public double Entry { get; set; }
    public double Distance { get; set; }
}
public sealed class EurState
{
    public double Fast { get; set; }
    public double Slow { get; set; }
    public DateTime CursorUtc { get; set; }
    public DateTime LastExitUtc { get; set; }
    public List<H1Record> H1 { get; set; } = new();
    public VirtualTrade? Virtual { get; set; }
}
public record FrozenContract(string Symbol, string Hash, int Stages, double[] Depths,
    bool Confirmed, int AddMinutes, double InitialFraction, double WeightPower,
    double RiskFraction, double MarginFraction, double TargetR, int HoldMinutes,
    double Slip, double ChildUnits, double CommissionPerSide, int ReferenceLeverage)
{
    public static FrozenContract Eur => new("EURUSD", "4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976",
        3, new[] { 0d, .2, .4 }, false, 210, .4, 1.5, .2725, .5, 4, 240, .00001, 1000, .03, 200);
    public static FrozenContract Xau => new("XAUUSD", "7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf",
        4, new[] { 0d, .16111111111111112, .32222222222222224, .48333333333333334 },
        true, 45, 1, .5, .125, .5, 6.6, 480, .05, 1, .03, 100);
}
public sealed class Basket
{
    public DateTime AtUtc { get; set; }
    public DateTime ExitUtc { get; set; }
    public int Side { get; set; }
    public double Entry { get; set; }
    public double Stop { get; set; }
    public double OriginalDistance { get; set; }
    public double BestExit { get; set; }
    public bool BreakEvenArmed { get; set; }
    public double Target { get; set; }
    public double ReferenceBalance { get; set; }
    public double RiskBudget { get; set; }
    public double Scale { get; set; }
    public double RemainingStageBudget { get; set; }
    public double UsedRisk { get; set; }
    public double[] StageRisk { get; set; } = new double[4];
    public double InitialRiskAllocation { get; set; }
    public double MaxDepthPrevious { get; set; }
    public int InitialWanted { get; set; }
    public int NextStage { get; set; }
    public int QueueStage { get; set; } = -1;
    public int QueueRemaining { get; set; }
    public long Sequence { get; set; }
    public DateTime LastConfirmationUtc { get; set; }
    public int[] Accepted { get; set; } = new int[4];
}
public static class FrozenCore
{
    // cTrader LocalStorage: max 50 characters, Latin alphanumeric only.
    // Bridge identity retains the complete original account/symbol key.
    public static string CheckpointStorageKey(string identity) => "Rizan"+Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).Substring(0,40);
    public static bool Finite(double x) => !double.IsNaN(x) && !double.IsInfinity(x);
    public static bool ValidCheckpointPeak(double value) => Finite(value) && value>=0;
    public static DateTime Floor(DateTime at, int minutes) => new(at.Ticks - at.Ticks % TimeSpan.FromMinutes(minutes).Ticks, DateTimeKind.Utc);
    public static List<Candle> Aggregate(IEnumerable<Candle> bars, int minutes, DateTime available)
    {
        return bars.GroupBy(x => Floor(x.OpenUtc, minutes)).OrderBy(g => g.Key)
            .Where(g => g.Key.AddMinutes(minutes) <= available)
            .Select(g => { var rows = g.OrderBy(x => x.OpenUtc).ToArray(); return new Candle(g.Key,
                rows[0].Open, rows.Max(x => x.High), rows.Min(x => x.Low), rows[^1].Close, rows.Sum(x => x.Count)); }).ToList();
    }
    public static double[] Ema(double[] a, int span)
    {
        var r = new double[a.Length]; if (a.Length == 0) return r;
        r[0] = a[0]; var alpha = 2d / (span + 1);
        for (int i = 1; i < a.Length; i++) r[i] = alpha * a[i] + (1 - alpha) * r[i - 1];
        return r;
    }
    public static double[] Atr(IReadOnlyList<Candle> a)
    {
        var r = Enumerable.Repeat(double.NaN, a.Count).ToArray(); var tr = new double[a.Count];
        for (int i = 0; i < a.Count; i++)
        {
            tr[i] = a[i].High - a[i].Low;
            if (i > 0) tr[i] = Math.Max(tr[i], Math.Max(Math.Abs(a[i].High-a[i-1].Close), Math.Abs(a[i].Low-a[i-1].Close)));
            if (i >= 13) r[i] = tr.Skip(i-13).Take(14).Average();
        }
        return r;
    }
    public static int[] Strict(IReadOnlyList<Candle> a)
    {
        var closes = a.Select(x => x.Close).ToArray(); var e50=Ema(closes,50); var e200=Ema(closes,200); var r=new int[a.Count];
        for(int i=2;i<a.Count;i++) r[i]=closes[i]>e200[i] && e50[i]>=e50[i-2] ? 1 : closes[i]<e200[i] && e50[i]<=e50[i-2] ? -1 : 0;
        return r;
    }
    public static List<Feature> EurFeatures(IReadOnlyList<Candle> m1, DateTime available, EurState state)
    {
        var m15=Aggregate(m1,15,available); var h1=Aggregate(m1,60,available); var atr=Atr(m15);
        foreach(var h in h1)
        {
            var at=h.End(60); if(state.H1.Count>0 && at<=state.H1[^1].AtUtc) continue;
            double ema=state.H1.Count==0 ? h.Close : 2d/51*h.Close+49d/51*state.H1[^1].Ema;
            double slope=state.H1.Count>=3 ? ema-state.H1[^3].Ema : 0;
            int bias=h.Close>ema && slope>0 ? 1 : h.Close<ema && slope<0 ? -1 : 0;
            state.H1.Add(new(at,ema,bias));
        }
        if(state.H1.Count>512) state.H1=state.H1.TakeLast(512).ToList();
        var result=new List<Feature>();
        for(int i=0;i<m15.Count;i++)
        {
            var b=m15[i]; var at=b.End(15); var h=state.H1.LastOrDefault(x=>x.AtUtc<=at);
            var body=b.High>b.Low ? (b.Close-b.Open)/(b.High-b.Low) : double.NaN;
            double ph=i>=8 ? m15.Skip(i-8).Take(8).Max(x=>x.High) : double.NaN;
            double pl=i>=8 ? m15.Skip(i-8).Take(8).Min(x=>x.Low) : double.NaN;
            result.Add(new(at,b.Open,b.High,b.Low,b.Close,b.Count,atr[i],body,ph,pl,h?.Bias ?? 99));
        }
        return result;
    }
    public static Signal? EurSignal(Feature b)
    {
        if(b.AtUtc.Hour<7 || b.AtUtc.Hour>=12 || b.Count<12 || b.Bias!=0 || !Finite(b.Atr) || b.Atr<=0) return null;
        int side=b.Low<b.PriorLow && b.Close>b.PriorLow && b.Body>.2 ? 1 : b.High>b.PriorHigh && b.Close<b.PriorHigh && b.Body<-.2 ? -1 : 0;
        return side==0 ? null : new(b.AtUtc,side,Math.Max(.0005,Math.Min(.006,3*b.Atr)));
    }
    public static (double R,DateTime AtUtc)? VirtualStep(VirtualTrade p,Candle b)
    {
        double offset=p.Side==-1 ? .00012 : 0, exit; var at=b.OpenUtc;
        if(at>p.LastUtc && (at-p.LastUtc).TotalSeconds>300) exit=b.Open+offset-p.Side*.00001;
        else if(at>=p.AtUtc.AddMinutes(240) || at.Hour>=20 || at.Date!=p.AtUtc.Date)
        { exit=p.LastClose+offset-p.Side*.00001; at=p.LastUtc; }
        else
        {
            var stop=p.Entry-p.Side*p.Distance; var tp=p.Entry+p.Side*p.Distance*4;
            bool hs=p.Side==1 ? b.Low+offset<=stop : b.High+offset>=stop;
            bool ht=p.Side==1 ? b.High+offset>=tp : b.Low+offset<=tp;
            if(hs) exit=(p.Side==1 ? Math.Min(stop,b.Open+offset) : Math.Max(stop,b.Open+offset))-p.Side*.00001;
            else if(ht) exit=tp-p.Side*.00001;
            else { p.LastUtc=b.OpenUtc;p.LastClose=b.Close;return null; }
        }
        var result=(p.Side*(exit-p.Entry)/p.Distance,at);p.LastUtc=b.OpenUtc;p.LastClose=b.Close;return result;
    }
    public static void AdvanceVirtual(IReadOnlyList<Candle> m1,List<Feature> f,EurState state)
    {
        var byTime=f.ToDictionary(x=>x.AtUtc);
        foreach(var b in m1.Where(x=>x.OpenUtc>state.CursorUtc))
        {
            var candidate=byTime.TryGetValue(b.OpenUtc,out var feature) ? EurSignal(feature) : null;
            if(state.Virtual==null && candidate!=null && (state.LastExitUtc==default || b.OpenUtc>state.LastExitUtc))
                state.Virtual=new(){AtUtc=candidate.AtUtc,LastUtc=candidate.AtUtc,LastClose=b.Open,Side=candidate.Side,
                    Distance=candidate.Distance,Entry=b.Open+(candidate.Side==1 ? .00012 : 0)+candidate.Side*.00001};
            if(state.Virtual!=null)
            {
                var exit=VirtualStep(state.Virtual,b);
                if(exit!=null){state.Fast=2d/3*exit.Value.R+1d/3*state.Fast;state.Slow=2d/9*exit.Value.R+7d/9*state.Slow;state.LastExitUtc=exit.Value.AtUtc;state.Virtual=null;}
            }
            state.CursorUtc=b.OpenUtc;
        }
    }
    public static double EurScale(EurState state) => Math.Min(state.Fast<-.5 ? .1 : 1,state.Slow<-.05 ? .625 : 1);
    public static (bool Buy,bool Sell,double BuyAnchor,double SellAnchor)[] XauRaw(IReadOnlyList<Candle> m5,double[] atr,int[] h1,int[] m15)
    {
        int n=m5.Count;var fit=Enumerable.Repeat(double.NaN,n).ToArray();var std=(double[])fit.Clone();
        for(int i=47;i<n;i++)
        {
            double mean=0,weighted=0;for(int j=0;j<48;j++){var v=m5[i-47+j].Close;mean+=v/48;weighted+=j*v;}
            double slope=(weighted-48d*47/2*mean)/(48d*(48d*48-1)/12);
            fit[i]=mean+slope*47/2;double variance=0;for(int j=i-47;j<=i;j++) variance+=Math.Pow(m5[j].Close-mean,2)/48;std[i]=Math.Sqrt(variance);
        }
        int lc=-100,sc=-100;double lh=0,sl=0,la=0,sa=0;
        var r=new (bool Buy,bool Sell,double BuyAnchor,double SellAnchor)[n];
        for(int i=0;i<n;i++)
        {
            var b=m5[i];bool lg=false,sh=false;double anchor=double.NaN;
            if(Finite(atr[i]))
            {
                if(i-lc>0 && i-lc<=3 && b.Close>lh+.05*atr[i] && b.Close>b.Open){lg=true;anchor=la-.1*atr[i];lc=-100;}
                if(i-sc>0 && i-sc<=3 && b.Close<sl-.05*atr[i] && b.Close<b.Open){sh=true;anchor=sa+.1*atr[i];sc=-100;}
                if(i>=24)
                {
                    double pl=m5.Skip(i-24).Take(24).Min(x=>x.Low),ph=m5.Skip(i-24).Take(24).Max(x=>x.High);
                    if(b.Low<pl && b.Close>pl){lc=i;lh=b.High;la=b.Low;}
                    if(b.High>ph && b.Close<ph){sc=i;sl=b.Low;sa=b.High;}
                }
            }
            bool up=h1[i]==1 && m15[i]==1,down=h1[i]==-1 && m15[i]==-1;
            bool buy=i>=49 && b.Close>fit[i-1]-1.5*std[i-1] && m5[i-1].Close<=fit[i-2]-1.5*std[i-2] && b.Close>b.Open && up;
            bool other=i>=49 && b.Close<fit[i-1]+1.5*std[i-1] && m5[i-1].Close>=fit[i-2]+1.5*std[i-2] && b.Close<b.Open && down;
            double ba=i>=2 && Finite(atr[i]) ? m5.Skip(i-2).Take(3).Min(x=>x.Low)-.1*atr[i] : double.NaN;
            r[i]=(buy && !other,sh && down && !(lg && up),ba,anchor);
        }
        return r;
    }
    public static int[] AlignStrict(IReadOnlyList<Candle> input,int minutes,IReadOnlyList<Candle> target)
    {
        var strict=Strict(input);int j=-1;var r=new int[target.Count];
        for(int i=0;i<target.Count;i++){while(j+1<input.Count && input[j+1].End(minutes)<=target[i].End(5))j++;r[i]=j>=0 ? strict[j] : 0;}
        return r;
    }
    public static Signal? XauSignal(IReadOnlyList<Candle> m1,DateTime available)
    {
        var m5=Aggregate(m1,5,available);var m15=Aggregate(m1,15,available);var h1=Aggregate(m1,60,available);
        if(m5.Count<100 || m15.Count<200 || h1.Count<200) return null;
        var atr=Atr(m5);var raw=XauRaw(m5,atr,AlignStrict(h1,60,m5),AlignStrict(m15,15,m5));var last=raw[^1];var at=m5[^1].End(5);
        // Archived frozen-input adapter admits 12:00 <= UTC < 20:00.
        if(at.Hour<12 || at.Hour>=20 || at.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday) return null;
        int side=last.Sell ? -1 : last.Buy ? 1 : 0;
        return side==0 ? null : new(at,side,0,atr[^1],side==1 ? last.BuyAnchor : last.SellAnchor);
    }
    public static bool XauConfirmation(IReadOnlyList<Candle> m1,DateTime at,int side)
    {
        var m5=Aggregate(m1,5,at).Where(x=>x.Count==5).ToList();var m15=Aggregate(m1,15,at).Where(x=>x.Count==15).ToList();var h1=Aggregate(m1,60,at).Where(x=>x.Count==60).ToList();
        if(m5.Count<2 || m15.Count<2 || h1.Count<3) return false;
        var a=m5[^1];var b=m15[^1];if(a.End(5)!=at || (at-b.End(15)).TotalMinutes>15 || (at-h1[^1].End(60)).TotalMinutes>60) return false;
        var hb=Strict(h1)[^1];var mb=Strict(m15)[^1];
        return hb==side && mb==side && (side==1 ? a.Close>m5[^2].High && a.Close>a.Open && b.Close>m15[^2].High && b.Close>b.Open : a.Close<m5[^2].Low && a.Close<a.Open && b.Close<m15[^2].Low && b.Close<b.Open);
    }
    public static double ChildRisk(FrozenContract c,int side,double fill,double stop) => c.ChildUnits*(side*(fill-stop)+c.Slip)+2*c.CommissionPerSide;
    // Quotes reserve entry slippage; actual fills reserve exit slippage only.
    public static double PlannedChildRisk(FrozenContract c,int side,double quote,double stop) => ChildRisk(c,side,quote+side*c.Slip,stop);
    public static bool FillBudgetOk(FrozenContract c,Basket b,int stage,double quote,double equity,double freeMargin,double usedMargin,double marginChild,double spread)
    {
        if(stage<0 || stage>=c.Stages || !new[]{quote,equity,marginChild}.All(x=>Finite(x)&&x>0) || !new[]{freeMargin,usedMargin,spread}.All(x=>Finite(x)&&x>=0))return false;
        double risk=PlannedChildRisk(c,b.Side,quote,b.Stop),projectedEquity=equity-c.ChildUnits*(spread+c.Slip)-c.CommissionPerSide;
        double reference=Math.Min(b.ReferenceBalance,projectedEquity);
        return reference>0 && Finite(risk) && risk>0 && b.StageRisk[stage]+risk<=StageAllocation(c,b,stage)+1e-8 &&
            b.UsedRisk+risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8 &&
            usedMargin+marginChild<=reference*c.MarginFraction*b.Scale+1e-8 && freeMargin>=marginChild+c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide;
    }
    public static bool ActualFillBudgetOk(FrozenContract c,Basket b,int stage,double actualFill,double equity,double usedMargin)
    {
        if(stage<0 || stage>=c.Stages || !new[]{actualFill,equity}.All(x=>Finite(x)&&x>0) || !Finite(usedMargin) || usedMargin<0)return false;
        double risk=ChildRisk(c,b.Side,actualFill,b.Stop),reference=Math.Min(b.ReferenceBalance,equity);
        return Finite(risk) && risk>0 && b.StageRisk[stage]+risk<=StageAllocation(c,b,stage)+1e-8 &&
            b.UsedRisk+risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8 && usedMargin<=reference*c.MarginFraction*b.Scale+1e-8;
    }
    public static Basket? StartBasket(FrozenContract c,Signal signal,double entry,double balance,double equity,double freeMargin,double usedMargin,double marginChild,double scale,double peak)
    {
        if(!Finite(usedMargin) || !new[]{entry,balance,equity,marginChild,scale,peak}.All(x=>Finite(x)&&x>0) || !Finite(freeMargin) || freeMargin<0 || usedMargin<0) return null;
        double distance=c.Symbol=="XAUUSD" ? Math.Max(.5,Math.Max(2.65*signal.Atr,signal.Side*(entry-signal.Anchor))) : signal.Distance;
        if(!Finite(distance) || distance<=0 || signal.Side is not (1 or -1)) return null;
        double stop=entry-signal.Side*distance;double reference=Math.Min(balance,equity);
        double rc=reference*c.RiskFraction*scale;double mc=Math.Max(0,Math.Min(freeMargin,reference*c.MarginFraction*scale-usedMargin));
        double risk=c.Symbol=="EURUSD" ? PlannedChildRisk(c,signal.Side,entry,stop) : ChildRisk(c,signal.Side,entry,stop);
        int count=FloorCount(Math.Min(rc/risk,mc/marginChild));
        if(c.Symbol=="XAUUSD") count=Math.Min(count,Math.Max(1,FloorCount(balance/100)));
        double degear=c.Symbol=="EURUSD" && (peak-equity)/peak>=.25 ? .7 : 1;
        double budget=rc*degear;
        int initial=count>0 ? Math.Min(Math.Max(1,FloorCount(count*c.InitialFraction*degear)),FloorCount(budget/risk)) : 0;
        if(initial<1) return null;
        DateTime exit=signal.AtUtc.AddMinutes(c.HoldMinutes);var daily=signal.AtUtc.Date.AddHours(20).AddMinutes(c.Symbol=="XAUUSD" ? -1 : 0);if(exit>daily)exit=daily;
        return new(){AtUtc=signal.AtUtc,ExitUtc=exit,Side=signal.Side,Entry=entry,Stop=stop,OriginalDistance=distance,BestExit=entry-signal.Side*c.Slip,Target=entry+signal.Side*distance*c.TargetR,
            ReferenceBalance=reference,RiskBudget=budget,Scale=scale,RemainingStageBudget=Math.Max(0,budget-initial*risk),InitialRiskAllocation=initial*risk,InitialWanted=initial,NextStage=0,QueueStage=0,QueueRemaining=initial};
    }
    public static int StageWanted(FrozenContract c,Basket b,int stage,double fill,double equity,double freeMargin,double marginChild,double usedMargin)
    {
        if(stage<1 || stage>=c.Stages || !Finite(fill) || !Finite(equity) || equity<=0 || !Finite(marginChild) || marginChild<=0) return 0;
        double denom=Enumerable.Range(1,c.Stages-1).Sum(k=>Math.Pow(k+1,c.WeightPower));
        double share=StageAllocation(c,b,stage);var risk=c.Symbol=="EURUSD" ? PlannedChildRisk(c,b.Side,fill,b.Stop) : ChildRisk(c,b.Side,fill,b.Stop);
        if(risk<=0 || !Finite(risk)) return 0;
        double mb=Math.Max(0,Math.Min(freeMargin,Math.Min(b.ReferenceBalance,equity)*c.MarginFraction*b.Scale-usedMargin));
        return FloorCount(Math.Min(share/risk,Math.Min(Math.Max(0,b.RiskBudget-b.UsedRisk)/risk,mb/marginChild)));
    }
    public static double StageAllocation(FrozenContract c,Basket b,int stage) => stage==0 ? b.InitialRiskAllocation :
        b.RemainingStageBudget*Math.Pow(stage+1,c.WeightPower)/Enumerable.Range(1,c.Stages-1).Sum(k=>Math.Pow(k+1,c.WeightPower));
    public static int FloorCount(double value) => !Finite(value) || value<=0 ? 0 : (int)Math.Min(int.MaxValue,Math.Floor(value+1e-9));
}
