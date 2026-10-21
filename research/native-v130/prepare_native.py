"""Create a native cTrader diagnostic build; modify transport, never inject signals."""
from pathlib import Path
import sys, hashlib, json, difflib

work=Path(sys.argv[1])
source=work/'source'
original={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*.cs')}

def change(name,old,new):
    p=source/name;s=p.read_text()
    assert s.count(old)==1,(name,old[:80],s.count(old))
    p.write_text(s.replace(old,new))

change('PortfolioHost.cs','    internal XauEngine? Xau { get; private set; }', '''    [Parameter("Historical transport", DefaultValue=false, Group="Backtest only")]
    public bool HistoricalTransport { get; set; }
    internal bool IsHistoricalBacktest => HistoricalTransport &&
        (RunningMode==RunningMode.SilentBacktesting || RunningMode==RunningMode.VisualBacktesting);
    internal XauEngine? Xau { get; private set; }''')
change('PortfolioHost.cs','        ExpectedAccount=ExpectedAccount.Trim();','''        // This diagnostic binary cannot run on real-time/demo/live market data.
        if(!IsHistoricalBacktest){Print("NATIVE_BACKTEST_MODE_REQUIRED");Stop();return;}
        ExpectedAccount=Account.Number.ToString();
        BridgeUrl=""; BridgeToken=""; BtcBridgeUrl=""; BtcBridgeToken="";
        if(EnableBtc){Print("NATIVE_BACKTEST_BTC_ADAPTER_REQUIRED");Stop();return;}
        Print("NATIVE_BACKTEST_TRANSPORT local_state=True signal_cache=False mode={0}",RunningMode);''')
change('PortfolioHost.cs','if(EnableTrading&&(ExpectedAccount!=Account.Number.ToString()||','if(EnableTrading&&!IsHistoricalBacktest&&(ExpectedAccount!=Account.Number.ToString()||')
old='internal TradeResult Send(TradeType side,string symbol,double units,string label,double sl,double tp,string comment){if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");return ExecuteMarketOrder(side,symbol,units,label,sl,tp,comment);}'
new='''internal TradeResult Send(TradeType side,string symbol,double units,string label,double sl,double tp,string comment){
        if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");
        var r=ExecuteMarketOrder(side,symbol,units,label,sl,tp,comment);
        Print("NATIVE_ORDER_RESULT symbol={0} success={1} error={2} position={3} units={4} at={5:O}",
            symbol,r.IsSuccessful,r.Error,r.Position?.Id,units,Server.TimeInUtc);
        return r;
    }'''
change('PortfolioHost.cs',old,new)
change('PortfolioHost.cs','        _shuttingDown=true;\n        _running=false;','''        Print("NATIVE_BACKTEST_SUMMARY balance={0} equity={1} closed_fills={2} open_positions={3} leverage={4}",
            Account.Balance,Account.Equity,History.Count(),Positions.Count,Account.PreciseLeverage);
        _shuttingDown=true;
        _running=false;''')

for name in ('eur/RizanRobot.cs','xau/RizanRobot.cs'):
    change(name,'else { RecoverAttempt();ReconcileExposure();Changed();Persist(); }',
        'else { RecoverAttempt();ReconcileExposure();Changed();Persist(); if(Host.IsHistoricalBacktest)_continuityReady=!_state.Quarantined && BindingOk && _localRevision>=_state.Revision; }')
    change(name,'                    PrepareBasket(signal,now);',
        '''                {
                    Print("NATIVE_SIGNAL symbol={0} side={1} at={2:O}",SymbolName,signal.Side,signal.AtUtc);
                    PrepareBasket(signal,now);
                }''')
    change(name,'    private void Persist()', '''    private string? _nativeLastPersistedJson;
    private void Persist()''')
    change(name,'        var json=Serialize();', '''        var json=Serialize();
        if(Host.IsHistoricalBacktest && _nativeLastPersistedJson==json && _localRevision>=_state.Revision)return;''')
    change(name,'            _localRevision=_state.Revision;', '''            _localRevision=_state.Revision;
            if(Host.IsHistoricalBacktest)_nativeLastPersistedJson=json;''')
    # Cache only the native closed-bar materialization; no indicator/signal cache.
    # Preserve every bar and rebuild if cTrader prepends/drops history.
    change(name,'    private List<Candle> ClosedM1(DateTime now)', '''    private readonly List<Candle> _nativeClosedCache=new();
    private int _nativeClosedIndex;
    private DateTime _nativeFirstOpen;
    private List<Candle> ClosedM1(DateTime now)''')
    start='''        var r=new List<Candle>();for(int i=0;i<_m1.Count;i++)
        { var at=DateTime.SpecifyKind(_m1.OpenTimes[i],DateTimeKind.Utc);if(at.AddMinutes(1)>now)break;
            r.Add(new(at,_m1.OpenPrices[i],_m1.HighPrices[i],_m1.LowPrices[i],_m1.ClosePrices[i])); }
        return r;'''
    replacement='''        if(!Host.IsHistoricalBacktest)throw new InvalidOperationException("BACKTEST_ONLY_BUILD");
        if(_m1.Count>0 && (_nativeFirstOpen!=_m1.OpenTimes[0] || _nativeClosedIndex>_m1.Count)){
            _nativeClosedCache.Clear();_nativeClosedIndex=0;_nativeFirstOpen=_m1.OpenTimes[0];
        }
        while(_nativeClosedIndex<_m1.Count){
            int i=_nativeClosedIndex;
            var at=DateTime.SpecifyKind(_m1.OpenTimes[i],DateTimeKind.Utc);
            if(at.AddMinutes(1)>now)break;
            _nativeClosedCache.Add(new(at,_m1.OpenPrices[i],_m1.HighPrices[i],_m1.LowPrices[i],_m1.ClosePrices[i]));
            _nativeClosedIndex++;
        }
        return _nativeClosedCache;'''
    change(name,start,replacement)

change('RizanXauEurPortfolio.cs','RizanXauEurBtcFrozen7D130','RizanNativeHistoricalTransportV1')
protected=['xau/FrozenCore.cs','xau/XauBatchExecution.cs','xau/XauSendReference.cs',
           'eur/FrozenCore.cs','eur/EurBatchExecution.cs','eur/F0245Policy.cs',
           'BtcCore.cs','BtcEngine.cs','BtcSevenDayFeed.cs','BtcStateLink.cs','BtcWeekendPolicy.cs']
for name in protected:
    assert (source/name).read_bytes()==original[name],name
manifest={'scope':'Native cTrader API, no REPLAY define, no ApiStubs, no cached signals',
          'backtest_only':True,'transport':'local durable state, instantaneous local persistence ACK',
          'protected_files':protected,'source':{}}
diffs=[]
for name,before in original.items():
    after=(source/name).read_bytes()
    manifest['source'][name]={'before':hashlib.sha256(before).hexdigest(),'after':hashlib.sha256(after).hexdigest()}
    if before!=after:diffs.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='frozen/'+name,tofile='native-backtest/'+name))
(work/'NATIVE_ADAPTER_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
(work/'NATIVE_ADAPTER.diff').write_text(''.join(diffs))
print("NATIVE_ADAPTER_PREPARED protected_files="+str(len(protected)))
