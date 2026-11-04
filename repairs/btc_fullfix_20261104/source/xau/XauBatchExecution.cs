using System;
using System.Linq;
namespace Rizan.Portfolio.Xau;

// All counts are virtual 1-oz children. A broker position can contain many.
public static class XauBatchExecution
{
    public const string Model = "XAU_BATCH_STAGE_FIXED_REF_WAL_V1";
    public const int MaxChildren = 2000;
    
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
    public static bool PlannedOk(FrozenContract c,Basket b,int stage,double quote,double equity,double freeMargin,double usedMargin,double batchMargin,double spread,int quantity,bool first)
    {
        if(quantity<1||stage<0||stage>=c.Stages||!new[]{quote,equity,batchMargin}.All(x=>FrozenCore.Finite(x)&&x>0)||!new[]{freeMargin,usedMargin,spread}.All(x=>FrozenCore.Finite(x)&&x>=0))return false;
        double perRisk=FrozenCore.ChildRisk(c,b.Side,quote+b.Side*c.Slip,b.Stop);
        double risk=quantity*perRisk,cost=quantity*(c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide),reference=Math.Min(b.ReferenceBalance,equity-cost);
        return reference>0&&FrozenCore.Finite(risk)&&risk>0&&b.StageRisk[stage]+risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+risk<=b.RiskBudget+1e-8&&usedMargin+batchMargin<=reference*c.MarginFraction*b.Scale+1e-8&&freeMargin>=batchMargin+cost;
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
        return FrozenCore.Finite(risk)&&risk>0&&b.StageRisk[stage]+risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+risk<=b.RiskBudget+1e-8&&usedMargin<=reference*c.MarginFraction*b.Scale+1e-8;
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
