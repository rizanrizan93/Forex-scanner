"""Subscribe the third broker symbol to native M1 data in multi-symbol backtests."""
from pathlib import Path
import sys,json,hashlib,difflib
work=Path(sys.argv[1]);source=work/'source';p=source/'PortfolioHost.cs';s=p.read_text()
a='    internal XauEngine? Xau { get; private set; }';assert s.count(a)==1
s=s.replace(a,'    private cAlgo.API.Bars? _nativeBtcBrokerM1;\n'+a)
a='        BridgeUrl=""; BridgeToken=""; BtcBridgeUrl=""; BtcBridgeToken="";';assert s.count(a)==1
s=s.replace(a,a+'\n        if(EnableBtc)_nativeBtcBrokerM1=MarketData.GetBars(TimeFrame.Minute,"BTCUSD");')
p.write_text(s);manifest_path=work/'NATIVE_ADAPTER_MANIFEST.json';m=json.loads(manifest_path.read_text());m['source']['PortfolioHost.cs']['after']=hashlib.sha256(p.read_bytes()).hexdigest();m['multi_symbol_market_data']='Subscribe BTCUSD broker M1 bars; EUR/XAU already subscribe in their unchanged startup path.';manifest_path.write_text(json.dumps(m,indent=2))
frozen_source=Path('frozen/portfolio_7day_frozen/work/source');diffs=[]
for path in sorted(source.rglob('*.cs')):
 name=path.relative_to(source);prior=frozen_source/name;old=prior.read_text() if prior.is_file() else '';new=path.read_text()
 if old!=new:diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='frozen/'+str(name),tofile='native-backtest/'+str(name)))
(work/'NATIVE_ADAPTER.diff').write_text(''.join(diffs))
print('NATIVE_PORTFOLIO_M1_SUBSCRIPTION_READY')
