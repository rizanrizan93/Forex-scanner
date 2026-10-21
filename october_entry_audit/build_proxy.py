from pathlib import Path
import difflib,hashlib,json
r=Path('october_entry_audit');baseline=Path('portfolio_7day_frozen/work/replay/Replay.cs').read_text();s=baseline
old='var btcSessionBars=bdata.Rows.Select(v=>new BtcBar(v.At,v.Open,v.High,v.Low,v.Close)).ToList();var btape=BtcCore.Signals(BtcCore.Aggregate(btcSessionBars,60),BtcCore.Aggregate(btcSessionBars,240));'
new='var seed=File.ReadLines(Environment.GetEnvironmentVariable("BTC_H1_INPUT")!).Skip(1).Select(line=>{var p=line.Split(\',\');return new BtcBar(DateTimeOffset.FromUnixTimeSeconds(long.Parse(p[0])).UtcDateTime,double.Parse(p[1],CultureInfo.InvariantCulture),double.Parse(p[2],CultureInfo.InvariantCulture),double.Parse(p[3],CultureInfo.InvariantCulture),double.Parse(p[4],CultureInfo.InvariantCulture),int.Parse(p[5]));}).Where(b=>b.At.AddHours(1)<=new DateTime(2026,10,20,17,0,0,DateTimeKind.Utc)).ToList();var btape=BtcCore.Signals(seed,BtcCore.Aggregate(seed,240).Where(b=>b.At.AddHours(4)<=new DateTime(2026,10,20,17,0,0,DateTimeKind.Utc)).ToList());'
assert s.count(old)==1;s=s.replace(old,new)
old='new DateTime(Period.StartYear,1,1,0,0,0,DateTimeKind.Utc)';assert s.count(old)==3
s=s.replace(old,'DateTime.Parse(Environment.GetEnvironmentVariable("AUDIT_START_UTC")!,CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal)')
old='.Where(t=>t.Year>=Period.StartYear).Distinct()';assert s.count(old)==1
s=s.replace(old,'.Where(t=>t>=DateTime.Parse(Environment.GetEnvironmentVariable("AUDIT_START_UTC")!,CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal)).Distinct()')
# Observe existing gate results without changing control flow.
s=s.replace(' public object? Summary;',' readonly List<object> EntryAudit=new();\n public object? Summary;')
s=s.replace('l.Call("PrepareBasket",point.Signal,phaseTime);if(l.Basket!=null)', 'l.Call("PrepareBasket",point.Signal,phaseTime);EntryAudit.Add(new{At=at,Symbol=l.Symbol,Status=(string)l.Type.GetField("_status",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(l.Context)!,BasketPrepared=l.Basket!=null,Balance=host.Account.Balance,Equity=host.Account.Equity});if(l.Basket!=null)')
s=s.replace('return new{Summary,CashFlows=', 'return new{Summary,EntryAudit,CashFlows=')
# Persist exact warmed tapes for candidate diagnostics. No signal rule changes.
(r/'ProxyReplay.cs').write_text(s)
(r/'PROXY_HARNESS.diff').write_text(''.join(difflib.unified_diff(baseline.splitlines(True),s.splitlines(True),fromfile='Frozen/Replay.cs',tofile='Research/ProxyReplay.cs')))
source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('portfolio_7day_frozen/work/source').rglob('*.cs')}
Path('publish/SOURCE_UNCHANGED.json').write_text(json.dumps({'strategy_files_unchanged':True,'files':source,'changes':'Harness execution start date and BTC indicator transport only; source strategies byte unchanged.'},indent=2))
