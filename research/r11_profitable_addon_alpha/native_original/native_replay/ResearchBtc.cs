using Rizan.Portfolio;
using System.Text.Json;
static class ResearchBtc {
 public static Dictionary<DateTime,BtcSignal> Attach(Data data,Dictionary<DateTime,BtcSignal> primary,string output,bool export){
  var q=BtcCore.Aggregate(data.Rows.Select(r=>new BtcBar(r.At,r.Open,r.High,r.Low,r.Close)).ToList(),240);
  int before=primary.Count;EntryFamilies.MergeBtc(primary,q);
  Console.WriteLine("NATIVE_SOURCE_BTC_TAPE primary="+before+" total="+primary.Count);
  return primary;
 }
}
