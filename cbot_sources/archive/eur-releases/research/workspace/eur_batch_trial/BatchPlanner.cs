using Rizan.Frozen;
// Offline execution prototype. Counts denote virtual 1,000-unit children, not broker positions.
static class BatchPlanner
{
 public static int Count(FrozenContract c,Basket b,int stage,double quote,double equity,double used,double margin,double spread,int cap)
 {
  if(cap<1||stage<0||stage>=c.Stages||!new[]{quote,equity,margin}.All(x=>FrozenCore.Finite(x)&&x>0)||!new[]{used,spread}.All(x=>FrozenCore.Finite(x)&&x>=0))return 0;
  double risk=FrozenCore.PlannedChildRisk(c,b.Side,quote,b.Stop),cost=c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide;
  if(!FrozenCore.Finite(risk)||risk<=0)return 0;
  int lo=0,hi=cap;
  while(lo<hi){int q=lo+(hi-lo+1)/2;if(Ok(q))lo=q;else hi=q-1;}return lo;
  bool Ok(int q){double projected=equity-q*cost,reference=Math.Min(b.ReferenceBalance,projected);return reference>0&&b.StageRisk[stage]+q*risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+q*risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8&&used+q*margin<=reference*c.MarginFraction*b.Scale+1e-8&&equity-used>=q*(margin+cost);}
 }
 public static bool ActualOk(FrozenContract c,Basket b,int stage,double fill,double equity,double used,int q)
 {
  if(q<1||stage<0||stage>=c.Stages||!new[]{fill,equity}.All(x=>FrozenCore.Finite(x)&&x>0)||!FrozenCore.Finite(used)||used<0)return false;
  double risk=q*FrozenCore.ChildRisk(c,b.Side,fill,b.Stop),reference=Math.Min(b.ReferenceBalance,equity);
  return FrozenCore.Finite(risk)&&risk>0&&b.StageRisk[stage]+risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8&&used<=reference*c.MarginFraction*b.Scale+1e-8;
 }
}
