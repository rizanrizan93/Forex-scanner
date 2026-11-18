"""Run R6 eight-year public-data M1->M5 event backtest. No LIVE effects."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import pandas as pd
from research.zone_rebound.xau_m5_mss_direction_r6 import replay_year,aggregate

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--csv',type=Path)
    a.add_argument('--provenance',type=Path)
    a.add_argument('--year',type=int)
    a.add_argument('--aggregate',nargs='*',type=Path)
    a.add_argument('--out',type=Path,required=True)
    args=a.parse_args()
    if args.aggregate is not None:
        result=aggregate(args.aggregate)
        for tf,o in result['result'].items():
            print('R6_M5_MSS_DIRECTION',tf,o.get('chosen'),o.get('test_2025_26'),
                  'pass60',o.get('observed_both_sides_60pct',False))
    else:
        if args.csv is None or args.year not in range(2019,2027):a.error('CSV and year required')
        if not args.provenance or not args.provenance.exists():a.error('Source manifest required')
        prov=json.loads(args.provenance.read_text())
        if prov.get('year')!=args.year or prov.get('normalized_csv_sha256')!=sha(args.csv):
            raise ValueError('INPUT_PROVENANCE_SHA_MISMATCH')
        if prov.get('failed_periods'):raise ValueError('FAILED_PROVIDER_PERIODS')
        result=replay_year(pd.read_csv(args.csv),args.year)
        result['source_manifest']=prov
        result['input_sha256']=sha(args.csv)
        print('R6_M5_YEAR',args.year,'M1',result['price_rows'],'M5',result['m5_bars'])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False,default=str)+'\n')
if __name__=='__main__':main()
