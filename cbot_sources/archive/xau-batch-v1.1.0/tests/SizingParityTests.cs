using System;using System.Text.Json;using Rizan.Frozen;using Rizan.Research;
var c=FrozenContract.Xau;int checks=0;var rnd=new Random(20261012);
for(int t=0;t<1000;t++){
 int side=t%2==0?1:-1;double cash=new[]{100d,1000d,10000d}[t%3],quote=side==1?1200.11:1200,entry=quote+side*.05;var b=FrozenCore.StartBasket(c,new(new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc),side,0,2,side==1?1198:1202.11),entry,cash,cash,cash,0,entry/100,1,cash,.16)!;
 int stage=t%4;double equity=cash*(.1+.9*rnd.NextDouble()),used=stage==0?0:cash*.1;
 if(stage>0){double risk=FrozenCore.ChildRisk(c,side,entry,b.Stop);b.UsedRisk=b.InitialWanted*risk;b.StageRisk[0]=b.UsedRisk;quote-=side*(1+rnd.NextDouble());}
 int cap=stage==0?b.InitialWanted:100;Func<int,double> margin=q=>q*12+(q>20?(q-20)*2:0);
 int native=XauBatchExecution.Count(c,b,stage,quote,equity,Math.Max(0,equity-used),used,.11,cap,stage==0,margin);
 int replay=XauBatchSizing.Count(c,b,stage,cap,quote,equity,Math.Max(0,equity-used),used,.11,margin);
 if(native!=replay)throw new Exception("REPLAY_SIZING_PARITY");int brute=0;for(int q=1;q<=cap;q++)if(XauBatchExecution.PlannedOk(c,b,stage,quote,equity,Math.Max(0,equity-used),used,margin(q),.11,q,stage==0))brute=q;
 if(native!=brute)throw new Exception("TIERED_MARGIN_COUNT");checks++;
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,Scope="Native batch sizing helper vs prior research helper, four stages, equity and nonlinear margin fixture"}));
