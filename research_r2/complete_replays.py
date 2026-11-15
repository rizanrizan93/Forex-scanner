"""Sequential retries after two parallel research workers exceeded memory."""
import pathlib,subprocess,sys,json,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
failures=[]
for mode,name,log in [('ANNUAL','REVIEW_ANNUAL','r2_review_annual.log'),('CONTINUOUS','REVIEW_CONTINUOUS','r2_review_continuous.log')]:
 p=ROOT/log
 if p.exists():shutil.copy2(p,ROOT/'r2_audit'/('FAILED_'+log))
 failures.append({'experiment':name,'earlier_exit_code':137,'earlier_failure':'offline research process killed under parallel memory pressure; no completed result retained','retry':'sequential full rerun'})
 with p.open('w') as f:
  result=subprocess.run([sys.executable,str(ROOT/'research_r2/run_r2.py'),'--configs',str(ROOT/'r2_results/review_configs.json'),'--mode',mode,'--name',name],stdout=f,stderr=subprocess.STDOUT)
 failures[-1]['retry_exit_code']=result.returncode;(ROOT/'r2_audit/retry_status.json').write_text(json.dumps(failures,indent=2));print(name,'exit',result.returncode,flush=True)
 if result.returncode:raise SystemExit(result.returncode)
