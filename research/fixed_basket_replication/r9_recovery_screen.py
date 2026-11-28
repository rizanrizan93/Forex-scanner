"""Reconstructed documented R9 method; not original kernel/native replay.
Run: python r9_recovery_screen.py /private/RIZAN_BTC2325_REPLAY_REPRODUCIBLE_2019_2026.zip
"""
import csv,gzip,hashlib,io,json,math,zipfile,sys
from datetime import datetime
P=[('R9_DEFENSIVE',[.7502,1.5,1.5,1.3,1.1313,.9853,.4,.4821,.025,.4571],[19834124349.457973,10164244141.887169]),('R9_BALANCED',[.8,1.25,1.5,1.3,1.2,1.1,.4,.8,.02,.5],[79905620743.48389,35583981985.40277]),('R9_GROWTH',[.827,1.5,1.5,1.3,1.1863,1,.4518,.7168,.025,.41],[91727608297.55418,48447118957.962395]),('R9_AGGRESSIVE',[.9,1.5,1.5,1.3,1.2,1.1,.4,.6,.02,.4],[102720206210.24275,28915077365.888878])]
H=[['9b92931a3b54f4ffb34253c3ee8a4d2e0ec8cfe01586b1e634dd32100fc20835','143b2e428aa9f2d45f621256568bbd2ca4701d5e828a3f0b5c21f7fb1dd52f9e'],['2f017adc2deea0a6fd92ed40672d22a1c9e9b2dc8fc599bb2727509e26d07600','8fba6817f23cf2c4763252e01c4b4f23137efd4c1a6e4b4ae712b6790817bb0a']]
def utc(x):return datetime.fromisoformat(x.replace('Z','+00:00'))
def load(z,c):
    names=[f'replay_source/inputs/P3_BUY050_B_cost{c}.json.gz',f'BTC_extra_269_baskets_cost{c}.csv']
    b=[z.read(n) for n in names]
    assert [hashlib.sha256(x).hexdigest() for x in b]==H[c-1]
    return json.loads(gzip.decompress(b[0])),list(csv.DictReader(io.StringIO(b[1].decode('utf-8-sig'))))
def sim(j,extra,c,p):
    events=[];core=j['Ledger']
    for kind,rows in enumerate([core,extra]):
        for i,r in enumerate(rows):
            a,b=(r['Entry'],r['Exit']) if kind==0 else (r['entry_utc'],r['exit_utc'])
            events.extend([(utc(a),1,kind,i),(utc(b),0,kind,i)])
    cash=peak=original=100.;dd=0.;openp={};busy=n=accepted=0;pfp=pfn=0.
    for t,entry,k,i in sorted(events):
        key=(k,i)
        if entry:
            if cash<=0:continue
            d=1-cash/peak
            if not k:
                r=core[i];base=original
                phase=p[3] if cash<1000 else p[4] if cash<100000 else p[5]
                scale=p[{'XAUUSD':0,'EURUSD':1,'BTCUSD':2}[r['Symbol']]]
                guard=p[7] if d>=p[6] else 1.
                openp[key]=float(r['Pnl'])/base*cash*phase*scale*guard
            else:
                if busy or d>=p[9]:continue
                r=extra[i];px=float(r['entry_px']);stop=float(r['stop_px'])
                cost=abs(px-stop)+px*(.0005+.0012*c)
                q=math.floor(min(cash*p[8]/cost,cash*.1*200/px,3200)*100)/100
                if q<.01:continue
                openp[key]=float(r['pnl_usd'])/float(r['btc_qty'])*q;busy=1;accepted+=1
        elif key in openp:
            pnl=openp.pop(key);cash+=pnl;peak=max(cash,peak);dd=max(dd,1-cash/peak);n+=1
            if k:busy=0
            if pnl>0:pfp+=pnl
            else:pfn-=pnl
        if not entry and not k:original+=float(core[i]['Pnl'])
    return dict(balance=cash,closedDD=dd*100,baskets=n,extraAccepted=accepted,profitFactor=pfp/pfn,open=len(openp))
def main(path):
    out={'status':'RECONSTRUCTED_DOCUMENTED_METHOD_NOT_ORIGINAL_KERNEL','nativeReplayExecuted':False,'floatingDD':None,'scenarios':[]}
    with zipfile.ZipFile(path) as z:
        for c in [1,2]:
            j,e=load(z,c)
            for name,p,expected in P:
                a=sim(j,e,c,p);target=expected[c-1]
                a.update(profile=name,cost=c,expected=target,relativeError=(a['balance']/target-1),parity=abs(a['balance']/target-1)<1e-8)
                out['scenarios'].append(a)
    return out
if __name__=='__main__':
    print(json.dumps(main(sys.argv[1]),indent=2))
