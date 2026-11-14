using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
namespace Rizan.Portfolio;
public sealed record MacroDaily {
 public string Date{get;set;}=""; public DateTime AvailableUtc{get;set;}
 public double Dxy{get;set;} public double Us2{get;set;} public double Us10{get;set;} public double Real10{get;set;}
 public double DxyDelta1{get;set;} public double DxyDelta5{get;set;} public double DxyTrend20{get;set;}
 public double Us2Delta1{get;set;} public double Us2Delta5{get;set;} public double Us10Delta1{get;set;} public double Us10Delta5{get;set;} public double RealDelta1{get;set;} public double RealDelta5{get;set;}
}
// Research prototype. Production must receive independently authenticated point-in-time snapshots.
// It is fail-closed by default and cannot trade before Configure supplies a validated immutable timeline.
public static class MacroDirection {
 static MacroDaily[] rows=Array.Empty<MacroDaily>();static string mode="unconfigured";
 static bool scopeOn=true;static readonly List<object> transitions=new();
 static readonly Dictionary<string,int> counts=new();static readonly List<object> samples=new();
 public static bool Enabled=>mode!="off"&&scopeOn;
 public static string RootMode=>mode.StartsWith("seed_")?mode.Split('_')[1]:mode;
 public static double Threshold=>mode.StartsWith("seed_")?double.Parse(mode.Split('_')[2],System.Globalization.CultureInfo.InvariantCulture):0;
 public static bool ScopeFor(string cfg,double acknowledgedPeak)=>cfg!="off"&&(!cfg.StartsWith("seed_")||!double.IsFinite(acknowledgedPeak)||acknowledgedPeak<=0||acknowledgedPeak<double.Parse(cfg.Split('_')[2],System.Globalization.CultureInfo.InvariantCulture));
 public static void UpdateScope(double acknowledgedPeak,DateTime now){bool next=ScopeFor(mode,acknowledgedPeak);if(next!=scopeOn)transitions.Add(new{At=now,AcknowledgedPeak=acknowledgedPeak,Threshold,From=scopeOn,To=next});scopeOn=next;}
 public static void InitializeFrozenOff(){mode="off";scopeOn=false;rows=Array.Empty<MacroDaily>();counts.Clear();samples.Clear();transitions.Clear();}
 public static void Configure(string value,string path){
  mode=value;scopeOn=value!="off";counts.Clear();samples.Clear();transitions.Clear();
  if(rows.Length==0){rows=JsonSerializer.Deserialize<MacroDaily[]>(System.IO.File.ReadAllText(path))!;Validate(rows);}
 }
 public static void Validate(MacroDaily[] data){
  DateTime prior=DateTime.MinValue;
  foreach(var p in data){
   if(p.AvailableUtc<=prior||!DateTime.TryParse(p.Date,out var date)||p.AvailableUtc<date.Date.AddDays(1).AddHours(6)||!new[]{p.Dxy,p.Us2,p.Us10,p.Real10,p.DxyDelta1,p.DxyDelta5,p.DxyTrend20,p.Us2Delta1,p.Us2Delta5,p.Us10Delta1,p.Us10Delta5,p.RealDelta1,p.RealDelta5}.All(double.IsFinite)||p.Dxy<=0)throw new InvalidOperationException("INVALID_MACRO_TIMELINE");prior=p.AvailableUtc;
  }
 }
 public static MacroDaily? Point(DateTime at){int lo=0,hi=rows.Length;while(lo<hi){int mid=(lo+hi)/2;if(rows[mid].AvailableUtc<=at)lo=mid+1;else hi=mid;}return lo>0&&at-rows[lo-1].AvailableUtc<=TimeSpan.FromDays(7)?rows[lo-1]:null;}
 public static int Sign(double x,double band)=>x>=band-1e-9?1:x<= -band+1e-9?-1:0;
 public static bool SmallPhase(double reference,double peak)=>(mode.Contains("_r5")||mode.Contains("_r10"))&&Math.Max(reference,peak)<5000;
 static double SmallRisk=>mode.Contains("_r10")?.10:.05;
 public static ResearchCase Profile(ResearchCase c)=>mode.EndsWith("_e2")?c with{EurTarget=2,EurBE=1}:mode.EndsWith("_e4")?c with{EurTarget=4,EurBE=1.5}:c;
 public static double CapRisk(double reference,double peak,double original){
  if(!SmallPhase(reference,peak))return original;
  double fade=Math.Clamp((Math.Max(reference,peak)-1000)/4000,0,1);return Math.Min(original,reference*(SmallRisk+(.2075-SmallRisk)*fade));
 }
 public static bool Decide(string how,string symbol,int side,MacroDaily p){
  if(side is not(1 or -1))return false;
  int dx=Sign(p.DxyDelta1,.05),u2=Sign(p.Us2Delta1,1),u10=Sign(p.Us10Delta1,1),real=Sign(p.RealDelta1,1);
  int yield=symbol=="EURUSD"?u2:real;
  if(how.StartsWith("veto"))return !(side*dx>0&&side*yield>0);
  if(how.StartsWith("align"))return side*dx<0&&side*yield<=0;
  if(how.StartsWith("notcontrary"))return side*dx<=0&&side*yield<=0;
  if(how.StartsWith("dollar"))return side*dx<0;
  if(how.StartsWith("both5"))return side*Sign(p.DxyDelta5,.05)<0&&side*Sign(symbol=="EURUSD"?p.Us2Delta5:p.RealDelta5,1)<=0;

  int score;
  if(how.StartsWith("trend"))score=2*Sign(p.DxyTrend20,.05)+Sign(p.Us2Delta5,1)+Sign(p.Us10Delta5,1)+(symbol=="EURUSD"?0:Sign(p.RealDelta5,1));
  else score=2*dx+u2+u10+(symbol=="EURUSD"?0:real);
  return side*score<= -3;
 }
 public static bool Allow(string symbol,int side,DateTime signal,DateTime now){
  if(!Enabled)return true;var p=Point(signal);string why=signal>now?"FUTURE_SIGNAL":p==null?"MISSING_STALE":Decide(RootMode,symbol,side,p)?"PASS":"DIRECTION";
  string key=symbol+":"+why;counts[key]=counts.GetValueOrDefault(key)+1;
  if(samples.Count<2500)samples.Add(new{Symbol=symbol,Side=side,At=signal,Now=now,Point=p,Result=why});return why=="PASS";
 }
 public static object Audit()=>new{Mode=mode,DataPoints=rows.Length,ConservativeAvailability="observation date +1 calendar day 06UTC",OriginalVintageCertified=false,ScopeThreshold=Threshold,ScopeAtEnd=scopeOn,ScopeTransitions=transitions,Counts=counts,Samples=samples,SmallRiskFraction=SmallRisk};
}
