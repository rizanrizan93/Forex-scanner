"""Fixed-window historical source sample. Public HistData XAUUSD M1, research only."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hashlib, json, os
from histdata_fetcher import fetch_data
from fx_scanner.research_xau_histdata_download_v193 import _normalize_frame, PROVIDER_COMMIT

START=date(2023,9,1)
END=date(2023,9,29)

def main():
    fetched=fetch_data(pair='XAUUSD',start_date=START,end_date=END,
                       timeframe='1min',output_format=None,max_workers=1)
    failed=[{'period':x.period_label,'reason':x.reason} for x in fetched.failed_periods]
    if failed or fetched.data.empty:
        raise RuntimeError('HISTDATA_INCOMPLETE: '+json.dumps(failed))
    rows=_normalize_frame(fetched.data)
    out=Path(os.environ.get('REJECTION_SAMPLE_PATH','/tmp/rejection-histdata-2023.csv'))
    out.parent.mkdir(parents=True,exist_ok=True)
    rows.to_csv(out,index=False)
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    provenance={'source':'HISTDATA_XAUUSD_M1',
                'provider_commit':PROVIDER_COMMIT,'source_tier':'PUBLIC_SECONDARY_MARKET_DATA',
                'range_requested':[START.isoformat(),END.isoformat()],
                'timestamp_source':'FIXED_EST_UTC_MINUS5_NO_DST',
                'timestamp_normalized':'UTC','rows':len(rows),
                'sha256_csv':digest,'failed_periods':failed,
                'first_utc':str(rows.timestamp.iloc[0]),
                'last_utc':str(rows.timestamp.iloc[-1]),
                'fp_markets_executable_quote':False}
    Path(str(out)+'.provenance.json').write_text(json.dumps(provenance,indent=2))
    print('REJECTION_SOURCE_PROVENANCE',json.dumps(provenance))
if __name__=='__main__':main()
