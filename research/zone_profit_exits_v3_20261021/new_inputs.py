"""Reuse verified V2 acquisition/reconstruction on NEW research dates only."""
from pathlib import Path
import sys,json,concurrent.futures
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline_v2'))
import download_inputs as down
import prepare_inputs as prep

def get(job):
    down.ROOT=ROOT
    return down.get(job)

def prepare(day):
    prep.ROOT=ROOT
    return prep.prepare_book(day)

if __name__=='__main__':
    cfg=json.loads((ROOT/'LOCKED_PROTOCOL_V3.json').read_text())
    jobs=[('book',d) for d in cfg['new_book_days']]+[('trades',d) for d in cfg['new_validation_days']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:rows=list(ex.map(get,jobs))
    (ROOT/'NEW_INPUT_MANIFEST.json').write_text(json.dumps(rows,indent=2)+'\n')
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as ex:books=list(ex.map(prepare,cfg['new_book_days']))
    prep.ROOT=ROOT;trades=[prep.prepare_trades(d) for d in cfg['new_validation_days']]
    (ROOT/'NEW_DATA_QUALITY.json').write_text(json.dumps({'books':books,'trades':trades},indent=2)+'\n')
