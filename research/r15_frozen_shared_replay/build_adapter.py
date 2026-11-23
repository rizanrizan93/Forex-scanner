"""Create a reviewable research adapter; leave original native sources untouched."""
import argparse,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def build(destination):
    source=ROOT/'research/r11_profitable_addon_alpha/native_original'
    out=Path(destination);shutil.copytree(source,out,dirs_exist_ok=True,ignore=shutil.ignore_patterns('bin','obj'))
    p=out/'native_replay/Replay.cs';s=p.read_text();before=hashlib.sha256(s.encode()).hexdigest();changes=[]
    def replace(old,new,count=1):
        nonlocal s
        assert s.count(old)==count,(old,s.count(old),count)
        s=s.replace(old,new);changes.append(dict(old=old,new=new,count=count))
    replace('readonly SeedController seed;readonly XauAddonController addon;','readonly SeedController seed;readonly XauAddonController addon;readonly SparseAddon sparse;')
    needle='"ADDON"));});}'
    replace(needle,'"ADDON"));});sparse=new(host,c.Cost,h=>{ReplaySizing.Settle(h.NetProfit);trades.Add(new(h.EntryTime,h.ClosingTime,h.SymbolName,h.NetProfit,host.Account.Balance,1,0,1,"SPARSE"));});}')
    # Extra timestamps must not alter the legacy seed's observation schedule.
    # Preserve its exact calendar until the original graduation actually occurs.
    native_calendar='xt.Signals.Keys'+s.split('var signals=xt.Signals.Keys',1)[1].split(';int si=0;',1)[0]
    assert '\n' not in native_calendar and native_calendar.endswith('.ToArray()')
    replace('.Concat(seed.SignalTimes).Concat(addon.SignalTimes)', '.Concat(seed.SignalTimes).Concat(addon.SignalTimes).Concat(sparse.SignalTimes)')
    replace(';int si=0;',';var nativeSignalTimes='+native_calendar+'.ToHashSet();int si=0;')
    replace('while(si<signals.Length&&signals[si]<at)si++;','while(si<signals.Length&&(signals[si]<at||!seed.GrowthEnabled&&!nativeSignalTimes.Contains(signals[si])))si++;')
    replace('if(legs.All(l=>!l.Active)&&!host.Positions.Any(p=>p.SymbolName=="BTCUSD"))','if(legs.All(l=>!l.Active)&&!host.Positions.Any(p=>p.SymbolName=="BTCUSD")&&!sparse.Active)',2)
    replace('if(legs.Any(l=>l.Active)||host.Positions.Any(p=>p.SymbolName=="BTCUSD"))for','if(legs.Any(l=>l.Active)||host.Positions.Any(p=>p.SymbolName=="BTCUSD")||sparse.Active)for')
    replace('if(hasSignal){var signalTime=', 'sparse.ObserveCore(at,l.Symbol,hasSignal);if(hasSignal){var signalTime=')
    needle='if(seed.GrowthEnabled&&hb&&cfg.Btc&&bt.TryGetValue(at,out var bs))host.Btc?.Enter(bs,host.Server.TimeInUtc);RecordBtc();'
    replace(needle,needle+'sparse.Manage(host.Server.TimeInUtc);sparse.Enter(at,seed.GrowthEnabled,legs.All(l=>l.Basket==null&&l.Acks.Count==0)&&host.Btc?.ResearchBatchQueued!=true);')
    replace('RecordBtc();seed.Manage(host.Server.TimeInUtc);if(seed.GrowthEnabled)addon.Manage(host.Server.TimeInUtc);Observe();',
            'RecordBtc();seed.Manage(host.Server.TimeInUtc);if(seed.GrowthEnabled)addon.Manage(host.Server.TimeInUtc);sparse.Manage(host.Server.TimeInUtc);Observe();')
    replace('RecordBtc();seed.Manage(_clock);if(seed.GrowthEnabled)addon.Manage(_clock);foreach',
            'RecordBtc();seed.Manage(_clock);if(seed.GrowthEnabled)addon.Manage(_clock);sparse.Manage(_clock);foreach')
    replace('return new{AddonAudit=addon.Audit(),','return new{SparseAudit=sparse.Audit(),AddonAudit=addon.Audit(),')
    p.write_text(s);shutil.copyfile(HERE/'SparseAddon.cs',out/'native_replay/SparseAddon.cs')
    report=dict(original_replay_sha256=before,patched_replay_sha256=hashlib.sha256(s.encode()).hexdigest(),
        changes=changes,original_source_modified=False,production_source_modified=False)
    (out/'adapter_patch_manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print('ADAPTER_BUILT',out,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();build(a.output)
