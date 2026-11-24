"""Offline runner; exact input provenance gate and independent per-base receipts."""
import argparse, hashlib, json, shutil, subprocess, sys
from pathlib import Path

EXPECTED = {
    "eur_2012_2026.csv": "710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5",
    "BTCUSD_M1.csv": "9257332636450a0c93d20c45757016ae359feb208d7b91ac82fac173a64f8c51",
}
HERE=Path(__file__).resolve().parent
GEN=HERE.parent/"frozen_v1_10b_20261124"/"generate_tapes.py"

def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--inputs",required=True,type=Path)
    p.add_argument("--work",required=True,type=Path)
    p.add_argument("--bases",default="3",help="comma-separated base indices, or all")
    p.add_argument("--prepare-only",action="store_true")
    a=p.parse_args()
    inp=a.inputs.resolve(); work=a.work.resolve(); work.mkdir(parents=True,exist_ok=True)
    actual={k:digest(inp/k) for k in EXPECTED}
    if actual!=EXPECTED:raise SystemExit("Exact source checksum mismatch: "+str(actual))
    root=work/"screen";root.mkdir(exist_ok=True)
    stage=work/"replay_recovery";stage.mkdir(exist_ok=True)
    link=stage/"inputs"
    if link.exists() and link.resolve()!=inp:raise SystemExit("Different staged input directory")
    if not link.exists():link.symlink_to(inp,target_is_directory=True)
    receipt=root/"tape_manifest.json"
    if not receipt.exists():
        shutil.copyfile(GEN,root/"generate_tapes.py")
        subprocess.run([sys.executable,str(root/"generate_tapes.py")],check=True)
        files=sorted((root/"data").glob("*"))
        manifest={"price_sha256":actual,"generator_sha256":digest(GEN),"files":{f.name:digest(f) for f in files if f.is_file()}}
        receipt.write_text(json.dumps(manifest,indent=2)+"\n")
    else:
        manifest=json.loads(receipt.read_text())
        if manifest["price_sha256"]!=actual or manifest["generator_sha256"]!=digest(GEN):raise SystemExit("Stale tape provenance")
        for k,h in manifest["files"].items():
            if digest(root/"data"/k)!=h:raise SystemExit("Tape hash mismatch: "+k)
    required=[f"{s}_{n}" for s in (0,2) for n in ("times.i64","m1.f64")]+[f"base{i}_symbol{s}.bin" for i in range(36) for s in (0,2)]
    if any(k not in manifest["files"] for k in required):raise SystemExit("Incomplete tape manifest")
    if a.prepare_only:return
    exe=work/"v3_search"
    subprocess.run(["g++","-O3","-std=c++20","-fopenmp",str(HERE/"search.cpp"),"-o",str(exe)],check=True)
    subprocess.run([str(exe),"--selftest"],check=True)
    bases=list(range(36)) if a.bases=="all" else list(dict.fromkeys(map(int,a.bases.split(","))))
    if any(b not in range(36) for b in bases):raise SystemExit("invalid base")
    results=root/"results";results.mkdir(exist_ok=True)
    run_source=digest(HERE/"search.cpp")
    prefix_source=digest(HERE.parent/"frozen_v1_10b_20261124"/"screen_prefix.cpp")
    for b in bases:
        stem=f"v3_base{b}";summary=results/(stem+".json");csv=results/(stem+".csv");done=results/(stem+".receipt.json")
        signature={"source_sha256":run_source,"prefix_sha256":prefix_source,"tapes_sha256":digest(receipt)}
        if done.exists():
            saved=json.loads(done.read_text())
            if all(saved.get(k)==v for k,v in signature.items()) and saved.get("csv_sha256")==digest(csv) and saved.get("summary_sha256")==digest(summary):
                print("VERIFIED existing shard",b,flush=True);continue
            raise SystemExit("Existing incompatible shard receipt; use separate work directory")
        subprocess.run([str(exe),str(root),str(b)],check=True)
        meta=json.loads(summary.read_text())
        if not meta["complete"] or meta["base"]!=b or meta["signal_groups_evaluated"]!=19440:raise SystemExit("Incomplete shard")
        done.write_text(json.dumps({**signature,"csv_sha256":digest(csv),"summary_sha256":digest(summary)},indent=2)+"\n")
    allmeta=[json.loads(f.read_text()) for f in results.glob("v3_base*.json") if not f.name.endswith(".receipt.json") and f.with_name(f.stem+".receipt.json").exists()]
    totals={k:sum(m[k] for m in allmeta) for k in ("nominal_space_shard","signal_groups_evaluated","signal_groups_passed","wallet_configs_evaluated","annual_cost_trials","dev_passed","eval_passed","native_replays")}
    print(json.dumps({"completed_shards":len(allmeta),"search_space_full":302330880,**totals},indent=2))
if __name__=="__main__":main()
