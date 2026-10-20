"""Validate ZIP CRC and reconstruct every delta; sample causally at 1 second.
Heatmap stores actual price-binned displayed quantity every 30 seconds.
"""
from pathlib import Path
import concurrent.futures, hashlib, json, zipfile, sys, time
import numpy as np
import orjson
from book_adapter import Book

ROOT = Path(__file__).resolve().parent

def prepare(day):
    src = ROOT / 'data' / f'{day}_BTCUSDT_ob500.data.zip'
    out = ROOT / 'derived' / (day + '.npz')
    audit = ROOT / 'derived' / (day + '.json')
    if out.exists() and audit.exists():
        return json.loads(audit.read_text())
    start = int(np.datetime64(day, 'ms').astype('int64'))
    end = start + 86400000
    grid = start
    ts, values, heat_t, heat = [], [], [], []
    # Fixed USD prices, not re-centered using future extrema.
    edges = np.arange(30000, 55010, 10)
    book = Book()
    n = bad = regress = clipped = 0
    previous = -1
    begin = time.time()
    with zipfile.ZipFile(src) as z:
        assert len(z.namelist()) == 1
        # Fully reading the member verifies its ZIP CRC.
        with z.open(z.namelist()[0]) as stream:
            for raw in stream:
                msg = orjson.loads(raw)
                t = int(msg['ts'])
                if t < previous:
                    regress += 1
                # Before applying an event at t, emit only grids STRICTLY < t.
                # Thus equal-timestamp message batches are fully applied together.
                while grid < min(t, end):
                    s = book.sample(grid)
                    ts.append(grid)
                    values.append(s if s else (np.nan,) * 5)
                    if not s:
                        bad += 1
                    if grid % 30000 == 0:
                        row = np.zeros(len(edges) - 1, np.float32)
                        if s:
                            for p, q in list(book.bids.items()) + list(book.asks.items()):
                                ix = int((p / 10 - 30000) // 10)
                                if 0 <= ix < len(row):
                                    row[ix] += q
                                else:
                                    clipped += 1
                        heat_t.append(grid)
                        heat.append(row)
                    grid += 1000
                book.apply(msg)
                previous = max(previous, t)
                n += 1
        while grid < end:
            s = book.sample(grid)
            ts.append(grid)
            values.append(s if s else (np.nan,) * 5)
            bad += int(s is None)
            grid += 1000
    out.parent.mkdir(exist_ok=True)
    np.savez_compressed(out, ts=np.array(ts, np.int64), quotes=np.asarray(values),
                        heat_t=np.asarray(heat_t), heat=np.asarray(heat), price_edges=edges)
    h = hashlib.sha256()
    with src.open('rb') as f:
        while block := f.read(4 * 1024 * 1024):
            h.update(block)
    result = {'day': day, 'source_url': 'https://quote-saver.bycsi.com/orderbook/linear/BTCUSDT/' + src.name,
              'zip_bytes': src.stat().st_size, 'zip_sha256': h.hexdigest(), 'zip_crc_read_pass': True,
              'messages': n, 'invalid_sample_seconds': bad, 'timestamp_regressions': regress,
              'snapshot_resets': book.resets, 'heatmap_clipped_levels': clipped,
              'samples': len(ts), 'seconds': round(time.time() - begin, 2)}
    audit.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result

if __name__ == '__main__':
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(prepare, [f'2024-01-{i:02}' for i in range(1, 9)]))
    (ROOT / 'DATA_AUDIT.json').write_text(json.dumps(results, indent=2) + '\n')
