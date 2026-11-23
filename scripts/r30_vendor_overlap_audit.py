"""Audit source-vendor boundary (HuggingFace 2019 versus original R10 2019).

Never assumes two quote feeds are identical. Reports absolute-price offsets
and direction-label agreement on common closed bars, without fitting models.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from r30_pareto_direction_search import sha

def compare(early,original,tf,output):
    a=pd.read_csv(early,index_col=0,parse_dates=True)
    b=pd.read_csv(original,index_col=0,parse_dates=True)
    if (a.index.tz is None or b.index.tz is None
            or not a.index.is_unique or not b.index.is_unique):
        raise ValueError("R30_OVERLAP_BAD_TIMESTAMPS")
    common=a.index.intersection(b.index)
    if len(common)<(2000 if tf=="1h" else 500):
        raise ValueError("R30_OVERLAP_INSUFFICIENT_COMMON_BARS")
    delta=a.loc[common,"c"].to_numpy(float)-b.loc[common,"c"].to_numpy(float)
    ra=np.sign(a.loc[common,"c"].shift(-1).to_numpy(float)-a.loc[common,"c"].to_numpy(float))
    rb=np.sign(b.loc[common,"c"].shift(-1).to_numpy(float)-b.loc[common,"c"].to_numpy(float))
    aligned=np.isfinite(ra)&np.isfinite(rb)
    report={
        "contract":"R30_EXTERNAL_VS_R10_XAU_2019_OVERLAP_QA_V1",
        "tf":tf,"year":2019,
        "source1":"HF TheFinanceEngineer external redistributed OHLC",
        "source2":"original R10 HistData shards",
        "source1_sha256":sha(early),"source2_sha256":sha(original),
        "common_bars":len(common),"median_abs_close_diff_usd":float(np.median(abs(delta))),
        "p95_abs_close_diff_usd":float(np.quantile(abs(delta),.95)),
        "median_signed_close_diff_usd":float(np.median(delta)),
        "next_candle_label_agreement":float(np.mean(ra[aligned]==rb[aligned])),
        "execution_authority":False,
        "cannot_combine_as_same_vendor":True,
    }
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps(report),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=("1h","4h"),required=True)
    p.add_argument("--early",required=True)
    p.add_argument("--original",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    compare(a.early,a.original,a.tf,a.out)
