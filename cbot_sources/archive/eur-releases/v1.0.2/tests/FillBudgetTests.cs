using System;
using System.Text.Json;
using Rizan.Frozen;
int assertions=0;
void Check(bool ok,string label){assertions++;if(!ok)throw new Exception(label);}
var c=FrozenContract.Eur;
// Exact one-child regression from 25 January 2021, both order sides.
foreach(int side in new[]{1,-1}){
 double quote=1.21497,eq=95.9885;
 var signal=new Signal(new DateTime(2021,1,25,10,30,0,DateTimeKind.Utc),side,.00244928571428571);
 var b=FrozenCore.StartBasket(c,signal,quote,eq,eq,eq,0,1000*quote/200,.625,100)!;
 Check(b.InitialWanted==1,"ONE_CHILD_REGRESSION");
 Check(FrozenCore.FillBudgetOk(c,b,0,quote,eq,eq,0,1000*quote/200,.00001),"ONE_CHILD_PRECHECK");
 Check(FrozenCore.ActualFillBudgetOk(c,b,0,quote+side*.00001,eq-.05,1000*quote/200),"DECLARED_SLIPPAGE_ALLOWED");
 Check(!FrozenCore.ActualFillBudgetOk(c,b,0,quote+side*.00002,eq-.06,1000*quote/200),"EXCESS_SLIPPAGE_BLOCKED");
 Check(Math.Abs(FrozenCore.PlannedChildRisk(c,side,quote,b.Stop)-FrozenCore.ChildRisk(c,side,quote+side*c.Slip,b.Stop))<1e-10,"QUOTE_AND_ACTUAL_PARITY");
 // Legacy checkpoint allocation: no silent increase of committed budgets.
 b.InitialRiskAllocation=FrozenCore.ChildRisk(c,side,quote,b.Stop);
 Check(!FrozenCore.FillBudgetOk(c,b,0,quote,eq,eq,0,1000*quote/200,.00001),"LEGACY_QUEUE_FAILS_BEFORE_ORDER");
}
// Independent formula oracle across balances, feedback, degear and stages.
foreach(double equity in new[]{50d,100d,200d,1000d,10000d})foreach(double scale in new[]{1d,.625,.1})foreach(int side in new[]{1,-1})foreach(double dd in new[]{0d,.25,.5}){
 double quote=1.1,dist=.0015,margin=5.5,peak=equity/(1-dd);
 var b=FrozenCore.StartBasket(c,new Signal(DateTime.UtcNow,side,dist),quote,equity,equity,equity,0,margin,scale,peak);
 double risk=1000*(dist+2*c.Slip)+.06;int count=(int)Math.Floor(Math.Min(equity*.2725*scale/risk,equity*.5*scale/margin)+1e-9);
 double degear=(peak-equity)/peak>=.25?.7:1,budget=equity*.2725*scale*degear;
 int wanted=count>0?Math.Min(Math.Max(1,(int)Math.Floor(count*.4*degear+1e-9)),(int)Math.Floor(budget/risk+1e-9)):0;
 Check((b?.InitialWanted??0)==wanted,"INITIAL_INTEGER_SIZING");
 if(b==null)continue;
 Check(Math.Abs(b.RiskBudget-budget)<1e-8,"TOTAL_BUDGET_UNCHANGED");
 Check(b.InitialRiskAllocation+b.RemainingStageBudget<=budget+1e-8,"ALLOCATIONS_WITHIN_TOTAL");
 for(int stage=0;stage<c.Stages;stage++){
  double fill=quote-side*c.Depths[stage]*dist;
  for(int shift=0;shift<10;shift++){
   double slips=c.Slip*shift/9,actual=fill+side*slips;
   Check(FrozenCore.ChildRisk(c,side,actual,b.Stop)<=FrozenCore.PlannedChildRisk(c,side,fill,b.Stop)+1e-8,"EXPECTED_SLIPPAGE_RESERVED");
  }
 }
 Check(!FrozenCore.FillBudgetOk(c,b,0,quote,double.NaN,equity,0,margin,.00001),"NAN_EQUITY_REJECTED");
 Check(!FrozenCore.FillBudgetOk(c,b,0,quote,equity,0,0,margin,.00001),"NO_MARGIN_REJECTED");
 Check(!FrozenCore.ActualFillBudgetOk(c,b,0,quote,0,margin),"ZERO_EQUITY_REJECTED");
 Check(!FrozenCore.ActualFillBudgetOk(c,b,0,quote,equity,equity),"MARGIN_CAP_REJECTED");
}
var tight=FrozenCore.StartBasket(c,new Signal(DateTime.UtcNow,1,.0015),1.1,100,100,100,0,5.5,1,100)!;
Check(!FrozenCore.FillBudgetOk(c,tight,0,1.1,100,100,0,49.99,.00001),"COMMISSION_PROJECTED_MARGIN_BLOCK");
Check(!FrozenCore.FillBudgetOk(c,tight,-1,1.1,100,100,0,5.5,.00001),"INVALID_STAGE_BLOCK");
Console.WriteLine(JsonSerializer.Serialize(new{Status="PASS",Assertions=assertions,Scope="Sizing, pre-fill/actual-fill budgets, both directions, old checkpoint allocation, invalid funds and projected costs"}));
