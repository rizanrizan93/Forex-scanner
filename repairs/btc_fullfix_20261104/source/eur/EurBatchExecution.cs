using System;
using System.Linq;
namespace Rizan.Portfolio.Eur;

// All counts are virtual 1,000-unit children. A broker position can contain many.
public static class EurBatchExecution
{
    public const string Model = "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1";
    public const int MaxChildren = 2000;
    public const double ReversalToleranceR = .02;
    public static Basket? Start(FrozenContract c,Signal signal,double quote,double balance,double equity,double freeMargin,double usedMargin,double marginChild,double scale,double peak)
    {
        var b=FrozenCore.StartBasket(c,signal,quote+signal.Side*c.Slip,balance,equity,freeMargin,usedMargin,marginChild,scale,peak);
        if(b==null && scale<1) {
            // Research candidate: one first child only, risk unchanged, 50% hard margin cap.
            b=FrozenCore.StartBasket(c with{MarginFraction=c.MarginFraction/scale},signal,quote+signal.Side*c.Slip,balance,equity,freeMargin,usedMargin,marginChild,scale,peak);
            if(b!=null) {
                double oneRisk=FrozenCore.ChildRisk(c,b.Side,b.Entry,b.Stop);
                if(oneRisk>b.RiskBudget)return null;
                b.InitialWanted=1;b.QueueRemaining=1;b.InitialRiskAllocation=oneRisk;
                b.RemainingStageBudget=Math.Max(0,b.RiskBudget-oneRisk);
                return b;
            }
        }
        if(b==null)return null;
        // First request has brackets relative to the actual fill: distance is fixed.
        double risk=FrozenCore.ChildRisk(c,b.Side,b.Entry,b.Stop),reference=Math.Min(balance,equity);
        int count=FrozenCore.FloorCount(Math.Min(reference*c.RiskFraction*scale/risk,Math.Max(0,Math.Min(freeMargin,reference*c.MarginFraction*scale-usedMargin))/marginChild));
        double degear=peak>0&&(peak-equity)/peak>=.25?.7:1;
        b.InitialWanted=Math.Min(Math.Max(1,FrozenCore.FloorCount(count*c.InitialFraction*degear)),FrozenCore.FloorCount(b.RiskBudget/risk));
        if(count<1||b.InitialWanted<1)return null;
        b.InitialRiskAllocation=b.InitialWanted*risk;b.RemainingStageBudget=Math.Max(0,b.RiskBudget-b.InitialRiskAllocation);b.QueueRemaining=b.InitialWanted;
        return b;
    }
    public static void AnchorFirstFill(FrozenContract c,Basket b,double entry)
    {
        if(b.Accepted.Sum()!=0)throw new InvalidOperationException("FIRST_FILL_ALREADY_ACCEPTED");
        if(!FrozenCore.Finite(entry)||entry<=0)throw new ArgumentException("INVALID_FILL");
        double distance=Math.Abs(b.Entry-b.Stop);b.Entry=entry;b.Stop=entry-b.Side*distance;b.Target=entry+b.Side*distance*c.TargetR;
    }
    public static int ChildrenForVolume(double volume,double childUnits)
    {
        if(!FrozenCore.Finite(volume)||!FrozenCore.Finite(childUnits)||volume<=0||childUnits<=0)return 0;
        double q=volume/childUnits;
        return q<=int.MaxValue&&Math.Abs(q-Math.Round(q))<=1e-8?(int)Math.Round(q):0;
    }
    public static int ExposureStage(FrozenContract c,Basket b,string prefix,string label,double volume)
    {
        var parts=label.Split('|');int live=ChildrenForVolume(volume,c.ChildUnits);
        if(parts.Length!=5||parts[0]!=prefix||!long.TryParse(parts[1],out var ticks)||ticks!=b.AtUtc.Ticks||!int.TryParse(parts[2],out var stage)||stage<0||stage>=c.Stages||!long.TryParse(parts[3],out var sequence)||sequence<1||sequence>b.Sequence||!int.TryParse(parts[4],out var quantity)||quantity<1||quantity>MaxChildren||live<1||live>quantity)return -1;
        return stage;
    }
    public static bool InZone(FrozenContract c,Basket b,int stage,double quote)
    {
        if(stage<0||stage>=c.Stages||!FrozenCore.Finite(quote)||quote<=0)return false;
        double distance=Math.Abs(b.Entry-b.Stop);
        return distance>0&&b.Side*(b.Entry-quote)/distance>=c.Depths[stage]-ReversalToleranceR;
    }
    public static bool PlannedOk(FrozenContract c,Basket b,int stage,double quote,double equity,double freeMargin,double usedMargin,double batchMargin,double spread,int quantity,bool first)
    {
        if(quantity<1||stage<0||stage>=c.Stages||!new[]{quote,equity,batchMargin}.All(x=>FrozenCore.Finite(x)&&x>0)||!new[]{freeMargin,usedMargin,spread}.All(x=>FrozenCore.Finite(x)&&x>=0))return false;
        double perRisk=first?FrozenCore.ChildRisk(c,b.Side,b.Entry,b.Stop):FrozenCore.PlannedChildRisk(c,b.Side,quote,b.Stop);
        double risk=quantity*perRisk,cost=quantity*(c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide),reference=Math.Min(b.ReferenceBalance,equity-cost);
        return reference>0&&FrozenCore.Finite(risk)&&risk>0&&b.StageRisk[stage]+risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8&&usedMargin+batchMargin<=reference*c.MarginFraction*((stage==0&&first&&quantity==1)?1:b.Scale)+1e-8&&freeMargin>=batchMargin+cost;
    }
    // The delegate quotes margin for the entire order, including broker leverage tiers.
    public static int Count(FrozenContract c,Basket b,int stage,double quote,double equity,double freeMargin,double usedMargin,double spread,int cap,bool first,Func<int,double> margin)
    {
        if(cap<1)return 0;int lo=0,hi=Math.Min(cap,MaxChildren);
        while(lo<hi){int q=lo+(hi-lo+1)/2;if(PlannedOk(c,b,stage,quote,equity,freeMargin,usedMargin,margin(q),spread,q,first))lo=q;else hi=q-1;}return lo;
    }
    public static bool ActualOk(FrozenContract c,Basket b,int stage,double fill,double equity,double usedMargin,int quantity,double entryCommission=0)
    {
        if(!FrozenCore.Finite(entryCommission)||entryCommission<0)return false;
        if(quantity<1||stage<0||stage>=c.Stages||!new[]{fill,equity}.All(x=>FrozenCore.Finite(x)&&x>0)||!FrozenCore.Finite(usedMargin)||usedMargin<0)return false;
        double risk=quantity*FrozenCore.ChildRisk(c,b.Side,fill,b.Stop)+2*Math.Max(0,entryCommission-quantity*c.CommissionPerSide),reference=Math.Min(b.ReferenceBalance,equity);
        return FrozenCore.Finite(risk)&&risk>0&&b.StageRisk[stage]+risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8&&usedMargin<=reference*c.MarginFraction*((stage==0&&b.Accepted.Sum()==0&&quantity==1)?1:b.Scale)+1e-8;
    }
    public static void Accept(FrozenContract c,Basket b,int stage,double fill,int quantity,double entryCommission=0)
    {
        if(quantity<1||stage<0||stage>=c.Stages||quantity>b.QueueRemaining||b.QueueStage!=stage)throw new InvalidOperationException("INVALID_BATCH_ACCEPTANCE");
        double risk=quantity*FrozenCore.ChildRisk(c,b.Side,fill,b.Stop)+2*Math.Max(0,entryCommission-quantity*c.CommissionPerSide);
        if(!FrozenCore.Finite(risk)||risk<=0||!FrozenCore.Finite(entryCommission)||entryCommission<0)throw new InvalidOperationException("INVALID_BATCH_RISK");
        b.Accepted[stage]=checked(b.Accepted[stage]+quantity);b.StageRisk[stage]+=risk;b.UsedRisk+=risk;b.QueueRemaining-=quantity;
        if(b.QueueRemaining==0){b.NextStage=Math.Max(b.NextStage,stage+1);b.QueueStage=-1;}
    }
}
