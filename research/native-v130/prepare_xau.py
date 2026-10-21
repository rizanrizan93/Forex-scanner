"""Supply archived raw external inputs to original XAU gates during native tests."""
import json,sys,hashlib,difflib
from pathlib import Path
work=Path(sys.argv[1]);source=work/'source';inputs=Path(sys.argv[2]);data=json.loads(inputs.read_text())
assert data['CoverageFromUtc']=='2025-06-08T04:00:00Z' and data['CoverageToUtc']=='2025-06-22T04:00:00Z'
assert len(data['Dgs10'])==32 and len(data['Dfii10'])==32 and len(data['Events'])==5
payload=json.dumps({k:v for k,v in data.items() if k!='Provenance'},separators=(',',':')).replace('"','""')
(source/'HistoricalXauInputs.cs').write_text('''using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Rizan.Portfolio.Xau;
namespace Rizan.Portfolio;
internal static class HistoricalXauInputs {
    public sealed class Inputs {
        public DateTime CoverageFromUtc {get;set;}
        public DateTime CoverageToUtc {get;set;}
        public List<MacroPoint> Dgs10 {get;set;}=new();
        public List<MacroPoint> Dfii10 {get;set;}=new();
        public List<NewsPoint> Events {get;set;}=new();
    }
    private static readonly Inputs data=JsonSerializer.Deserialize<Inputs>(@"'''+payload+'''")!;
    internal static ExternalSnapshot? At(DateTime now){
        if(now<data.CoverageFromUtc||now>=data.CoverageToUtc)return null;
        return new(){ProducedUtc=now,CoverageFromUtc=data.CoverageFromUtc,CoverageToUtc=data.CoverageToUtc,
            ForexFactoryOk=true,BlsOk=true,
            Dgs10=data.Dgs10.LastOrDefault(v=>v.AvailableUtc<=now),
            Dfii10=data.Dfii10.LastOrDefault(v=>v.AvailableUtc<=now),Events=data.Events};
    }
}
''')
host=source/'PortfolioHost.cs';s=host.read_text();needle='    internal XauEngine? Xau { get; private set; }';assert s.count(needle)==1
s=s.replace(needle,'''    [Parameter("Historical macro inputs", DefaultValue=false, Group="Backtest only")]
    public bool HistoricalMacro {get;set;}
'''+needle);host.write_text(s)
p=source/'xau/RizanRobot.cs';before=p.read_text();gate=before[before.index('    private bool ExternalOk('):before.index('    private void PrepareBasket(')]
needle='        var now=Server.TimeInUtc;\n        if(UsesBridge)ServiceBridge(now);';assert before.count(needle)==1
s=before.replace(needle,'        var now=Server.TimeInUtc;\n        if(Host.IsHistoricalBacktest && Host.HistoricalMacro)_snapshot=HistoricalXauInputs.At(now);\n        if(UsesBridge)ServiceBridge(now);')
assert gate==s[s.index('    private bool ExternalOk('):s.index('    private void PrepareBasket(')]
p.write_text(s)
manifest_path=work/'NATIVE_ADAPTER_MANIFEST.json';m=json.loads(manifest_path.read_text());m['historical_external_inputs']={'sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),'provenance':data['Provenance'],'coverage_from':data['CoverageFromUtc'],'coverage_to':data['CoverageToUtc'],'original_ExternalOk_method_unchanged':True,'gate_permission_flags_supplied':False}
for name in ('PortfolioHost.cs','xau/RizanRobot.cs','HistoricalXauInputs.cs'):
    item=m['source'].setdefault(name,{});item['after']=hashlib.sha256((source/name).read_bytes()).hexdigest()
manifest_path.write_text(json.dumps(m,indent=2))
frozen_source=Path('frozen/portfolio_7day_frozen/work/source');diffs=[]
for path in sorted(source.rglob('*.cs')):
    name=path.relative_to(source);prior=frozen_source/name;old=prior.read_text() if prior.is_file() else '';new=path.read_text()
    if old!=new:diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='frozen/'+str(name),tofile='native-backtest/'+str(name)))
(work/'NATIVE_ADAPTER.diff').write_text(''.join(diffs))
print('NATIVE_XAU_RAW_INPUTS_PREPARED original_external_gate_unchanged=True point_in_time_archive=False')
