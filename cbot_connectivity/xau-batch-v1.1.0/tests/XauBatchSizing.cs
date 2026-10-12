using System;
using Rizan.Frozen;
namespace Rizan.Research;
// Research helper only. No broker calls or live order authority.
public static class XauBatchSizing {
 public static bool PlannedOk(FrozenContract c,Basket b,int stage,int quantity,double fill,double equity,double freeMargin,double usedMargin,double fullMargin,double spread){
  if(quantity<1||stage<0||stage>=c.Stages||!FrozenCore.Finite(fill)||fill<=0||!FrozenCore.Finite(equity)||equity<=0||!FrozenCore.Finite(freeMargin)||freeMargin<0||!FrozenCore.Finite(usedMargin)||usedMargin<0||!FrozenCore.Finite(fullMargin)||fullMargin<=0||!FrozenCore.Finite(spread)||spread<0)return false;
  double risk=quantity*FrozenCore.ChildRisk(c,b.Side,fill+b.Side*c.Slip,b.Stop);
  double cost=quantity*(c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide),postEquity=equity-cost,reference=Math.Min(b.ReferenceBalance,postEquity);
  return reference>0&&FrozenCore.Finite(risk)&&risk>0&&b.StageRisk[stage]+risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+risk<=b.RiskBudget+1e-8&&usedMargin+fullMargin<=reference*c.MarginFraction*b.Scale+1e-8&&freeMargin>=fullMargin+cost;
 }
 public static int Count(FrozenContract c,Basket b,int stage,int cap,double fill,double equity,double freeMargin,double usedMargin,double spread,Func<int,double> margin){
  if(cap<1)return 0;int lo=0,hi=cap;while(lo<hi){int q=lo+(hi-lo+1)/2;if(PlannedOk(c,b,stage,q,fill,equity,freeMargin,usedMargin,margin(q),spread))lo=q;else hi=q-1;}return lo;
 }
}
