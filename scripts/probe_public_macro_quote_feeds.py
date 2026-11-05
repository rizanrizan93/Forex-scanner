"""Read-only probe of public macro price providers; no live order side effects."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

NOW = datetime.now(UTC)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"

def open_json(url, maxbytes=500000):
    req = Request(url, headers={"User-Agent":UA,"Accept":"application/json"})
    with urlopen(req, timeout=6) as r:
        return json.loads(r.read(maxbytes).decode("utf-8"))

def safe(op, sym, fn):
    try:
        row = fn(sym)
        return {"feed":op,"symbol":sym,**row}
    except Exception as e:
        return {"feed":op,"symbol":sym,"error":type(e).__name__+":"+str(e)[:140]}

def age(ts):
    if isinstance(ts,(int,float)):
        dt = datetime.fromtimestamp(ts,UTC)
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z","+00:00"))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=UTC)
        except Exception:return None
    return round((NOW - dt).total_seconds()/60,1)

def yahoo(sym):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+quote(sym,safe="")+"?interval=1m&range=1d"
    p=open_json(url)
    d=p["chart"]["result"][0]
    meta=d.get("meta") or {}
    stamps=d.get("timestamp") or []
    return {
        "price":meta.get("regularMarketPrice"),
        "last_timestamp":meta.get("regularMarketTime"),
        "last_age_min":age(meta.get("regularMarketTime")),
        "chart_last_age_min":age(max(stamps) if stamps else None),
        "prior":meta.get("chartPreviousClose"),
        "market_state":meta.get("marketState"),
    }
def cnbc(sym):
    params=urlencode({
        "symbols":sym,"requestMethod":"itv","noform":"1","partnerId":"2","fund":"1",
        "exthrs":"1","output":"json","events":"1",
    })
    p=open_json("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?"+params)
    rows=(p.get("FormattedQuoteResult") or {}).get("FormattedQuote") or []
    if isinstance(rows,dict): rows=[rows]
    if not rows:return {"error":"NO_ROWS"}
    d=rows[0]
    return {
        "symbol_returned":d.get("symbol"),
        "last":d.get("last"),
        "change_pct":d.get("change_pct"),
        "last_time":d.get("last_time"),
        "provider":d.get("provider"),
        "realTime":d.get("realTime"),
        "exchange":d.get("exchange"),
    }

if __name__ == "__main__":
    specs=[("Yahoo",s,yahoo) for s in
           ("DX-Y.NYB","GC=F","SI=F","CL=F","BZ=F","^VIX","JPY=X","CHF=X")]
    specs += [("CNBC",s,cnbc) for s in
              (".DXY","DXY","DX=F","DX-Y.NYB","@GC.1","@GC.0","@SI.1","@SI.0",
               "@CL.1","@BZ.1","@BRN.1",".VIX","JPY=","CHF=","US10Y")]
    with ThreadPoolExecutor(max_workers=9) as pool:
        results=list(pool.map(lambda item:safe(*item),specs))
    print("OBSERVED_UTC",NOW.isoformat())
    for x in results:print(json.dumps(x,ensure_ascii=False,sort_keys=True))
