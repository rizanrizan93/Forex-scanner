using System;
namespace Rizan.Portfolio.Eur;

// Immutable F0245 v1. Virtual feedback deliberately retains the original EUR signal/4R reference.
public static class F0245Policy
{
    public const string Version = "1.2.0_F0245";
    public const string ConfigHash = "d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a";
    public static FrozenContract Contract => RP.E(FrozenContract.Eur with { Hash=ConfigHash, RiskFraction=.2075, TargetR=10 });
    public static Signal ExecutionSignal(Signal signal) => signal with { Distance=signal.Distance*RP.C.EurStop };
    // entryFees is the known absolute opening commission for the remaining owned volume.
    // Exit commission is estimated with the frozen contract; this is cost-adjusted BE, not guaranteed net zero.
    public static bool UpdateBreakEven(FrozenContract c,Basket b,double exitQuote,double volumeUnits,double weightedEntry,double entryFees)
    {
        if(volumeUnits<=0||!FrozenCore.Finite(exitQuote)||!FrozenCore.Finite(weightedEntry)||!FrozenCore.Finite(entryFees)||entryFees<0||b.OriginalDistance<=0)return false;
        b.BestExit=b.BestExit<=0?exitQuote:b.Side==1?Math.Max(b.BestExit,exitQuote):Math.Min(b.BestExit,exitQuote);
        if(b.Side*(b.BestExit-b.Entry)<RP.C.EurBE*b.OriginalDistance)return false;
        double stop=weightedEntry+b.Side*(c.Slip+entryFees/volumeUnits+c.CommissionPerSide/c.ChildUnits);
        if(b.Side*(exitQuote-stop)<=1e-8||b.Side*(stop-b.Stop)<=1e-8)return false;
        b.Stop=stop;b.BreakEvenArmed=true;b.QueueRemaining=0;b.QueueStage=-1;b.NextStage=c.Stages;
        return true;
    }
}
