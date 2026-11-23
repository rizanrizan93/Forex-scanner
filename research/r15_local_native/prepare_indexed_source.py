"""Index-only replay adapter. Preserve original iteration order and source files."""
from pathlib import Path
import subprocess,sys,json,hashlib
root=Path(__file__).resolve().parents[2]
subprocess.run([sys.executable,str(Path(__file__).with_name('prepare_guard_source.py'))],check=True)
out=root/'artifacts/r15/guard_source'
def replace(path,a,b):
 p=out/path;s=p.read_text();assert s.count(a)==1,(path,a,s.count(a));p.write_text(s.replace(a,b))
replace(Path('native_replay/ApiStubs.cs'),'List<HistoricalTrade> History','IndexedHistory History')
(out/'native_replay/IndexedHistory.cs').write_text('''using System;using System.Collections.Generic;using System.Linq;
namespace cAlgo.API {
public sealed class IndexedHistory:List<HistoricalTrade>{
 readonly Dictionary<(string,string),List<HistoricalTrade>> labels=new(),baskets=new();
 readonly Dictionary<string,List<HistoricalTrade>> symbols=new(),families=new();
 static void Push<K>(Dictionary<K,List<HistoricalTrade>> d,K k,HistoricalTrade h) where K:notnull {if(!d.TryGetValue(k,out var v))d[k]=v=new();v.Add(h);}
 public new void Add(HistoricalTrade h){base.Add(h);Push(labels,(h.SymbolName,h.Label),h);Push(symbols,h.SymbolName,h);var p=h.Label.Split('|');Push(families,p[0],h);if(p.Length>=2)Push(baskets,(h.SymbolName,p[0]+"|"+p[1]+"|"),h);}
 public IEnumerable<HistoricalTrade> ByLabel(string symbol,string label)=>labels.TryGetValue((symbol,label),out var v)?v:Array.Empty<HistoricalTrade>();
 public IEnumerable<HistoricalTrade> ByBasket(string symbol,string prefix)=>baskets.TryGetValue((symbol,prefix),out var v)?v:Array.Empty<HistoricalTrade>();
 public IEnumerable<HistoricalTrade> BySymbol(string symbol)=>symbols.TryGetValue(symbol,out var v)?v:Array.Empty<HistoricalTrade>();
 public IEnumerable<HistoricalTrade> ByFamily(string family)=>families.TryGetValue(family,out var v)?v:Array.Empty<HistoricalTrade>();
}}
''')
replace(Path('source/BtcNativeLifecycle.cs'),'History.Where(p=>p.SymbolName==Instrument&&p.Label==label)','Host.History.ByLabel(Instrument,label)')
for name in ('xau','eur'):
 replace(Path(f'source/{name}/RizanRobot.cs'),'History.Where(x=>x.Label==_state.PendingLabel&&x.SymbolName==SymbolName)','Host.History.ByLabel(SymbolName,_state.PendingLabel)')
replace(Path('source/xau/RizanRobot.cs'),'History.Where(t=>t.SymbolName==SymbolName && (t.Label==r.Label || t.PositionId==r.PositionId))','Host.History.BySymbol(SymbolName).Where(t=>t.SymbolName==SymbolName && (t.Label==r.Label || t.PositionId==r.PositionId))')
replace(Path('source/xau/RizanRobot.cs'),'History.Where(t=>t.SymbolName==SymbolName && t.Label.StartsWith(Prefix+"|"+b.AtUtc.Ticks+"|",StringComparison.Ordinal))','Host.History.ByBasket(SymbolName,Prefix+"|"+b.AtUtc.Ticks+"|")')
replace(Path('native_replay/Replay.cs'),'host.History.Where(h=>h.SymbolName==l.Symbol&&h.Label.StartsWith(label,StringComparison.Ordinal))','host.History.ByBasket(l.Symbol,label)')
replace(Path('native_replay/Replay.cs'),'host.History.Where(p=>p.SymbolName==l.Symbol&&p.Label.StartsWith(l.Prefix+"|"+((DateTime)basket.AtUtc).Ticks+"|",StringComparison.Ordinal))','host.History.ByBasket(l.Symbol,l.Prefix+"|"+((DateTime)basket.AtUtc).Ticks+"|")')
for filename,family in [('SeedController.cs','RZSEED'),('XauAddonController.cs','RZADDON')]:
 replace(Path('native_replay')/filename,f'host.History.Where(h=>h.Label.StartsWith("{family}|")&&!recorded.Contains(h.PositionId))',f'host.History.ByFamily("{family}").Where(h=>!recorded.Contains(h.PositionId))')
# Use current simulation time after any native close/ACK work for guard admission.
replace(Path('native_replay/Replay.cs'),'growthGuard.Allow(l.Symbol,phaseTime,trades)','growthGuard.Allow(l.Symbol,host.Server.TimeInUtc,trades)')
replace(Path('native_replay/Replay.cs'),'BrokerCalendar.CloseHour=int.Parse(', 'if(Environment.GetEnvironmentVariable("R15_INDEX_SELFTEST")=="1"){IndexSelfTest.Run();return;}\nBrokerCalendar.CloseHour=int.Parse(')
(out/'native_replay/IndexSelfTest.cs').write_text(r'''using System;using System.Linq;using System.Collections.Generic;using cAlgo.API;
static class IndexSelfTest {
 public static void Run(){
  var h=new IndexedHistory();var rng=new Random(15);string[] syms={"XAUUSD","EURUSD","BTCUSD"};
  for(int i=0;i<1000;i++){var sym=syms[rng.Next(3)];var label="RZ"+rng.Next(3)+"|"+rng.Next(7)+"|"+rng.Next(4);h.Add(new HistoricalTrade{SymbolName=sym,Label=label,PositionId=i+1});}
  void Equal(IEnumerable<HistoricalTrade> a,IEnumerable<HistoricalTrade> b){if(!a.Select(x=>x.PositionId).SequenceEqual(b.Select(x=>x.PositionId)))throw new Exception("INDEX_ORDER_OR_CONTENT_MISMATCH");}
  foreach(var sym in syms){Equal(h.BySymbol(sym),h.Where(x=>x.SymbolName==sym));for(int f=0;f<3;f++)for(int t=0;t<7;t++){var prefix="RZ"+f+"|"+t+"|";Equal(h.ByBasket(sym,prefix),h.Where(x=>x.SymbolName==sym&&x.Label.StartsWith(prefix,StringComparison.Ordinal)));for(int c=0;c<4;c++){var label=prefix+c;Equal(h.ByLabel(sym,label),h.Where(x=>x.SymbolName==sym&&x.Label==label));}}}
  for(int f=0;f<3;f++){var family="RZ"+f;Equal(h.ByFamily(family),h.Where(x=>x.Label.StartsWith(family+"|")));}
  if(h.ByLabel("MISSING","NONE").Any())throw new Exception("INDEX_MISSING");
  Environment.SetEnvironmentVariable("R15_GROWTH_GUARD","1");var at=new DateTime(2020,1,1,0,0,0,DateTimeKind.Utc);var g=new NativeGrowthGuard();var rows=new List<Trade>();
  for(int i=0;i<4;i++)rows.Add(new Trade(at,at.AddHours(i),"XAUUSD",-1,100,1,100,1));
  if(g.Allow("XAUUSD",at.AddHours(3),rows)||!g.Allow("EURUSD",at.AddHours(3),rows)||!g.Allow("XAUUSD",at.AddHours(27),rows))throw new Exception("GUARD_PAUSE_OR_SCOPE");
  var future=new NativeGrowthGuard();bool caught=false;try{future.Allow("XAUUSD",at,new List<Trade>{new Trade(at,at.AddHours(1),"XAUUSD",-1,100,1,100,1)});}catch(Exception e){caught=e.Message=="FUTURE_GUARD_SETTLEMENT";}if(!caught)throw new Exception("GUARD_FUTURE_NOT_DETECTED");
  Console.WriteLine("R15_INDEX_AND_GUARD_SELFTEST_PASS order, exact label, basket, symbol, family, pause scope/expiry, future settlement");
 }
}
''')
receipt={'scope':'Indexed replay history only, chronological list order retained. Optional GROWTH guard same policy; admission clock=current host clock. Original source files untouched. Must match all control ledger streams before economic use.','files':{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.cs')},'production_changes':False}
(root/'artifacts/r15/indexed_source_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print('R15_INDEXED_COPY_PREPARED')
