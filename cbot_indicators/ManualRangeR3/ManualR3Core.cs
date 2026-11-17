using System;
using System.Collections.Generic;
using System.Linq;

namespace Rizan.ManualR3;
public record Candle(DateTime At,double O,double H,double L,double C);
public record News(string Event,DateTime At);
public record Signal(int Side,DateTime TouchAt,DateTime At,double Level,double Atr,double RangeAdx);
public record Plan(string Id,int Side,double Entry,double Stop,double Target,double MaxFill,DateTime Created,DateTime TimeExit);
public record Snapshot(string State,int Bias,double Adx,double Atr,double Lower,double Upper,Signal? Signal,Plan? Plan);

public sealed class ManualR3Core
{
    public const string Version="RIZAN_MANUAL_RANGE_RECLAIM_R3_V1";
    readonly List<Candle> m1,m5,m15,h1;
    readonly double[] atr5,atr15,ema15,adx1,slope1;
    public IReadOnlyList<Signal> Signals {get;}
    public Plan? FrozenPlan {get;private set;}
    public ManualR3Core(IEnumerable<Candle> input,DateTime asOf)
    {
        m1=input.Where(x=>x.At.AddMinutes(1)<=asOf).OrderBy(x=>x.At).ToList();
        m5=Aggregate(m1,5,asOf);m15=Aggregate(m1,15,asOf);h1=Aggregate(m1,60,asOf);
        atr5=Atr(m5);atr15=Atr(m15);ema15=Ewm(m15.Select(x=>x.C).ToArray(),2.0/21,20);
        adx1=Adx(h1);var eh=Ewm(h1.Select(x=>x.C).ToArray(),2.0/21,20);
        slope1=eh.Select((x,i)=>i>=3&&Finite(x)&&Finite(eh[i-3])?(double)Math.Sign(x-eh[i-3]):0).ToArray();
        Signals=FindSignals();
    }
    public void RestorePlan(Plan? p)=>FrozenPlan=p;
    public static bool Finite(double x)=>!double.IsNaN(x)&&!double.IsInfinity(x);
    public static DateTime Floor(DateTime t,int minutes)=>new(t.Ticks-t.Ticks%(TimeSpan.TicksPerMinute*minutes),DateTimeKind.Utc);
    public static List<Candle> Aggregate(IEnumerable<Candle> input,int minutes,DateTime asOf)=>input.GroupBy(x=>Floor(x.At,minutes)).OrderBy(g=>g.Key)
        .Where(g=>g.Key.AddMinutes(minutes)<=asOf).Select(g=>new Candle(g.Key,g.First().O,g.Max(x=>x.H),g.Min(x=>x.L),g.Last().C)).ToList();
    public static double[] Ewm(double[] x,double alpha,int minimum)
    {
        var a=new double[x.Length];double value=double.NaN;int count=0;
        for(int i=0;i<x.Length;i++){
            if(Finite(x[i])){value=Finite(value)?(1-alpha)*value+alpha*x[i]:x[i];count++;}
            a[i]=count>=minimum?value:double.NaN;
        }return a;
    }
    public static double[] Atr(IReadOnlyList<Candle> b)
    {
        var tr=new double[b.Count];for(int i=0;i<b.Count;i++)tr[i]=i==0?b[i].H-b[i].L:
            Math.Max(b[i].H-b[i].L,Math.Max(Math.Abs(b[i].H-b[i-1].C),Math.Abs(b[i].L-b[i-1].C)));
        return Ewm(tr,1.0/14,14);
    }
    public static double[] Adx(IReadOnlyList<Candle> b)
    {
        var a=Atr(b);var pos=new double[b.Count];var neg=new double[b.Count];
        for(int i=1;i<b.Count;i++){
            double u=b[i].H-b[i-1].H,v=b[i-1].L-b[i].L;
            pos[i]=u>v&&u>0?u:0;neg[i]=v>u&&v>0?v:0;
        }
        var up=Ewm(pos,1.0/14,14);var dn=Ewm(neg,1.0/14,14);var dx=new double[b.Count];
        for(int i=0;i<b.Count;i++){
            if(!Finite(a[i])||a[i]<=0){dx[i]=double.NaN;continue;}
            double p=100*up[i]/a[i],m=100*dn[i]/a[i];dx[i]=p+m==0?0:100*Math.Abs(p-m)/(p+m);
        }return Ewm(dx,1.0/14,14);
    }
    static int At(IReadOnlyList<Candle>b,DateTime at,int minutes)
    {
        int l=0,r=b.Count;while(l<r){int k=(l+r)/2;if(b[k].At.AddMinutes(minutes)<=at)l=k+1;else r=k;}return l-1;
    }
    static double Value(IReadOnlyList<Candle>b,double[]values,DateTime at,int minutes)
    {int i=At(b,at,minutes);return i<0?double.NaN:values[i];}
    public (double Lower,double Upper,double Atr,double Adx,int Bias) Values(DateTime at)
    {
        double em=Value(m15,ema15,at,15),a=Value(m15,atr15,at,15),s=Value(h1,slope1,at,60);
        return (em-2*a,em+2*a,Value(m5,atr5,at,5),Value(h1,adx1,at,60),Finite(s)?(int)s:0);
    }
    static int Phase(DateTime wib)=>wib.Hour<14?0:wib.Hour<19?1:2;
    public static bool Session(DateTime at){var w=at.AddHours(7);return w.DayOfWeek>=DayOfWeek.Monday&&w.DayOfWeek<=DayOfWeek.Wednesday&&w.Hour>=14;}
    List<Signal> FindSignals()
    {
        var signals=new List<Signal>();var claimed=new HashSet<string>();
        for(int i=1;i<m1.Count;i++){
            var b=m1[i];var w=b.At.AddHours(7);
            if(w.DayOfWeek==DayOfWeek.Saturday||w.DayOfWeek==DayOfWeek.Sunday||w.Hour<7)continue;
            var f=Values(b.At);if(!Finite(f.Adx)||f.Adx>=20||!Finite(f.Atr)||f.Atr<=0)continue;
            foreach(int side in new[]{1,-1}){
                double level=side==1?f.Lower:f.Upper;if(!Finite(level))continue;
                bool cross=side==1?b.L<=level&&m1[i-1].C>level:b.H>=level&&m1[i-1].C<level;
                if(!cross)continue;string key=$"{w:yyyyMMdd}:{Phase(w)}:{side}";
                if(!claimed.Add(key))continue;
                for(int j=i;j<Math.Min(i+5,m1.Count);j++){
                    if(m1[j].At!=b.At.AddMinutes(j-i))break;
                    if(side*(m1[j].C-level)<=0)continue;
                    DateTime at=m1[j].At.AddMinutes(1);var end=Values(at);
                    if(Session(at)&&end.Bias==side&&Finite(end.Atr)&&end.Atr>0)
                        signals.Add(new(side,b.At,at,level,end.Atr,f.Adx));
                    break;
                }
            }
        }return signals.OrderBy(x=>x.At).ToList();
    }
    public static bool NewsAllowed(IReadOnlyList<News>? news,DateTime at)
    {
        if(news==null)return false;
        foreach(var n in news)if(Math.Abs((at-n.At).TotalMinutes)<=(n.Event=="FOMC"?60:30))return false;
        return true;
    }
    public Snapshot Evaluate(DateTime now,double bid,double ask,DateTime quoteAt,IReadOnlyList<News>? news)
    {
        var f=Values(now);string state="WAIT_DATA";Signal? signal=null;Plan? plan=null;
        Snapshot Result()=>new(state,f.Bias,f.Adx,f.Atr,f.Lower,f.Upper,signal,plan);
        if(m1.Count<2000||!Finite(f.Atr)||!Finite(f.Adx)||!Finite(f.Lower))return Result();
        if((now-m1[^1].At.AddMinutes(1)).TotalSeconds>90)return Result();
        var w=now.AddHours(7);bool day=w.DayOfWeek>=DayOfWeek.Monday&&w.DayOfWeek<=DayOfWeek.Wednesday;
        bool session=w.Hour>=14;bool calendar=NewsAllowed(news,now);
        bool quote=Finite(bid)&&Finite(ask)&&0<bid&&bid<=ask&&(now-quoteAt).TotalSeconds>=-5&&(now-quoteAt).TotalSeconds<=30;
        signal=Signals.LastOrDefault(x=>x.TouchAt.AddHours(7).Date==w.Date&&x.At<=now&&NewsAllowed(news,x.At));
        if(signal!=null){
            double age=(now-signal.At).TotalSeconds;double price=quote?(signal.Side==1?ask:bid):m1[^1].C;
            double distance=Math.Abs(price-signal.Level)/signal.Atr;
            if(age<60){
                if(distance>1){state="EXPIRED_PRICE";return Result();}
                if(!(day&&session&&calendar&&quote)){state="WAIT_CHECKLIST";return Result();}
                string id=$"R3:{signal.Side}:{signal.TouchAt:O}";
                if(FrozenPlan==null||FrozenPlan.Id!=id){
                    double risk=Math.Max(3*signal.Atr,2*(ask-bid));DateTime until=now.AddMinutes(240),midnight=w.Date.AddDays(1).AddHours(-7);
                    FrozenPlan=new(id,signal.Side,price,price-signal.Side*risk,price+signal.Side*3*risk,
                        signal.Level+signal.Side*signal.Atr,now,until<midnight?until:midnight);
                }
                state=signal.Side==1?"TRIGGER_BUY":"TRIGGER_SELL";plan=FrozenPlan;return Result();
            }
            if(age<900){state="EXPIRED_TIME";return Result();}
        }
        double reference=quote?(bid+ask)/2:m1[^1].C;
        state=!(day&&session)?"WAIT_SESSION":!calendar?"WAIT_NEWS":f.Adx>=20?"WAIT_REGIME":
            f.Bias==1&&Math.Abs(reference-f.Lower)<=.5*f.Atr?"PREPARE_BUY":
            f.Bias==-1&&Math.Abs(reference-f.Upper)<=.5*f.Atr?"PREPARE_SELL":"WATCH_ZONE";
        return Result();
    }
}
