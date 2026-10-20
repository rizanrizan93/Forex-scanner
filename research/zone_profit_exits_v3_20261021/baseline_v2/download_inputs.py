from pathlib import Path
import urllib.request, concurrent.futures, json, gzip, hashlib, zipfile
ROOT=Path(__file__).resolve().parent

def get(item):
    kind,day=item
    if kind=='book':
        name=f'{day}_BTCUSDT_ob500.data.zip'
        url='https://quote-saver.bycsi.com/orderbook/linear/BTCUSDT/'+name
    else:
        name=f'{day}_BTCUSDT_trades.csv.gz'
        url=f'https://datasets.tardis.dev/v1/bybit/trades/{day.replace("-","/")}/BTCUSDT.csv.gz'
    p=ROOT/'data'/name
    if not p.exists():
        tmp=p.with_suffix('.download')
        with urllib.request.urlopen(url,timeout=60) as r,tmp.open('wb') as f:
            while b:=r.read(4*1024*1024):f.write(b)
        if kind=='book':
            assert zipfile.is_zipfile(tmp)
        else:
            with gzip.open(tmp,'rt') as f:
                assert next(f).startswith('exchange,symbol,timestamp,local_timestamp')
        tmp.rename(p)
    h=hashlib.sha256()
    with p.open('rb') as f:
        while b:=f.read(4*1024*1024):h.update(b)
    r={'kind':kind,'day':day,'url':url,'bytes':p.stat().st_size,'sha256':h.hexdigest()}
    print(json.dumps(r),flush=True)
    return r

if __name__=='__main__':
    cfg=json.loads((ROOT/'LOCKED_PROTOCOL.json').read_text())
    jobs=[('book',d) for d in cfg['all_book_days']]+[('trades',d) for d in cfg['sample_days']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:rows=list(ex.map(get,jobs))
    (ROOT/'INPUT_MANIFEST.json').write_text(json.dumps(rows,indent=2)+'\n')
