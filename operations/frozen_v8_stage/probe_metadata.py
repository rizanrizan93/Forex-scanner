"""Official cTrader Console offline metadata check, no brokerage credentials."""
import json,subprocess,hashlib,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
file=root/"RizanFrozenV8.algo"
expected="c2472244c9f444f0d62b8125ef3e28b2118b6098e8157e1fba5772333098e8c9"
assert hashlib.sha256(file.read_bytes()).hexdigest()==expected
image="ghcr.io/spotware/ctrader-console:latest"
p=subprocess.run(["docker","image","inspect",image,"--format","{{.Id}}"],capture_output=True,text=True,timeout=15)
if p.returncode:
 print(json.dumps({"metadata_loaded":False,"reason":"INSTALLED_CTRADER_CONSOLE_UNAVAILABLE","broker_orders":0}))
 sys.exit(1)
# No credentials, no network, only the binary readable by the container.
root.chmod(0o755);file.chmod(0o644)
digest=p.stdout.strip()
cmd=["docker","run","--rm","--network","none","--cpus","0.5","--memory","384m","--pids-limit","128","--cap-drop","ALL","--security-opt","no-new-privileges","-v",str(file)+":/input/RizanFrozenV8.algo:ro","--workdir","/input",digest,"metadata","RizanFrozenV8.algo"]
p=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
try:j=json.loads(p.stdout)
except Exception:j={}
loaded=p.returncode==0 and j.get("Type")=="cBot" and "EnableTrading" in p.stdout and "BridgeToken" in p.stdout and "BtcBridgeUrl" in p.stdout
print(json.dumps({"metadata_loaded":loaded,"type":j.get("Type"),"sha256":expected,"network":"none","broker_orders":0,"exit_code":p.returncode,"has_enable_trading":"EnableTrading" in p.stdout,"has_btc_bridge":"BtcBridgeUrl" in p.stdout,"console_image_id":digest}))
if not loaded:sys.exit(1)
