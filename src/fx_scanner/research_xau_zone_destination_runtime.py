from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from .research_xau_zone_destination import build_dataset, aggregate
from .research_xau_v229_historical_v242_year_runtime import _download


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int)
    p.add_argument("--shards",type=Path)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if bool(args.year)==bool(args.shards):
        p.error("provide exactly one of --year or --shards")
    if args.year:
        csv=Path(f"/tmp/histdata/xau-zone-destination-{args.year}.csv")
        provenance=_download(args.year,csv,args.output.with_suffix(".provenance.json"))
        if provenance.get("failed_periods"):
            raise SystemExit("INCOMPLETE_PROVIDER_DOWNLOAD")
        result=build_dataset(pd.read_csv(csv),target_year=args.year)
        result["price_provenance"]=provenance
    else:
        paths=sorted(args.shards.rglob("xau-zone-destination-20*.json"))
        result=aggregate([json.loads(p.read_text()) for p in paths if not p.name.endswith(".provenance.json")])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,allow_nan=False,separators=(",",":"))+"\n")
    print(f"ZONE_DESTINATION output={args.output} rows={len(result.get('rows',[]))}")

if __name__=="__main__": main()
