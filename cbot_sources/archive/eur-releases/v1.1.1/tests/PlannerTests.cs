using System;
using System.Linq;
using System.Text.Json;
using Rizan.Frozen;
int assertions=0;var c=FrozenContract.Eur;var rng=new Random(98107);
for(int i=0;i<3000;i++){
 int side=i%2==0?1:-1;double cash=100+100000*rng.NextDouble(),quote=1.05+.2*rng.NextDouble(),distance=.001+.009*rng.NextDouble(),spread=.00001;
 var b=EurBatchExecution.Start(c,new(new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc),side,distance),quote,cash,cash,cash,0,1000*quote/200,.625,cash);if(b==null)continue;
 int stage=i%3,cap=1+i%150;bool first=stage==0;double equity=cash*(.8+.2*rng.NextDouble()),used=equity*.1,margin=1000*quote/200;
 double Margin(int q)=>q*margin*(q>50?1.1:1);
 int q=EurBatchExecution.Count(c,b,stage,quote,equity,equity-used,used,spread,cap,first,Margin),brute=0;
 for(int k=1;k<=cap;k++){double risk=first?FrozenCore.ChildRisk(c,side,b.Entry,b.Stop):FrozenCore.PlannedChildRisk(c,side,quote,b.Stop),cost=k*(c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide),reference=Math.Min(b.ReferenceBalance,equity-cost);
 bool ok=reference>0&&b.StageRisk[stage]+k*risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+k*risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8&&used+Margin(k)<=FrozenCore.MarginCeiling(c,reference,b.Scale)+1e-8&&equity-used>=Margin(k)+cost;if(ok)brute=k;}
 Check(q==brute,"MAXIMAL_WITH_TIERS");
 if(q>0){if(first)EurBatchExecution.AnchorFirstFill(c,b,quote+side*c.Slip);Check(EurBatchExecution.ActualOk(c,b,stage,quote+side*c.Slip,equity-q*(c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide),used+Margin(q),q),"PLANNED_ACTUAL_PARITY");}
 Check(EurBatchExecution.Count(c,b,stage,double.NaN,equity,equity-used,used,spread,cap,first,Margin)==0,"INVALID_QUOTE");
 Check(EurBatchExecution.ChildrenForVolume(1500,1000)==0,"FRACTIONAL_VIRTUAL_CHILD_REJECTED");
}
var examples=new System.Collections.Generic.List<object>();
foreach(int leverage in new[]{30,100,200})foreach(int side in new[]{1,-1}){
 double quote=1.1,spread=.00001;var b=EurBatchExecution.Start(c,new(new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc),side,.002),quote,100,100,100,0,1000*quote/leverage,1,100)!;
 int q=EurBatchExecution.Count(c,b,0,quote,100,100,0,spread,b.QueueRemaining,true,k=>k*1000*quote/leverage);
 examples.Add(new{Leverage=leverage,Side=side,Equity=100,Quote=quote,StopPips=20,Scale=1,InitialChildren=q,Lots=q*.01,ProjectedMargin=q*1000*quote/leverage});
 Check(q>0&&q<=EurBatchExecution.MaxChildren,"SMALL_CAPITAL_FITS");
 double per=FrozenCore.ChildRisk(c,side,b.Entry,b.Stop);EurBatchExecution.AnchorFirstFill(c,b,quote+side*.00007);b.QueueStage=0;b.QueueRemaining=q;
 EurBatchExecution.Accept(c,b,0,b.Entry,q);Check(b.Accepted[0]==q&&Math.Abs(b.UsedRisk-q*per)<1e-8,"AGGREGATED_ACCEPTANCE");
 Check(b.QueueStage==-1&&b.NextStage==1,"QUEUE_TRANSITION");
 bool duplicate=false;try{EurBatchExecution.Accept(c,b,0,b.Entry,q);}catch(InvalidOperationException){duplicate=true;}Check(duplicate,"NO_DOUBLE_ACCEPTANCE");
}
// Regression: virtual feedback can lower EUR scale to .1. The risk budget must shrink,
// but broker-minimum 1,000-unit execution must not be blocked only because the margin
// ceiling was multiplied by the same scale. $100 remains constrained by the 50% hard
// margin ceiling and by the .1-scaled risk budget.
foreach(int leverage in new[]{30,100,200})foreach(int side in new[]{1,-1}){
 double quote=1.1,spread=.00001,scale=.1,margin=1000*quote/leverage;
 var b=EurBatchExecution.Start(c,new(new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc),side,.002),quote,100,100,100,0,margin,scale,100);
 Check(b!=null,"LOW_SCALE_SMALL_CAPITAL_STARTS");
 int q=EurBatchExecution.Count(c,b!,0,quote,100,100,0,spread,b!.QueueRemaining,true,k=>k*margin);
 examples.Add(new{Leverage=leverage,Side=side,Equity=100,Quote=quote,StopPips=20,Scale=scale,InitialChildren=q,Lots=q*.01,ProjectedMargin=q*margin,ScaledRiskBudget=100*c.RiskFraction*scale,HardMarginCeiling=FrozenCore.MarginCeiling(c,100,scale)});
 Check(q>=1,"LOW_SCALE_MIN_CHILD_FITS");
 Check(q*margin<=FrozenCore.MarginCeiling(c,100,scale)+1e-8,"LOW_SCALE_MARGIN_WITHIN_HARD_CEILING");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Assertions=assertions,Examples=examples}));
void Check(bool value,string name){assertions++;if(!value)throw new Exception(name);}
