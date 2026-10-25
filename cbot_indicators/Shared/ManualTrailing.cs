using System;
using X=Rizan.Portfolio.Xau;
namespace Rizan.Indicators;

// An indicative scenario, never a broker stop or a strategy backtest.
public sealed class ManualTrailing
{
    public int Side {get;}
    public double Entry {get;}
    public double InitialStop {get;}
    public double Stop {get;private set;}
    public double Risk => Math.Abs(Entry-InitialStop);
    public double Water {get;private set;}
    public DateTime Cursor {get;private set;}
    public bool Active {get;private set;}
    public bool Stopped {get;private set;}
    public bool CoverageGap {get;private set;}
    public double? Exit {get;private set;}
    readonly double spread,activationR,distanceR;
    public ManualTrailing(int side,double entry,double stop,DateTime start,double assumedSpread,
                          double activation=1,double distance=1)
    {
        if(side is not (1 or -1) || !X.FrozenCore.Finite(entry+stop+assumedSpread+activation+distance) ||
           Math.Min(entry,stop)<=0 || side*(entry-stop)<=0 || assumedSpread<0 || activation<0 || distance<=0)
            throw new ArgumentException("INVALID_MANUAL_SCENARIO");
        Side=side;Entry=entry;InitialStop=stop;Stop=stop;Water=entry;
        Cursor=X.FrozenCore.Floor(start,1);if(Cursor<start)Cursor=Cursor.AddMinutes(1);
        spread=assumedSpread;activationR=activation;distanceR=distance;
    }
    public void Step(X.Candle b)
    {
        if(Stopped || CoverageGap || b.OpenUtc<Cursor)return;
        if(b.OpenUtc!=Cursor){CoverageGap=true;return;}
        double offset=Side==-1 ? spread : 0;
        double adverse=(Side==1 ? b.Low : b.High)+offset;
        if(Side*(adverse-Stop)<=0)
        {
            double open=b.Open+offset;Exit=Side==1 ? Math.Min(Stop,open) : Math.Max(Stop,open);
            Stopped=true;Cursor=b.End(1);return;
        }
        double favorable=(Side==1 ? b.High : b.Low)+offset;
        Water=Side==1 ? Math.Max(Water,favorable) : Math.Min(Water,favorable);
        Active=Active || Side*(Water-Entry)>=activationR*Risk;
        if(Active)
        {
            double quote=b.Close+offset;double candidate=Water-Side*distanceR*Risk;
            candidate=Side==1 ? Math.Min(candidate,quote-.01) : Math.Max(candidate,quote+.01);
            Stop=Side==1 ? Math.Max(Stop,candidate) : Math.Min(Stop,candidate);
        }
        Cursor=b.End(1);
    }
}
