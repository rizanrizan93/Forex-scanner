using Rizan.Frozen;
int assertions=0;
var c=FrozenContract.Eur;
var rng=new Random(2047);
for(int i=0;i<2000;i++){
 int side=i%2==0?1:-1;double cash=100+100000*rng.NextDouble(),quote=1.05+.2*rng.NextDouble(),distance=.001+.009*rng.NextDouble();
 var signal=new Signal(new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc),side,distance,0,0);
 var b=FrozenCore.StartBasket(c,signal,quote,cash,cash,cash,0,1000*quote/200,.5+.5*rng.NextDouble(),cash)!;
 if(b==null)continue;
 int stage=i%3,cap=1+i%150;double equity=cash*(.8+.2*rng.NextDouble()),used=equity*.1,margin=1000*quote/200,spread=.00001;
 int q=BatchPlanner.Count(c,b,stage,quote,equity,used,margin,spread,cap),brute=0;
 for(int k=1;k<=cap;k++){double cost=c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide,risk=FrozenCore.PlannedChildRisk(c,side,quote,b.Stop),reference=Math.Min(b.ReferenceBalance,equity-k*cost);
 bool ok=reference>0&&b.StageRisk[stage]+k*risk<=FrozenCore.StageAllocation(c,b,stage)+1e-8&&b.UsedRisk+k*risk<=Math.Min(b.RiskBudget,reference*c.RiskFraction*b.Scale)+1e-8&&used+k*margin<=reference*c.MarginFraction*b.Scale+1e-8&&equity-used>=k*(margin+cost);if(ok)brute=k;}
 Check(q==brute,"MAXIMAL_BATCH");
 if(q>0){double after=equity-q*(c.ChildUnits*(spread+c.Slip)+c.CommissionPerSide);Check(BatchPlanner.ActualOk(c,b,stage,quote+side*c.Slip,after,used+q*margin,q),"PROJECTED_ACTUAL_PARITY");}
 Check(BatchPlanner.Count(c,b,stage,double.NaN,equity,used,margin,spread,cap)==0,"INVALID_QUOTE");
 Check(!BatchPlanner.ActualOk(c,b,stage,quote,-1,used,1),"INVALID_EQUITY");
}
Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new{Pass=true,Assertions=assertions}));
void Check(bool v,string message){assertions++;if(!v)throw new Exception(message);}
