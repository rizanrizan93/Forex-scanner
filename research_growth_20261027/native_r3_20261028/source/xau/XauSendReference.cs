using System;
using System.Linq;
using System.Globalization;
namespace Rizan.Portfolio.Xau;
public static class XauSendReference {
 public static Basket? Refresh(FrozenContract c,Signal? signal,Basket template,double quote,double spread,double freeMargin,double marginChild,double tolerance) {
  if(signal==null||!FrozenCore.Finite(signal.Atr)||signal.Atr<=0||!FrozenCore.Finite(signal.Anchor)||signal.Anchor<=0||signal.AtUtc!=template.AtUtc||signal.Side!=template.Side||template.Accepted.Sum()!=0||!FrozenCore.Finite(quote)||!FrozenCore.Finite(spread)||spread<0)return null;
  double entry=quote+signal.Side*c.Slip;
  if(Math.Abs(entry-template.Entry)>tolerance*Math.Abs(template.Entry-template.Stop)+1e-8)return null;
  var s=signal.Side==-1?signal with{Anchor=signal.Anchor+spread}:signal;
  var contract=c with{RiskFraction=template.RiskBudget/template.ReferenceBalance};
  var b=FrozenCore.StartBasket(contract,s,entry,template.ReferenceBalance,template.ReferenceBalance,freeMargin,0,marginChild,1,template.ReferenceBalance,spread+c.Slip);
  if(b==null||b.RiskBudget>template.RiskBudget+1e-8||b.ExitUtc!=template.ExitUtc)return null;
  b.Sequence=template.Sequence;return b;
 }
 public static bool Restore(FrozenContract c,Signal? signal,Basket template,string comment,int maximum,double tolerance,out Basket? b,out int requested) {
  b=null;requested=0;var p=comment?.Split(';');
  if(signal==null||!FrozenCore.Finite(signal.Atr)||signal.Atr<=0||!FrozenCore.Finite(signal.Anchor)||signal.Anchor<=0||signal.AtUtc!=template.AtUtc||signal.Side!=template.Side||p==null||p.Length!=9||p[0]!="RZ1"||!long.TryParse(p[1],out var at)||at!=template.AtUtc.Ticks||!long.TryParse(p[2],out var exit)||exit!=template.ExitUtc.Ticks||!int.TryParse(p[3],out var side)||side!=template.Side||!int.TryParse(p[6],out int wanted)||wanted<1||!int.TryParse(p[7],out requested)||requested<1||requested>maximum||requested>wanted)return false;
  var ic=CultureInfo.InvariantCulture;
  if(!double.TryParse(p[4],NumberStyles.Float,ic,out var stop)||!double.TryParse(p[5],NumberStyles.Float,ic,out var target)||!double.TryParse(p[8],NumberStyles.Float,ic,out var spread)||!new[]{stop,target,spread}.All(FrozenCore.Finite)||stop<=0||target<=0||spread<0||spread>1.5)return false;
  double entry=(target+c.TargetR*stop)/(1+c.TargetR),distance=side*(entry-stop);
  double expected=Math.Max(.5,Math.Max(c.StopAtrMultiplier*signal.Atr,side*(entry-signal.Anchor-(side==-1?spread:0))));
  if(!FrozenCore.Finite(entry)||!FrozenCore.Finite(expected)||distance<=0||Math.Abs(distance-expected)>1e-7||Math.Abs(entry-template.Entry)>tolerance*Math.Abs(template.Entry-template.Stop)+1e-7)return false;
  double allocation=wanted*FrozenCore.ChildRisk(c,side,entry,stop);
  if(!FrozenCore.Finite(allocation)||allocation<=0||allocation>template.RiskBudget+1e-7)return false;
  b=new Basket{AtUtc=template.AtUtc,ExitUtc=template.ExitUtc,Side=side,Entry=entry,Stop=stop,Target=target,ReferenceBalance=template.ReferenceBalance,RiskBudget=template.RiskBudget,Scale=1,InitialWanted=wanted,InitialRiskAllocation=allocation,RemainingStageBudget=Math.Max(0,template.RiskBudget-allocation),QueueStage=0,QueueRemaining=wanted,Sequence=template.Sequence};return true;
 }
}
