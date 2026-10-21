using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;
var cases=JsonDocument.Parse(File.ReadAllText("publish/MACRO_GATE_INPUT.json")).RootElement;
var tapes=JsonDocument.Parse(File.ReadAllText("research_reports/october-order-readiness-20261021/ACTIVATION_RAW_CANDIDATES.json")).RootElement;
var selected=tapes.EnumerateArray().First(x=>x.GetProperty("case").GetString()=="FX_CHECKPOINT_EPOCHS_TECH_ALLOWED_A").GetProperty("candidates").EnumerateArray().ToDictionary(x=>DateTime.Parse(x.GetProperty("utc").GetString()!).ToUniversalTime(),x=>x.Clone());
var rows=new List<object>();
foreach(var c in cases.EnumerateArray()){
 var at=DateTime.Parse(c.GetProperty("signal_utc").GetString()!).ToUniversalTime();var price=selected[at];var h=new Host{EnableTrading=false,EnableXau=true,EnableEur=false,EnableBtc=false};h.CreateEngines();var x=h.Xau!;h.Server.TimeInUtc=at;
 var snap=JsonSerializer.Deserialize<X.ExternalSnapshot>(c.GetProperty("snapshot").GetRawText())!;typeof(X.RizanRobot).GetField("_snapshot",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(x,snap);
 var signal=new X.Signal(at,-1,0,price.GetProperty("Atr").GetDouble(),price.GetProperty("Anchor").GetDouble());
 bool passed=(bool)typeof(X.RizanRobot).GetMethod("ExternalOk",BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(x,new object[]{signal,at})!;
 string status=(string)typeof(X.RizanRobot).GetField("_status",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(x)!;string name=c.GetProperty("name").GetString()!;
 if(name=="POSITIVE_YIELD_CONTROL"&&!passed)throw new Exception("POSITIVE_CONTROL_FAILED");if(h.Requests!=0)throw new Exception("UNEXPECTED_FAKE_ORDER");
 var row=new{name,signal_utc=at,signal_wib=at.AddHours(7).ToString("yyyy-MM-dd HH:mm:ss"),direction="SELL",macro_passed=passed,status=passed?"MACRO_OK":status,dgs10=snap.Dgs10,dfii10=snap.Dfii10,scope=c.GetProperty("scope").GetString(),historical_terminal_delivery_proven=false,live_orders=0};rows.Add(row);Console.WriteLine("MACRO_NATIVE_GATE "+JsonSerializer.Serialize(row));
}
File.WriteAllText("publish/MACRO_NATIVE_GATE_RESULTS.json",JsonSerializer.Serialize(rows,new JsonSerializerOptions{WriteIndented=true}));
sealed class Host:RizanPortfolio{}
