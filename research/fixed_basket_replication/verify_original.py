#!/usr/bin/env python3
"""Verify recovery inputs and original settlement parity. Not a trading simulator."""
import argparse, csv, hashlib, json, math, zipfile
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, localcontext

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "RECOVERED_PROFILES.json"
D = Decimal

def load():
    return json.loads(MANIFEST.read_text(), parse_float=D)

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def inventory(folder):
    m=load()
    archives={s["archive"]:s["archiveSHA256"] for s in m["sourceFiles"] if s["archive"]}
    for name in m["requiredArtifacts"]:
        if name.endswith(".zip"):
            archives.setdefault(name, None)
    rows=[]
    for name, expected in sorted(archives.items()):
        p=folder/name
        if not p.is_file():
            rows.append({"archive":name,"status":"MISSING"})
            continue
        digest=sha256(p)
        if expected and digest != expected:
            rows.append({"archive":name,"status":"SHA256_MISMATCH","actual":digest,"expected":expected})
            continue
        try:
            with zipfile.ZipFile(p) as z:
                bad=z.testzip()
                members=z.namelist()
            rows.append({"archive":name,"status":"CORRUPT" if bad else ("VERIFIED_ARCHIVE" if expected else "UNPINNED_ARCHIVE"),"sha256":digest,"memberCount":len(members),"badMember":bad})
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            rows.append({"archive":name,"status":"CORRUPT","error":str(exc)})
    return {"status":"INVENTORY_ONLY_NOT_REPLAY","archives":rows}

def utc(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("timezone required")
    return d.astimezone(timezone.utc)

def audit(ledger, profile_id, cost):
    m=load()
    p=next((p for p in m["profiles"] if p["id"]==profile_id),None)
    if not p: raise ValueError("unknown profile")
    if p["vector"] is None: raise ValueError("exact original configuration missing")
    expected=p["metrics"]["fixed"]
    i=0 if cost==1 else 2
    with localcontext() as ctx:
        ctx.prec=50
        balance=peak=D("100")
        dd=D(0)
        seen=set()
        last=None
        n=0
        with open(ledger,newline="",encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k=(utc(r["exit_utc"]),int(r["settlement_seq"]))
                if last is not None and k<=last: raise ValueError("invalid event ordering")
                if not r["basket_id"] or r["basket_id"] in seen: raise ValueError("duplicate/empty basket id")
                if utc(r["entry_utc"])>k[0]: raise ValueError("entry after exit")
                if r["symbol"] not in ("EURUSD","XAUUSD","BTCUSD"): raise ValueError("invalid symbol")
                pnl=D(r["net_pnl_usd"])
                reported=D(r["balance_after_usd"])
                if not pnl.is_finite() or not reported.is_finite(): raise ValueError("nonfinite ledger")
                balance+=pnl
                if abs(balance-reported)>D("0.01"): raise ValueError("settlement arithmetic mismatch")
                peak=max(peak,balance)
                dd=max(dd,(peak-balance)/peak*100)
                seen.add(r["basket_id"]); last=k; n+=1
        if not n: raise ValueError("empty ledger")
        # Archived summary numbers are binary64 and may not preserve cents.
        target=D(str(expected[i])); targetdd=D(str(expected[i+1]))
        tol=max(D("0.01"),D(str(math.ulp(float(target))))*2)
        match=abs(balance-target)<=tol and abs(dd-targetdd)<=D("0.000001")
        return {"status":"SETTLEMENT_SUMMARY_PARITY_ONLY" if match else "PARITY_FAILED","candidate":profile_id,"cost":cost,"balance":str(balance),"closedDDPct":str(dd),"expectedBalance":str(target),"expectedDDPct":str(targetdd),"balanceToleranceUSD":str(tol),"basketCount":n,"ledgerSHA256":sha256(Path(ledger)),"originalKernelExecuted":False,"nativeReplayVerified":False,"floatingDDPct":None,"match":match}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("inventory"); a.add_argument("folder",type=Path)
    a=sub.add_parser("audit"); a.add_argument("ledger",type=Path); a.add_argument("--profile",required=True); a.add_argument("--cost",type=int,choices=[1,2],required=True)
    args=parser.parse_args()
    result=inventory(args.folder) if args.mode=="inventory" else audit(args.ledger,args.profile,args.cost)
    print(json.dumps(result,indent=2))
    if args.mode=="audit" and not result["match"]: raise SystemExit(2)
