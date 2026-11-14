"""Load an algo's metadata in installed cTrader Console, offline, with no broker credentials."""
import subprocess,json,sys,re
from pathlib import Path
root=Path(sys.argv[1]).resolve();image='ghcr.io/spotware/ctrader-console:latest'
def run(args,timeout=60):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
r=run(['docker','image','inspect',image,'--format','{{.Id}}']);assert r.returncode==0,'CTRADER_IMAGE_UNAVAILABLE';digest=r.stdout.strip()
base=['docker','run','--rm','--network','none','--cpus','0.5','--memory','384m','--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','-v',str(root)+':/input:ro',digest]
version=run(base+['--version']);help_main=run(base+['--help']);help_meta=run(base+['metadata','--help'])
r=run(base+['metadata','/input/RizanBootstrap125V1.algo'],timeout=90)
out=r.stdout+'\n'+r.stderr
report={'mode':'OFFLINE_METADATA_ONLY','network':'none','broker_orders':0,'image_id':digest,'exit_code':r.returncode,'metadata_loaded':r.returncode==0 and 'EnableTrading' in out and 'BridgeToken' in out,'requires_ctid':bool(re.search(r'(missing|required|specify).*ctid|ctid.*(missing|required)',out,re.I)),'output_excerpt':out[:12000],'version':version.stdout[:1500],'help':help_main.stdout[:15000],'metadata_help':help_meta.stdout[:15000]}
(root/'native-metadata-result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
