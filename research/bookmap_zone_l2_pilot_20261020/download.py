"""Download public research inputs only; never sends credentials or trades."""
import concurrent.futures, urllib.request, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def download(day):
    p=ROOT/'data'/f'{day}_BTCUSDT_ob500.data.zip'
    p.parent.mkdir(exist_ok=True)
    if p.exists():return str(p)
    url='https://quote-saver.bycsi.com/orderbook/linear/BTCUSDT/'+p.name
    tmp=p.with_suffix('.download')
    with urllib.request.urlopen(url,timeout=60) as r,tmp.open('wb') as f:
        while block:=r.read(4*1024*1024):f.write(block)
    if not zipfile.is_zipfile(tmp):raise ValueError('Not a valid ZIP; preserve failed input for audit')
    tmp.rename(p)
    return str(p)
if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for p in ex.map(download,[f'2024-01-{i:02}' for i in range(1,9)]):print(p,flush=True)
