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
