using System.Text.Json;
using Rizan.Portfolio;
int checks=0;void Check(bool x,string name){checks++;if(!x)throw new Exception(name);}
Check(BtcEntryGate.BuyAllowed(.2,192),"BUY_THRESHOLD_INCLUSIVE");
Check(!BtcEntryGate.BuyAllowed(.199999999,240),"BUY_BELOW_THRESHOLD");
Check(!BtcEntryGate.BuyAllowed(.3,191),"BUY_COVERAGE");
Check(!BtcEntryGate.BuyAllowed(double.NaN,240),"BUY_NAN");
Check(BtcEntryGate.SellAllowed(30,48),"SELL_THRESHOLD_INCLUSIVE");
Check(!BtcEntryGate.SellAllowed(29.999999999,60),"SELL_BELOW_THRESHOLD");
Check(!BtcEntryGate.SellAllowed(40,47),"SELL_COVERAGE");
var flat=Enumerable.Range(0,21).Select(i=>new BtcBar(DateTime.UnixEpoch.AddHours(4*i),100,100,100,100,240)).ToList();
Check(double.IsNaN(BtcEntryGate.Efficiency(flat,20)),"FLAT_UNDEFINED");
var rising=flat.Select((b,i)=>b with{Close=100+i}).ToList();Check(BtcEntryGate.Efficiency(rising,20)==1,"MONOTONIC_EFFICIENCY");
Check(double.IsNaN(BtcEntryGate.Efficiency(rising,19)),"FULL_LOOKBACK_REQUIRED");
using var feed=JsonDocument.Parse(File.ReadAllText(args[0]));
var h=feed.RootElement.GetProperty("bars").EnumerateArray().Select(r=>{var v=r.EnumerateArray().ToArray();return new BtcBar(DateTimeOffset.FromUnixTimeSeconds(v[0].GetInt64()).UtcDateTime,v[1].GetDouble(),v[2].GetDouble(),v[3].GetDouble(),v[4].GetDouble(),v[5].GetInt32());}).ToList();
var cutoff=DateTime.Parse("2026-10-09T21:59:00Z").ToUniversalTime();
var actual=BtcCore.Signals(h,BtcCore.Aggregate(h,240)).Values.Where(s=>s.At<=cutoff).OrderBy(s=>s.At).ToList();
using var expected=JsonDocument.Parse(File.ReadAllText(args[1]));
var points=expected.RootElement.GetProperty("BTC10").EnumerateArray().OrderBy(p=>p.GetProperty("At").GetDateTime()).ToList();
Check(actual.Count==points.Count,"HISTORICAL_SIGNAL_COUNT");
for(int i=0;i<actual.Count;i++){var p=points[i];Check(actual[i].At==p.GetProperty("At").GetDateTime()&&actual[i].Side==p.GetProperty("Side").GetInt32(),"HISTORICAL_TIME_AND_SIDE_"+i);Check(Math.Abs(actual[i].Atr-p.GetProperty("Atr").GetDouble())<1e-7,"HISTORICAL_ATR_"+i);}
foreach(var date in new[]{new DateTime(2022,6,1,0,0,0,DateTimeKind.Utc),new DateTime(2024,6,3,0,0,0,DateTimeKind.Utc)}){
 var prefix=h.Where(b=>b.At.AddHours(1)<=date).ToList();var shortSignals=BtcCore.Signals(prefix,BtcCore.Aggregate(prefix,240));
 Check(actual.Where(s=>s.At<date).All(s=>shortSignals.TryGetValue(s.At,out var p)&&p==s),"CAUSAL_PREFIX");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,HistoricalSignals=actual.Count,ExactTimesAndSides=true,RealOrders=0}));
