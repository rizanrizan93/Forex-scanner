using System;
using System.IO;
using System.Linq;
using System.Globalization;
using System.Collections.Generic;
using Rizan.Portfolio;
static class BtcMacroGate {
 record M(DateTime Observation,DateTime Available,double Delta);
 static M[] macro=Array.Empty<M>();static (DateTime Start,DateTime End)[] events=Array.Empty<(DateTime,DateTime)>();
 static DateTime D(string s)=>DateTime.Parse(s,CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal);
 public static void Load(string root){macro=File.ReadLines(Path.Combine(root,"real_yield.csv")).Skip(1).Select(l=>l.Split(',')).Where(p=>p[3]!="").Select(p=>new M(D(p[0]),D(p[1]),double.Parse(p[3],CultureInfo.InvariantCulture))).OrderBy(p=>p.Available).ToArray();events=File.ReadLines(Path.Combine(root,"fomc.csv")).Skip(1).Select(l=>l.Split(',')).Select(p=>(D(p[1]),D(p[2]))).ToArray();}
 public static (bool Macro,bool Event,DateTime Observation,DateTime Available,double Delta) Check(BtcSignal s){int lo=0,hi=macro.Length;while(lo<hi){int k=(lo+hi)/2;if(macro[k].Available<=s.At)lo=k+1;else hi=k;}var m=lo>0?macro[lo-1]:null;bool ok=m!=null&&(s.At-m.Observation).TotalDays<=10&&s.Side*m.Delta<=0;return(ok,!events.Any(e=>s.At>=e.Start&&s.At<e.End),m?.Observation??default,m?.Available??default,m?.Delta??double.NaN);}
 public static bool Allow(BtcSignal s,string mode){var g=Check(s);return mode=="BASE"||mode=="MACRO"&&g.Macro||mode=="EVENT"&&g.Event||mode=="BOTH"&&g.Macro&&g.Event;}
}
