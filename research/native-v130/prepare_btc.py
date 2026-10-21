"""Backtest-only historical prefix transport for the unmodified BTC signal core."""
import sys,base64,gzip,csv,io,hashlib,struct,json,difflib
from pathlib import Path
work=Path(sys.argv[1]);source=work/'source';seed=Path(sys.argv[2])
encoded=''.join(seed.read_text().split());raw=gzip.decompress(base64.b64decode(encoded))
rows=list(csv.DictReader(io.StringIO(raw.decode())))
packed=b''.join(struct.pack('<qddddi',int(r['unix']),*[float(r[k]) for k in ('open','high','low','close')],int(r['count'])) for r in rows)
assert len(rows)==68280 and hashlib.sha256(packed).hexdigest()=='e041102102e4ae2768e06f0261b4bfbfabc056ffa5decde21e161d8904179030'
p=source/'BtcHistoricalFeed.cs'
p.write_text('''using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Globalization;
using System.Collections.Generic;
namespace Rizan.Portfolio;
internal sealed class BtcHistoricalFeed {
    private readonly List<BtcBar> all=new();
    internal DateTime Through {get;private set;}
    internal Dictionary<DateTime,BtcSignal> Signals {get;private set;}=new();
    internal bool Fresh(DateTime now)=>Through==BtcSevenDayFeed.Hour(now);
    internal BtcHistoricalFeed(){
        using var stream=new GZipStream(new MemoryStream(Convert.FromBase64String("'''+encoded+'''")),CompressionMode.Decompress);
        using var reader=new StreamReader(stream);
        var header=reader.ReadLine()!.Split(',');
        int Id(string s)=>Array.IndexOf(header,s);
        string? line;
        while((line=reader.ReadLine())!=null){var a=line.Split(',');
            double D(string s)=>double.Parse(a[Id(s)],CultureInfo.InvariantCulture);
            all.Add(new(DateTimeOffset.FromUnixTimeSeconds(long.Parse(a[Id("unix")])).UtcDateTime,D("open"),D("high"),D("low"),D("close"),int.Parse(a[Id("count")])));
        }
    }
    internal void Update(DateTime now){
        var through=BtcSevenDayFeed.Hour(now);if(Through==through)return;
        // Future seed rows never enter indicators, signal calculation or trading state.
        var prefix=all.TakeWhile(b=>b.At.AddHours(1)<=through).ToList();
        if(prefix.Count==0||prefix[^1].At.AddHours(1)!=through)throw new Exception("BTC_HISTORICAL_PREFIX_COVERAGE");
        var four=BtcCore.Aggregate(prefix,240).Where(b=>b.At.AddHours(4)<=through).ToList();
        Signals=BtcCore.Signals(prefix,four);Through=through;
    }
}
''')
host=source/'PortfolioHost.cs';s=host.read_text();needle='        if(EnableBtc){Print("NATIVE_BACKTEST_BTC_ADAPTER_REQUIRED");Stop();return;}\n';assert s.count(needle)==1;host.write_text(s.replace(needle,''))
p=source/'BtcEngine.cs';before=p.read_text();s=before
original_execution=s[s.index('    void ExecuteSignal('):s.index('    public override void OnStop()')]
def change(a,b):
    global s
    assert s.count(a)==1,(a[:80],s.count(a));s=s.replace(a,b)
change('    internal override bool RecoveryReady=>', '    BtcHistoricalFeed? historical;long nativeDurableRevision=-1;\n    internal override bool RecoveryReady=>')
change('(replay||link!=null&&link.FeedReady&&link.Persisted(state.Revision)&&feed.Fresh(Server.TimeInUtc));','(replay||Host.IsHistoricalBacktest&&historical!=null&&historical.Fresh(Server.TimeInUtc)&&nativeDurableRevision>=state.Revision||link!=null&&link.FeedReady&&link.Persisted(state.Revision)&&feed.Fresh(Server.TimeInUtc));')
change('            link?.Changed(state.Revision,value);}', '            nativeDurableRevision=state.Revision;link?.Changed(state.Revision,value);}')
change('            if(replay){ready=true;Save();Manage(Server.TimeInUtc);return;}', '''            if(Host.IsHistoricalBacktest){historical=new BtcHistoricalFeed();historical.Update(Server.TimeInUtc);Recover(default);Print("NATIVE_BACKTEST_BTC historical_prefix=True external_signals=False replay_entrypoint=False");return;}
            if(replay){ready=true;Save();Manage(Server.TimeInUtc);return;}''')
# Recover requires null JSON rather than the default Undefined value.
s=s.replace('Recover(default);','Recover(JsonDocument.Parse("null").RootElement);')
change('        var now=Server.TimeInUtc;Manage(now);if(replay)return;', '        var now=Server.TimeInUtc;if(Host.IsHistoricalBacktest)historical!.Update(now);Manage(now);if(replay)return;')
change('if((now-signal.At).TotalSeconds>5||link==null||link.Fatal)', 'if((now-signal.At).TotalSeconds>5||!Host.IsHistoricalBacktest&&(link==null||link.Fatal))')
change('else if(link.Persisted(state.Revision))', 'else if(Host.IsHistoricalBacktest ? nativeDurableRevision>=state.Revision : link!.Persisted(state.Revision))')
change('if((now-at).TotalSeconds<=5&&feed.Signals.TryGetValue(at,out var s))Enter(s,now);', 'if((now-at).TotalSeconds<=5&&(Host.IsHistoricalBacktest ? historical!.Signals : feed.Signals).TryGetValue(at,out var s))Enter(s,now);')
change('        state.LastSignal=s.At; // consume even when busy/OFF; never catch up a missed signal','        Print("NATIVE_SIGNAL symbol=BTCUSD side={0} at={1:O}",s.Side,s.At);\n        state.LastSignal=s.At; // consume even when busy/OFF; never catch up a missed signal')
assert original_execution==s[s.index('    void ExecuteSignal('):s.index('    public override void OnStop()')]
p.write_text(s)
manifest_path=work/'NATIVE_ADAPTER_MANIFEST.json';m=json.loads(manifest_path.read_text());m['protected_files'].remove('BtcEngine.cs');m['protected_methods']=['BtcEngine.ExecuteSignal'];m['btc_seed']={'rows':len(rows),'sha256':hashlib.sha256(packed).hexdigest(),'signals':'BtcCore computes signals itself from closed historical prefix'}
for name in ('BtcEngine.cs','PortfolioHost.cs','BtcHistoricalFeed.cs'):
    item=m['source'].setdefault(name,{});item['after']=hashlib.sha256((source/name).read_bytes()).hexdigest()
manifest_path.write_text(json.dumps(m,indent=2))
frozen_source=seed.parent.parent/'work/source'
diffs=[]
for path in sorted(source.rglob('*.cs')):
    name=path.relative_to(source);prior=frozen_source/name
    old=prior.read_text() if prior.is_file() else ''
    new=path.read_text()
    if old!=new:diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='frozen/'+str(name),tofile='native-backtest/'+str(name)))
(work/'NATIVE_ADAPTER.diff').write_text(''.join(diffs))
print('NATIVE_BTC_PREFIX_ADAPTER_PREPARED seed_hash_verified=True execution_method_unchanged=True')
