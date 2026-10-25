"""Adversarial OHLC sequencing checks; run python3 test_engine.py."""
import numpy as np
from run_study import replay

def fixture(side=1,entry=0,spread=0.):
    n=28000;p=np.zeros((n,6));p[:,0]=1546300800+np.arange(n)*60
    p[:,1:5]=100;p[:,5]=spread
    a=24001
    sig=np.array([[a,side,100,90 if side==1 else 110,5,side,p[a,0]]],float)
    return p,sig,np.zeros(n,dtype=np.int64),a

def run(p,s,b,entry=0,delay=0):
    return replay(p,s,b,entry,20,0,10,24,0,delay=delay)

p,s,b,a=fixture();p[a,1:5]=[100,130,99,125];p[a+1,1:5]=[120,122,110,115]
r=run(p,s,b);assert r[0,1]==a+1 and r[0,4]==120 # next bar adverse open, not old high minus trail
p,s,b,a=fixture();p[a,1:5]=[100,140,89,130]
r=run(p,s,b);assert r[0,1]==a and r[0,4]==90 and r[0,8]==0 # stop before favorable credit
p,s,b,a=fixture(-1,spread=1);p[a,1:5]=[100,102,70,75];p[a+1,1:5]=[80,85,78,82]
r=run(p,s,b);assert r[0,1]==a+1 and r[0,4]==81 # ask spread on SELL close
p,s,b,a=fixture();p[a,1:5]=[100,130,99,125];p[a+1,1:5]=[100,101,89,90]
r=run(p,s,b,entry=1);assert r[0,4]==90 and r[0,8]==0 # unknown fill-bar path cannot arm trailing
p,s,b,a=fixture();assert len(run(p,s,b,entry=1,delay=60))==0 # missed first touch cannot be recredited
p,s,b,a=fixture();b[a:]=1;assert len(run(p,s,b))==0 # warmup after a long missing interval
p,s,b,a=fixture();p[a,1:5]=[100,106,99,105];p[a+1,1:5]=[105,106,102,103]
r=replay(p,s,b,0,20,5,-.5,24,0)
assert r[0,4]>90 and r[0,8]>=6 # risk-relative trigger and distance function
print('7 adverse sequencing and coverage checks PASS')
