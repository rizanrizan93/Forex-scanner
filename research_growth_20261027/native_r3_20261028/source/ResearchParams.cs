using System;
namespace Rizan.Portfolio;
public record ResearchCase {
 public string Id{get;set;}="BASELINE";
 public double SafetyFraction{get;set;}=1;
 public double XauRisk{get;set;}=1; public double EurRisk{get;set;}=1;public double BtcRisk{get;set;}=1;
 public int XauWindow{get;set;}=1;public double XauZone{get;set;}=0;public bool XauPause{get;set;}=false;
 public double XauStep{get;set;}=102.5;public double XauTarget{get;set;}=5.5;public int XauCooldown{get;set;}=3;
 public int EurWindow{get;set;}=1;public bool EurPause{get;set;}=false;
 public double EurInitial{get;set;}=.4;public double EurTarget{get;set;}=10;public double EurBE{get;set;}=2;
 public double EurStop{get;set;}=.845;public double EurDepth{get;set;}=1;public double PlanningCost{get;set;}=1;
 public double BtcBuyTarget{get;set;}=12;public double BtcSellTarget{get;set;}=2;
 public double BtcBuyStop{get;set;}=2;public double BtcSellStop{get;set;}=1.5;
 public int BtcBatchOrders{get;set;}=1;public int BtcBatchSeconds{get;set;}=180;public double BtcBatchRisk{get;set;}=.025;public double BtcBatchMargin{get;set;}=.1;public double BtcBatchZone{get;set;}=.5;
 public double BtcBuyHours{get;set;}=128;public double BtcSellHours{get;set;}=8;
}
public static class RP {
#if REPLAY
 public static ResearchCase C=new();
#else
 public static ResearchCase C{get;}=FrozenR3.Create();
#endif
 public static int SafeQuantity(int q)=>C.SafetyFraction>=1||q<=1?q:Math.Max(1,(int)Math.Floor(q*C.SafetyFraction));
 public static void Buffer(Xau.Basket b){
  if(C.SafetyFraction>=1)return;
  double extra=Math.Min(b.RemainingStageBudget,b.InitialRiskAllocation*(1-C.SafetyFraction));
  b.InitialRiskAllocation+=extra;b.RemainingStageBudget=Math.Max(0,b.RiskBudget-b.InitialRiskAllocation);
  b.InitialWanted=SafeQuantity(b.InitialWanted);b.QueueRemaining=b.InitialWanted;
 }
 public static void Buffer(Eur.Basket b){
  if(C.SafetyFraction>=1)return;
  double extra=Math.Min(b.RemainingStageBudget,b.InitialRiskAllocation*(1-C.SafetyFraction));
  b.InitialRiskAllocation+=extra;b.RemainingStageBudget=Math.Max(0,b.RiskBudget-b.InitialRiskAllocation);
  b.InitialWanted=SafeQuantity(b.InitialWanted);b.QueueRemaining=b.InitialWanted;
 }

 public static Xau.FrozenContract X(Xau.FrozenContract c)=>c with{RiskFraction=c.RiskFraction*C.XauRisk,BalanceStepUsd=C.XauStep,TargetR=C.XauTarget};
 public static Eur.FrozenContract E(Eur.FrozenContract c)=>c with{RiskFraction=c.RiskFraction*C.EurRisk,InitialFraction=C.EurInitial,TargetR=C.EurTarget,Depths=Array.ConvertAll(c.Depths,x=>x*C.EurDepth),Slip=c.Slip*C.PlanningCost,CommissionPerSide=c.CommissionPerSide*C.PlanningCost};
}
