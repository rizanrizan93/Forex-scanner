using System;using System.Linq;using Rizan.Portfolio;
static class GateTests {
 static int tests;static void A(bool b,string name){tests++;if(!b)throw new Exception(name);}
 public static void Main(string[] args){BtcMacroGate.Load(args[0]);BtcSignal S(string at,int side=1)=>new(DateTime.Parse(at).ToUniversalTime(),side,1,1);
 A(BtcMacroGate.Check(S("2020-03-03T15:00:00Z")).Event,"public timestamp allowed during assumed 1min ingestion lag");
 A(!BtcMacroGate.Check(S("2020-03-03T15:01:00Z")).Event,"emergency post-release block");
 A(BtcMacroGate.Check(S("2020-03-03T14:59:59Z")).Event,"no hindsight pre-emergency block");
 A(BtcMacroGate.Check(S("2020-03-04T15:00:00Z")).Event,"24h end exclusive");
 A(!BtcMacroGate.Check(S("2020-03-15T21:01:00Z")).Event,"emergency Sunday EDT");
 A(!BtcMacroGate.Check(S("2024-03-20T18:01:00Z")).Event,"regular EDT");
 A(!BtcMacroGate.Check(S("2024-01-31T19:01:00Z")).Event,"regular EST");
 foreach(var date in new[]{"2019-01-01T00:00:00Z","2020-12-28T00:00:00Z","2026-10-09T21:00:00Z"}){
  var s=S(date);var g=BtcMacroGate.Check(s);A(g.Available<=s.At,"future availability");A(g.Observation<g.Available,"observation before lag");A(BtcMacroGate.Allow(s,"BASE"),"baseline passes");A(BtcMacroGate.Allow(s,"BOTH")== (g.Macro&&g.Event),"both conjunction");
  var sell=BtcMacroGate.Check(s with{Side=-1});A(g.Delta==0||g.Macro!=sell.Macro,"macro direction symmetric");
 }
 Console.WriteLine("{\"passed\":"+tests+",\"failed\":0}");}
}
