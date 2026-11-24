using System;
using System.Collections.Generic;
using System.Linq;
// Replay-only policy: no changes to the released algo.
// Track basket settlements, not child orders. Strictly earlier exits only.
internal static class EarlyRiskPolicy {
 static readonly Dictionary<string,List<(DateTime At,double Pnl)>> history=new();
 static int mask,look;static double threshold,factor,limit;
 internal static void Configure(int m,int l,double t,double f,double cap){
  if(m<0||m>7||l<1||l>64||!double.IsFinite(t)||t<0||t>1||!double.IsFinite(f)||f<=0||f>1||!double.IsFinite(cap)||cap<125)
   throw new InvalidOperationException("INVALID_EARLY_RISK_POLICY");
  mask=m;look=l;threshold=t;factor=f;limit=cap;history.Clear();
 }
 internal static void Record(string symbol,DateTime exit,double pnl){
  if(mask==0)return;
  if(!double.IsFinite(pnl))throw new InvalidOperationException("NONFINITE_SETTLEMENT");
  if(!history.TryGetValue(symbol,out var h))history[symbol]=h=new();
  h.Add((exit,pnl));
 }
 internal static double Factor(string symbol,DateTime at,double balance){
  int bit=symbol=="EURUSD"?1:symbol=="XAUUSD"?2:symbol=="BTCUSD"?4:0;
  if((mask&bit)==0||balance>=limit||!history.TryGetValue(symbol,out var h))return 1;
  var prior=h.Where(x=>x.At<at).OrderBy(x=>x.At).TakeLast(look).ToArray();
  return prior.Length==look&&prior.Count(x=>x.Pnl>0)/(double)look<threshold?factor:1;
 }
 internal static void SelfTest(){
  var t=new DateTime(2019,1,1,0,0,0,DateTimeKind.Utc);
  Configure(7,4,.5,.25,1000);
  for(int i=0;i<4;i++)Record("XAUUSD",t.AddMinutes(i),i==0?1:-1);
  if(Factor("XAUUSD",t.AddMinutes(3),200)!=1||Factor("XAUUSD",t.AddMinutes(4),200)!=.25||
     Factor("XAUUSD",t.AddMinutes(4),1000)!=1||Factor("EURUSD",t.AddMinutes(4),200)!=1)
   throw new Exception("EARLY_RISK_CAUSAL_SCOPE");
  Record("XAUUSD",t.AddDays(1),10000);
  if(Factor("XAUUSD",t.AddMinutes(4),200)!=.25)throw new Exception("FUTURE_SETTLEMENT_LEAK");
  Configure(0,8,.5,.25,1000);if(Factor("XAUUSD",t.AddDays(2),200)!=1)throw new Exception("CONTROL_CHANGED");
  Console.WriteLine("PASS native early sizing: completed basket causality, symbol separation, threshold, reset, neutral default");
 }
}
