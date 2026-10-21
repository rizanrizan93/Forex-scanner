"""cTrader delta-tick decoding and strictly as-of reference spread."""
import math

def decode(response):
    rows=list(response.tickData)
    if not rows:return []
    t=p=0;out=[]
    for k,row in enumerate(rows):
        t=int(row.timestamp) if k==0 else t+int(row.timestamp)
        p=int(row.tick) if k==0 else p+int(row.tick)
        out.append((t,p/100000.))
    out.reverse()
    if any(out[i][0]>out[i+1][0] for i in range(len(out)-1)):raise ValueError('Tick order invalid')
    return out


def spread_asof(bid,ask,at):
    if bid.hasMore or ask.hasMore:return None
    values=[]
    for r in (bid,ask):
        q=[(t,p) for t,p in decode(r) if t<=at]
        if not q or at-q[-1][0]>20000:return None
        values.append(q[-1][1])
    b,a=values
    if not all(math.isfinite(x) and x>0 for x in values) or a<b or a-b>50:return None
    return a-b


def entry_open_quote(bid,ask,anchor,until):
    """First observed BID of new M1, plus ASK known then; no forming OHLC.

    Caller must request the complete BID range starting exactly at anchor.
    Truncated ranges cannot establish the first tick and are rejected.
    """
    if bid.hasMore or ask.hasMore:return None
    b=[(t,p) for t,p in decode(bid) if anchor<=t<=until]
    if not b or b[0][0]>=anchor+60000:return None
    t,price=b[0]
    a=[(tm,p) for tm,p in decode(ask) if tm<=t]
    if not a or t-a[-1][0]>20000:return None
    spread=a[-1][1]-price
    if not math.isfinite(price) or price<=0 or not 0<=spread<=50:return None
    return dict(price=price,spread=spread,observed_ms=t)
