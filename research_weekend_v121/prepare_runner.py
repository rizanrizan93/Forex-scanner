"""Research overlays only; frozen package and trading source are never edited."""
from pathlib import Path
import zipfile,shutil,difflib,json
r=Path(__file__).resolve().parent;base=r.parent/'portfolio_weekend';w=r/'work'
with zipfile.ZipFile(base/'RIZAN_XAU_EUR_BTC_FROZEN_WEEKEND_V121.zip') as z:z.extractall(w)
p=w/'replay/Replay.cs';before=p.read_text();s=before
s=s.replace('bdata.Rows.Where(v=>BrokerCalendar.Open(v.At))','bdata.Rows.Where(v=>Environment.GetEnvironmentVariable("BTC_FULL_INDICATORS")=="1"||BrokerCalendar.Open(v.At))')
a=s.index('var scenarios=new[]');b=s.index('var reports=new List<object>();',a)
s=s[:a]+'''double cost=double.Parse(Environment.GetEnvironmentVariable("RESEARCH_COST")??"1",CultureInfo.InvariantCulture);
string path=Environment.GetEnvironmentVariable("RESEARCH_PATH")??"A";
var scenarios=new[]{new Scenario(Environment.GetEnvironmentVariable("RESEARCH_CASE")??"REPRO",200,cost,2,path=="A",20.75,true,true,false,maxYear,Environment.GetEnvironmentVariable("RESEARCH_CONTROL")!="1")};
'''+s[b:]
s=s.replace('.Spread*cfg.Cost','.Spread')
s=s.replace('host.Symbols.GetSymbol("BTCUSD").Leverage=10','host.Symbols.GetSymbol("BTCUSD").Leverage=double.Parse(Environment.GetEnvironmentVariable("RESEARCH_BTC_LEVERAGE")??"10",CultureInfo.InvariantCulture)')
s=s.replace('for(int step=0;step<2;step++)','int delay=Environment.GetEnvironmentVariable("RESEARCH_NEXT_M1")=="1"?60-_clock.Second:2;for(int step=0;step<delay;step++)')
s=s.replace('BrokerEntryDelaySeconds=2,','BrokerEntryDelaySeconds=Environment.GetEnvironmentVariable("RESEARCH_NEXT_M1")=="1"?-1:2,DelayPolicy=Environment.GetEnvironmentVariable("RESEARCH_NEXT_M1")=="1"?"broker fills at next M1 open for each market request; ACK remains 2 seconds":"broker 2 seconds",SpreadStressMultiplier=1,BtcLeverage=host.Symbols.GetSymbol("BTCUSD").Leverage,')
s=s.replace('public static bool Open(DateTime t)=>','public static bool Open(DateTime t)=>Environment.GetEnvironmentVariable("BTC_SEVEN_DAY")=="1"||')
p.write_text(s)
# Record BTC signal inputs, before portfolio consumption, for indicator comparison.
s=s.replace('var xdata=Data.Load(args[0],true,maxYear);','File.WriteAllText(args[2]+".btc_signals.json",JsonSerializer.Serialize(btape));var xdata=Data.Load(args[0],true,maxYear);');p.write_text(s)
(r/'RUNNER_CHANGE.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True),s.splitlines(True),fromfile='frozen/replay/Replay.cs',tofile='research/replay/Replay.cs')))
# Legacy engine is an explicit diagnostic variant, never compiled into a distributable cBot.
old=r/'legacy_work';shutil.copytree(w,old,dirs_exist_ok=True)
z=zipfile.ZipFile(r.parent/'portfolio_three/RIZAN_XAU_EUR_BTC_INTEGRATED_AUDIT_2019_2026.zip')
(old/'source/BtcEngine.cs').write_bytes(z.read('source/BtcEngine.cs'))
# Host timer accesses a method introduced in weekend version; keep harmless adapter for compilation.
f=old/'source/BtcEngine.cs';t=f.read_text();t=t.replace('internal void ReplayStart()', 'internal void InvalidateSchedule(){}\n    internal void ReplayStart()');f.write_text(t)
print(json.dumps({'work':str(w),'legacy':str(old),'strategy_source':'unchanged in stress/control work','cost':'commission/slippage/funding multiplied; spreads unchanged','xau_eur_leverage':200,'btc_leverage_default':10},indent=2))
