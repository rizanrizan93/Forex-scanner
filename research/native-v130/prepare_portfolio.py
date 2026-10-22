"""Subscribe the third broker symbol to native M1 data in multi-symbol backtests."""
from pathlib import Path
import sys,json,hashlib,difflib
work=Path(sys.argv[1]);source=work/'source';p=source/'PortfolioHost.cs';s=p.read_text()
a='    internal XauEngine? Xau { get; private set; }';assert s.count(a)==1
s=s.replace(a,'    private cAlgo.API.Bars? _nativeBtcBrokerM1;\n'+a)
a='        BridgeUrl=""; BridgeToken=""; BtcBridgeUrl=""; BtcBridgeToken="";';assert s.count(a)==1
s=s.replace(a,a+'\n        if(EnableBtc)_nativeBtcBrokerM1=MarketData.GetBars(TimeFrame.Minute,"BTCUSD");')
s=s.replace('_nextTelemetry=Server.TimeInUtc.AddMinutes(1);','_nextTelemetry=Server.TimeInUtc.AddMinutes(60);')
p.write_text(s)
for name in ('eur/RizanRobot.cs','xau/RizanRobot.cs'):
 p=source/name;s=p.read_text()
 needle='        Print("RIZAN_STARTUP_OK version=1.2.0_F0245; status={0}; storageKeyLength={1}",_status,_storageKey.Length);'
 if needle not in s:
  candidates=[v for v in s.splitlines() if 'Print("RIZAN_STARTUP_OK' in v]
  assert len(candidates)==1
  needle=candidates[0]
 s=s.replace(needle,'        Print("NATIVE_WARMUP symbol={0} at={1:O} count={2} first={3:O} last={4:O}",SymbolName,Server.TimeInUtc,_m1.Count,_m1.OpenTimes[0],_m1.OpenTimes[_m1.Count-1]);\n'+needle)
 needle='        Print("RIZAN_TRANSPORT symbol={0}; bridge={1}; continuity={2}; local_revision={3}",SymbolName,_bridgeReady,_continuityReady,_localRevision);'
 assert s.count(needle)==1
 s=s.replace(needle,needle+'\n        if(now.Minute==0)Print("NATIVE_DATA_STATE symbol={0} at={1:O} native_count={2} native_first={3:O} native_last={4:O} consumed_closed={5:O} bid={6} ask={7}",SymbolName,now,_m1.Count,_m1.OpenTimes[0],_m1.OpenTimes[_m1.Count-1],_state.LastBarUtc,Symbol.Bid,Symbol.Ask);')
 s=s.replace('_nextTelemetry=now.AddMinutes(1);','_nextTelemetry=now.AddMinutes(60);')
 p.write_text(s)
manifest_path=work/'NATIVE_ADAPTER_MANIFEST.json';m=json.loads(manifest_path.read_text());m['source']['PortfolioHost.cs']['after']=hashlib.sha256((source/'PortfolioHost.cs').read_bytes()).hexdigest();
for name in ('eur/RizanRobot.cs','xau/RizanRobot.cs'):m['source'][name]['after']=hashlib.sha256((source/name).read_bytes()).hexdigest()
m['multi_symbol_market_data']='Subscribe BTCUSD broker M1 bars; EUR/XAU already subscribe in their unchanged startup path.';manifest_path.write_text(json.dumps(m,indent=2))
frozen_source=Path('frozen/portfolio_7day_frozen/work/source');diffs=[]
for path in sorted(source.rglob('*.cs')):
 name=path.relative_to(source);prior=frozen_source/name;old=prior.read_text() if prior.is_file() else '';new=path.read_text()
 if old!=new:diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='frozen/'+str(name),tofile='native-backtest/'+str(name)))
(work/'NATIVE_ADAPTER.diff').write_text(''.join(diffs))
print('NATIVE_PORTFOLIO_M1_SUBSCRIPTION_READY')
