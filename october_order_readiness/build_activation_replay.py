from pathlib import Path
import difflib,hashlib,json
r=Path('october_order_readiness');baseline=Path('portfolio_7day_frozen/work/replay/Replay.cs').read_text();s=baseline
old='var btcSessionBars=bdata.Rows.Select(v=>new BtcBar(v.At,v.Open,v.High,v.Low,v.Close)).ToList();var btape=BtcCore.Signals(BtcCore.Aggregate(btcSessionBars,60),BtcCore.Aggregate(btcSessionBars,240));'
new='var seed=File.ReadLines(Environment.GetEnvironmentVariable("BTC_H1_INPUT")!).Skip(1).Select(line=>{var p=line.Split(\',\');return new BtcBar(DateTimeOffset.FromUnixTimeSeconds(long.Parse(p[0])).UtcDateTime,double.Parse(p[1],CultureInfo.InvariantCulture),double.Parse(p[2],CultureInfo.InvariantCulture),double.Parse(p[3],CultureInfo.InvariantCulture),double.Parse(p[4],CultureInfo.InvariantCulture),int.Parse(p[5]));}).Where(b=>b.At.AddHours(1)<=Audit.End).ToList();var btape=BtcCore.Signals(seed,BtcCore.Aggregate(seed,240).Where(b=>b.At.AddHours(4)<=Audit.End).ToList());'
assert s.count(old)==1;s=s.replace(old,new)
# Initial capital is explicit, and all account/cash/DD seeds change together in wrapper only.
s=s.replace('host.EnableBtc=c.Btc;', 'host.Account.Balance=host.Account.Equity=Audit.Initial;lastCash=peak=closedPeak=minimumEquity=navPeak=Audit.Initial;host.EnableBtc=c.Btc;')
s=s.replace('double previous=100;', 'double previous=Audit.Initial;').replace('Math.Abs(100+cashFlows.Sum', 'Math.Abs(Audit.Initial+cashFlows.Sum')
old='new DateTime(Period.StartYear,1,1,0,0,0,DateTimeKind.Utc)';assert s.count(old)==3;s=s.replace(old,'Audit.Start')
old='.Where(t=>t.Year>=Period.StartYear).Distinct()';assert s.count(old)==1;s=s.replace(old,'.Where(t=>t>=Audit.Start && t<Audit.End).Distinct()')
s=s.replace('public static int StartYear=2012;', 'public static int StartYear=2012;')
s=s.replace('if(at.Year>maxYear)break;', 'if(at.Year>maxYear||at>=Audit.End)break;')
s=s.replace('public static Data LoadBtc(string path){var rows=new List<Row>();foreach(var line in File.ReadLines(path).Skip(1)){var p=line.Split(\',\');rows.Add(new(DateTime.Parse', 'public static Data LoadBtc(string path){var rows=new List<Row>();foreach(var line in File.ReadLines(path).Skip(1)){var p=line.Split(\',\');if(DateTime.Parse(p[0],CultureInfo.InvariantCulture,DateTimeStyles.AdjustToUniversal|DateTimeStyles.AssumeUniversal)>=Audit.End)break;rows.Add(new(DateTime.Parse')
# Entry activation times are external observations; price warmup remains prior to activation.
old='l.Call("PrepareBasket",point.Signal,phaseTime);if(l.Basket!=null)'
new='if(at<(l.IsXau?Audit.XauFrom:Audit.EurFrom))continue;l.Call("PrepareBasket",point.Signal,phaseTime);EntryAudit.Add(new{At=at,Symbol=l.Symbol,Status=(string)l.Type.GetField("_status",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(l.Context)!,BasketPrepared=l.Basket!=null,Balance=host.Account.Balance,Equity=host.Account.Equity});if(l.Basket!=null)'
assert s.count(old)==1;s=s.replace(old,new)
s=s.replace(' public object? Summary;',' readonly List<object> EntryAudit=new();\n public object? Summary;')
s=s.replace('return new{Summary,CashFlows=', 'return new{Summary,EntryAudit,CashFlows=')
# Retain real raw candidates separately, including those not accepted as baskets.
needle='Console.WriteLine($"TAPES XAU={xtape.Signals.Count} EUR={etape.Signals.Count}");'
extra='''
var rawSignals=new List<object>();
foreach(var v in xtape.Signals.Where(x=>x.Key>=Audit.XauFrom && x.Key>=Audit.Start && x.Key<Audit.End)){var q=(X.Signal)v.Value.Signal;rawSignals.Add(new{utc=v.Key,symbol="XAUUSD",direction=q.Side==1?"BUY":"SELL",q.Atr,q.Anchor,macro_eligibility_reconstructed=false});}
foreach(var v in etape.Signals.Where(x=>x.Key>=Audit.EurFrom && x.Key>=Audit.Start && x.Key<Audit.End)){var q=(E.Signal)v.Value.Signal;rawSignals.Add(new{utc=v.Key,symbol="EURUSD",direction=q.Side==1?"BUY":"SELL",q.Distance,v.Value.Fast,v.Value.Slow});}
if(Environment.GetEnvironmentVariable("RESEARCH_CONTROL")!="1")foreach(var v in btape.Where(x=>x.Key>=Audit.Start && x.Key<Audit.End)){var q=v.Value;rawSignals.Add(new{utc=v.Key,symbol="BTCUSD",direction=q.Side==1?"BUY":"SELL",q.Atr,q.Reference});}
File.WriteAllText(args[2]+".raw_candidates.json",JsonSerializer.Serialize(rawSignals,new JsonSerializerOptions{WriteIndented=true}));
'''
assert s.count(needle)==1;s=s.replace(needle,needle+extra)
s+='''\nstatic class Audit {public static DateTime Parse(string name)=>DateTime.Parse(Environment.GetEnvironmentVariable(name)!,CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal);public static DateTime Start=>Parse("AUDIT_START_UTC");public static DateTime End=>Parse("AUDIT_END_UTC");public static DateTime XauFrom=>Parse("AUDIT_XAU_FROM");public static DateTime EurFrom=>Parse("AUDIT_EUR_FROM");public static double Initial=>double.Parse(Environment.GetEnvironmentVariable("AUDIT_INITIAL")??"115.17",CultureInfo.InvariantCulture);}\n'''
(r/'ActivationReplay.cs').write_text(s);(r/'ACTIVATION_HARNESS.diff').write_text(''.join(difflib.unified_diff(baseline.splitlines(True),s.splitlines(True),fromfile='Frozen/Replay.cs',tofile='Research/ActivationReplay.cs')))
m=json.loads(Path('portfolio_7day_frozen/FREEZE_MANIFEST.json').read_text());checks={n:hashlib.sha256((Path('portfolio_7day_frozen')/n).read_bytes()).hexdigest()==h for n,h in m['source_sha256'].items()};assert all(checks.values());Path('publish/SOURCE_UNCHANGED.json').write_text(json.dumps(checks,indent=2))
