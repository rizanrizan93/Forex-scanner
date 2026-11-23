"""Create isolated replay-admission experiment; original C# and live untouched."""
from pathlib import Path
import shutil,hashlib,json
root=Path(__file__).resolve().parents[2]
src=root/'research/r11_profitable_addon_alpha/native_original'
out=root/'artifacts/r15/guard_source'
shutil.copytree(src,out,dirs_exist_ok=True)
p=out/'native_replay/Replay.cs';s=p.read_text()
a='readonly SeedController seed;readonly XauAddonController addon;'
assert s.count(a)==1;s=s.replace(a,a+'readonly NativeGrowthGuard growthGuard=new();')
a='if(seed.GrowthEnabled&&l.Basket==null&&hasSignal&&host.PortfolioReady'
b='if(seed.GrowthEnabled&&growthGuard.Allow(l.Symbol,phaseTime,trades)&&l.Basket==null&&hasSignal&&host.PortfolioReady'
assert s.count(a)==1;s=s.replace(a,b)
a='if(seed.GrowthEnabled&&hb&&cfg.Btc&&bt.TryGetValue(at,out var bs))'
b='if(seed.GrowthEnabled&&growthGuard.Allow("BTCUSD",host.Server.TimeInUtc,trades)&&hb&&cfg.Btc&&bt.TryGetValue(at,out var bs))'
assert s.count(a)==1;s=s.replace(a,b)
a='return new{AddonAudit=addon.Audit(),SeedAudit=seed.Audit(),'
assert s.count(a)==1;s=s.replace(a,'return new{GrowthGuardAudit=growthGuard.Audit(),AddonAudit=addon.Audit(),SeedAudit=seed.Audit(),')
p.write_text(s)
(out/'native_replay/NativeGrowthGuard.cs').write_text('''using System;using System.Collections.Generic;
sealed class NativeGrowthGuard {
 readonly Dictionary<string,int> losses=new();readonly Dictionary<string,DateTime> pause=new();
 readonly List<object> events=new();int processed,blocks;
 bool Enabled=>Environment.GetEnvironmentVariable("R15_GROWTH_GUARD")=="1";
 public bool Allow(string symbol,DateTime now,List<Trade> trades){
  if(!Enabled)return true;
  while(processed<trades.Count){var t=trades[processed++];if(t.Exit>now)throw new Exception("FUTURE_GUARD_SETTLEMENT");if(t.Origin=="SEED")continue;
   int n=losses.GetValueOrDefault(t.Symbol);
   if(t.Pnl<0){n++;if(n>=4){var until=t.Exit.AddHours(24);if(!pause.ContainsKey(t.Symbol)||pause[t.Symbol]<until)pause[t.Symbol]=until;events.Add(new{t.Symbol,t.Exit,PauseUntil=until});n=0;}}
   else if(t.Pnl>0)n=0;losses[t.Symbol]=n;
  }
  bool allowed=now>=pause.GetValueOrDefault(symbol);if(!allowed)blocks++;return allowed;
 }
 public object Audit()=>new{Enabled,LossLimit=4,PauseHours=24,PerSymbol=true,SettlementsProcessed=processed,ChecksBlocked=blocks,Events=events};
}
''')
receipt={'original_source':str(src.relative_to(root)),'patched_replay_original_sha256':hashlib.sha256((src/'native_replay/Replay.cs').read_bytes()).hexdigest(),'patched_replay_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'scope':'Research entry admission only; GROWTH, per-symbol four accepted basket losses ->24h pause, exits and sizing unchanged','production_changes':False}
(root/'artifacts/r15/guard_source_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('R15_GUARD_COPY_PREPARED')
