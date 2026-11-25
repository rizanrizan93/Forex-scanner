"""Build a new isolated cTrader candidate from the verified V1 production source.
No native replay stubs, production deployment, orders or old checkpoint migration.
"""
import hashlib,json,shutil,sys
from pathlib import Path
base=Path("repairs/bootstrap125_v1_20261114")
out=Path("dist/RizanFrozenV8")
profile=json.loads(Path(sys.argv[1]).read_text())[0]
assert profile["Id"]=="V7_R1_CAP"
expected={"EarlyMask":5,"EarlyThreshold":1000,"BtcBuyTarget":18,"BtcBuyHours":72,"BtcSellTarget":2,"BtcSellHours":8,"BtcBatchOrders":128,"BtcBatchSeconds":600,"EarlyRiskMask":0,"GrowthRisk":20.75,"XauTarget":4.5,"XauStop":2.4,"EurTarget":10,"EurBE":3,"EurStop":.845,"BtcBuyRsiMax":100,"BtcBuyEfficiencyMin":.2,"BtcSellRsiMin":30,"AddBtcBullCompression":False}
assert all(profile[k]==v for k,v in expected.items())
assert profile["Addon"] is None and profile["Seed"]["Universe"]==1 and profile["Seed"]["HandoffEquity"]==125
old="b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128"
new=hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(",",":")).encode()).hexdigest()
assert new!=old
for folder in ["source","tests","bridge"]:
 shutil.copytree(base/folder,out/folder,ignore=shutil.ignore_patterns("bin","obj","__pycache__"))
original={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob("*") if p.is_file()}
def edit(rel,a,b,count=1):
 p=out/rel;s=p.read_text();n=s.count(a)
 assert n==count,(rel,a,n,count)
 p.write_text(s.replace(a,b))
# New profile identity, labels, native Robot export, URL. The BTC indicator-feed
# contract/seed hash intentionally stay identical, while checkpoint keys differ.
for p in out.rglob("*"):
 if p.is_file() and p.suffix in {".cs",".csproj",".py",".conf",".service",".md"}:
  s=p.read_text()
  s=s.replace(old,new).replace("b6014ae7",new[:8])
  s=s.replace("RIZAN_BOOTSTRAP125_V1_FROZEN_20261114","RIZAN_V8_FROZEN_1914512336_20261125")
  s=s.replace("RizanBootstrap125V1","RizanFrozenV8")
  s=s.replace("RZB125S","RZB8S")
  s=s.replace("/bootstrap125","/v8frozen")
  p.write_text(s)
p=out/"source/RizanBootstrap125V1.csproj";p.rename(out/"source/RizanFrozenV8.csproj")
edit("source/RizanFrozenV8.csproj","<Version>1.0.1</Version>","<Version>8.0.0</Version>")
edit("source/FrozenR3.cs","BtcBuyTarget=12","BtcBuyTarget=18")
edit("source/FrozenR3.cs","BtcBuyHours=128","BtcBuyHours=72")
edit("source/FrozenR3.cs","BtcBatchOrders=32","BtcBatchOrders=128")
edit("source/FrozenR3.cs","BtcBatchSeconds=180","BtcBatchSeconds=600")
# Work V7_R1_CAP uses default-filter bypass and no adaptive early-risk policy,
# no optional BTC H1 compression or PDS. Preserve incumbent strategy families.
edit("source/BootstrapState.cs","public bool Halted{get;set;}","public bool Halted{get;set;} public bool XauUnlocked{get;set;}")
edit("source/BootstrapState.cs",'if(Phase=="GROWTH"&&','if(XauUnlocked&&Phase!="GROWTH")throw new Exception("XAU_PHASE_INVALID");\n  if(Phase=="GROWTH"&&')
edit("source/BootstrapEngine.cs",'internal bool GrowthEnabled=>state.Phase=="GROWTH"&&RecoveryReady;','internal bool GrowthEnabled=>state.Phase=="GROWTH"&&RecoveryReady;\n internal bool XauGrowthEnabled=>GrowthEnabled&&state.XauUnlocked;\n void ObserveXauMilestone(){if(GrowthEnabled&&!state.XauUnlocked&&Account.Balance>=1000&&Account.Equity>=1000){state.XauUnlocked=true;Save();Print("V8_XAU_UNLOCK_PENDING_ACK balance={0} equity={1}",Account.Balance,Account.Equity);}}')
edit("source/BootstrapEngine.cs",'if(state.Phase=="GROWTH"&&remote.Phase!="GROWTH"','if(state.XauUnlocked&&!remote.XauUnlocked&&remote.Revision>=state.Revision)throw new Exception("XAU_UNLOCK_ROLLBACK");\n    if(state.Phase=="GROWTH"&&remote.Phase!="GROWTH"')
edit("source/BootstrapEngine.cs","ManageOpen(now);ObservePeak();","ManageOpen(now);ObservePeak();ObserveXauMilestone();")
edit("source/BootstrapEngine.cs","if(recovered)ObservePeak();","if(recovered){ObservePeak();ObserveXauMilestone();}")
edit("source/xau/RizanRobot.cs","private bool NoForeignExposure() => Host.PortfolioReady && Host.NoForeignExposure();","private bool NoForeignExposure() => Host.Bootstrap?.XauGrowthEnabled==true && Host.PortfolioReady && Host.NoForeignExposure();")
# All symbol ticks observe the threshold, including intrabar floating equity.
edit("source/RizanXauEurPortfolio.cs","if(_running)Xau?.OnTick();","if(_running){Bootstrap?.OnTick();Xau?.OnTick();}")
edit("source/RizanXauEurPortfolio.cs","try{Btc?.OnTick();}","try{Bootstrap?.OnTick();Btc?.OnTick();}")
edit("source/RizanXauEurPortfolio.cs",'if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");if(_runtimeStorageFault)', 'if(symbol=="XAUUSD"&&Bootstrap?.XauGrowthEnabled!=true)throw new InvalidOperationException("V8_XAU_MILESTONE_NOT_ACKED");if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");if(_runtimeStorageFault)')
edit("source/RizanXauEurPortfolio.cs","version=1.0.1-bootstrap125-20261115","version=8.0.0-frozen-v8-20261125")
# Never run against the V1 endpoint, even if manually configured.
edit("source/RizanXauEurPortfolio.cs","if(EnableTrading&&(ExpectedAccount",'''if(!Uri.TryCreate(BridgeUrl,UriKind.Absolute,out var stateUri)||stateUri.AbsolutePath.TrimEnd('/')!="/v8frozen"||!Uri.TryCreate(BtcBridgeUrl,UriKind.Absolute,out var btcUri)||btcUri.AbsolutePath.TrimEnd('/')!="/v8frozen/btc"){Print("V8_BRIDGE_ROUTE_REQUIRED");Stop();return;}
        if(EnableTrading&&(ExpectedAccount''')
# Separate server identity + BTC batch bounds; state and lease DB must never be shared.
edit("bridge/server.py","0 <= state[name] <= 32","0 <= state[name] <= 128")
edit("bridge/server.py",'state["BatchSent"] + state["BatchRemaining"] > 32','state["BatchSent"] + state["BatchRemaining"] > 128')
edit("bridge/server.py",'self.db.commit()','''self.db.execute("""CREATE TRIGGER IF NOT EXISTS v8_xau_unlock_monotonic BEFORE UPDATE OF state ON checkpoints WHEN OLD.key LIKE 'TPBOOT:%' AND json_extract(OLD.state,'$.XauUnlocked')=1 AND COALESCE(json_extract(NEW.state,'$.XauUnlocked'),0)!=1 BEGIN SELECT RAISE(ABORT,'XAU_UNLOCK_ROLLBACK'); END""")
        self.db.commit()''')
edit("bridge/server.py",'if state.get("Phase") not in {"SEED","GROWTH"}:','if type(state.get("XauUnlocked")) is not bool or (state["XauUnlocked"] and state.get("Phase")!="GROWTH"):raise ValueError("XAU_UNLOCK_INVALID")\n            if state.get("Phase") not in {"SEED","GROWTH"}:')
edit("bridge/test_bridge.py","Phase='SEED',Fault=False","Phase='SEED',XauUnlocked=False,Fault=False")
# Add assertions to the original lifecycle suite, including restart after DD.
edit("tests/Program.cs","var wire=Snapshot(phase);",'''var v8=Connected();Check(RP.C.BtcBuyTarget==18&&RP.C.BtcBuyHours==72&&RP.C.BtcBatchOrders==128&&RP.C.BtcBatchSeconds==600,"V8 exact frozen BTC configuration");
  v8.Account.Balance=v8.Account.Equity=125;v8.Bootstrap!.OnTimer();Ack(v8);v8.Bootstrap.OnTimer();Ack(v8);Check(v8.Bootstrap.GrowthEnabled&&!v8.Bootstrap.XauGrowthEnabled,"V8 EUR/BTC early only");
  v8.Account.Balance=1000;v8.Account.Equity=999;v8.Bootstrap.OnTimer();Ack(v8);Check(!v8.Bootstrap.XauGrowthEnabled,"XAU requires both balance and equity");
  v8.Account.Equity=1000;v8.Bootstrap.OnTimer();Check(!v8.Bootstrap.XauGrowthEnabled,"XAU waits for durable ACK");Ack(v8);Check(v8.Bootstrap.XauGrowthEnabled,"XAU unlocked");
  v8.Account.Balance=v8.Account.Equity=500;v8.Bootstrap.OnTimer();Check(v8.Bootstrap.XauGrowthEnabled,"XAU unlock irreversible");
  var v8snapshot=Snapshot(v8);var v8rev=serverRevision;var v8restart=NewHost();Ready(v8restart,v8snapshot,v8rev);Ack(v8restart);Check(v8restart.Bootstrap!.XauGrowthEnabled,"XAU unlock survives restart");
  var wire=Snapshot(phase);''')
# Disable inherited production provisioning scripts in the staged package.
# Do not accidentally run the legacy installer against the live V1 service.
shutil.rmtree(out/"bridge/deploy")
# Local tests and a dedicated isolated service config are packaged. A VPS
# installer is a separate operation, gated on successful build and validation.
(out/"FROZEN_PROFILE.json").write_text(json.dumps(profile,indent=2)+"\n")
(out/"BUILD_MANIFEST.json").write_text(json.dumps({"base_production_commit":"90172c2fba345e4221ca822c8e7d1d760a98c6b1","research_freeze_commit":"d8b9fecfee74fb614ce027b7865effd6eab6aa23","profile_hash":new,"original_files":original,"production_changed":False,"trading_default":False,"source_parity_status":"PORT_NOT_REPLAY_VALIDATED","bridge_route":"/v8frozen/","native_backtest_balance":1914512335.8534427,"native_backtest_dd":58.90845697509444,"files":{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob("*") if p.is_file()}},indent=2))
print("V8_SOURCE_GENERATED",new,"source_files",len(list((out/"source").rglob("*.cs"))))
