"""Load an algo's metadata in installed cTrader Console, offline, with no broker credentials."""
import subprocess,json,sys,re,hashlib
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.chmod(0o755);(root/'RizanBootstrap125V1.algo').chmod(0o644);(root/'BootstrapMetadataControl.algo').chmod(0o644);image='ghcr.io/spotware/ctrader-console:latest'
def run(args,timeout=60):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
r=run(['docker','image','inspect',image,'--format','{{.Id}}']);assert r.returncode==0,'CTRADER_IMAGE_UNAVAILABLE';digest=r.stdout.strip()
base=['docker','run','--rm','--network','none','--cpus','0.5','--memory','384m','--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','-v',str(root)+':/input:ro','--workdir','/input',digest]
version=run(base+['--version'])
r=run(base+['metadata','RizanBootstrap125V1.algo'],timeout=90)
out=r.stdout+'\n'+r.stderr
control=run(base+['metadata','BootstrapMetadataControl.algo'],timeout=90)
try:control_data=json.loads(control.stdout)
except:control_data={'raw':control.stdout[:3000]}
try:actual_data=json.loads(r.stdout)
except:actual_data={}
report={'mode':'OFFLINE_METADATA_ONLY','algo_sha256':hashlib.sha256((root/'RizanBootstrap125V1.algo').read_bytes()).hexdigest(),'network':'none','broker_orders':0,'image_id':digest,'exit_code':r.returncode,'metadata_loaded':r.returncode==0 and 'EnableTrading' in out and 'BridgeToken' in out,'requires_ctid':bool(re.search(r'(missing|required|specify).*ctid|ctid.*(missing|required)',out,re.I)),'output_excerpt':out[:12000],'version':version.stdout[:1500],'reported_type':actual_data.get('Type'),'control':control_data,'control_exit_code':control.returncode}
(root/'native-metadata-result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if not report["metadata_loaded"] or report["reported_type"]!="cBot" or report["control"].get("Type")!="cBot":sys.exit(1)
