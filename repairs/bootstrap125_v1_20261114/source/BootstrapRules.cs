using System;
using System.Collections.Generic;
using System.Linq;
namespace Rizan.Portfolio;
public readonly record struct SeedBar(DateTime At,double Open,double High,double Low,double Close,int Count);
public readonly record struct SeedSignal(DateTime At,double Atr,double Anchor);
public static class BootstrapRules
{
 public const double Handoff=125,Risk=.08,Margin=.5,StopAtr=1.25,TargetR=4;
 public static bool CanGraduate(double balance,double equity,bool flat)=>flat&&double.IsFinite(balance)&&double.IsFinite(equity)&&balance>=Handoff&&equity>=Handoff;
 public static double[] Ema(IReadOnlyList<double> a,int span){var v=new double[a.Count];if(a.Count==0)return v;v[0]=a[0];double alpha=2d/(span+1);for(int i=1;i<a.Count;i++)v[i]=alpha*a[i]+(1-alpha)*v[i-1];return v;}
 public static double[] Atr(IReadOnlyList<SeedBar> bars){var a=new double[bars.Count];if(a.Length==0)return a;for(int i=0;i<a.Length;i++){double prev=i>0?bars[i-1].Close:bars[i].Close;double tr=Math.Max(bars[i].High-bars[i].Low,Math.Max(Math.Abs(bars[i].High-prev),Math.Abs(bars[i].Low-prev)));a[i]=i==0?tr:(13*a[i-1]+tr)/14;}return a;}
 public static SeedSignal? Evaluate(IReadOnlyList<SeedBar> m5,IReadOnlyList<SeedBar> h4,DateTime at){
  if(at.Kind!=DateTimeKind.Utc||at.Minute%5!=0||at.Second!=0||at.Ticks%TimeSpan.TicksPerSecond!=0||at.Hour>=20||at.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday)return null;
  var m=m5.Where(b=>b.At.AddMinutes(5)<=at).ToArray();var h=h4.Where(b=>b.At.AddHours(4)<=at).ToArray();
  if(m.Length<256||h.Length<1024||m[^1].At.AddMinutes(5)!=at||m[^1].Count!=5||h[^1].Count!=240||at-h[^1].At.AddHours(4)>TimeSpan.FromHours(8))return null;
  var fast=Ema(h.Select(x=>x.Close).ToArray(),20);var slow=Ema(h.Select(x=>x.Close).ToArray(),80);if(fast[^1]<=slow[^1])return null;
  var atr=Atr(m)[^1];var c=m[^1];double hi=m.Skip(m.Length-65).Take(64).Max(x=>x.High);
  if(!double.IsFinite(atr)||atr<=0||c.Close<=c.Open||c.Close<=hi+.05*atr)return null;
  return new(at,atr,c.Low-.05*atr);
 }
}
