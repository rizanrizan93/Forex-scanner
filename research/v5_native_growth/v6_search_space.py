"""Native V6 challenger parameter space. Enumerates without materializing 201M JSON objects.
No claim of economic replay until exact market inputs and native receipts exist.
"""
import argparse, json, math, random
from pathlib import Path
AXES=[
 ("SeedUniverse",[1,4,0]), # EUR, EUR+XAU, all, mapped to original native enum
 ("EarlyRiskMask",[2,5,7]),
 ("EarlyRiskLook",[4,6,8,12]),
 ("EarlyRiskThreshold",[.4,.5,.6]),
 ("EarlyRiskFactor",[.25,.5,.75]),
 ("EarlyRiskLimit",[500,1000,1500,2000]),
 ("BtcBuyTarget",[12,16,18,24]),
 ("BtcBuyHours",[48,72,128,160]),
 ("BtcBatchOrders",[32,64,128]),
 ("XauTarget",[3.5,4.5,5.5,7]),
 ("XauStop",[1.8,2.4,3]),
 ("EurTarget",[6,8,10,12,15]),
 ("EurBE",[2,3,4]),
 ("EurStop",[.7,.845,1]),
 ("EarlyMask",[5,7]),
 ("BtcBuyRsiMax",[75,85,100]),
]
SPACE=math.prod(len(v) for _,v in AXES)
assert SPACE==201553920
SEED=dict(Base=3,Sl=2,Tp=3,Hold=2,Trend=2,Session=0,Risk=5,Universe=1,Day=1,Threshold=3,Direction=1,SeedOnly=False,HandoffEquity=125)
BASE=dict(Mode="off",Year=2019,EndYear=2026,Seed=SEED,GrowthRisk=20.75,EarlyMask=7,EarlyThreshold=1000)
CONTROL=dict(BASE,Id="V6_CONTROL")
LOCK=dict(BASE,Id="V6_LOCK_2091M",EarlyRiskMask=2,EarlyRiskLook=8,EarlyRiskThreshold=.6,EarlyRiskFactor=.25,EarlyRiskLimit=1500)
WORK=dict(BASE,Id="V6_WORK_BTC18H72",EarlyMask=5,BtcBuyTarget=18,BtcBuyHours=72)
def decode(i):
    if not 0<=i<SPACE:raise ValueError(i)
    original=i;p={}
    for name,vals in reversed(AXES):
        i,j=divmod(i,len(vals));p[name]=vals[j]
    seed=dict(SEED,Universe=p.pop("SeedUniverse"))
    return {**BASE,**p,"Seed":seed,"Id":f"V6_{original:09d}"}
def encode(p):
    i=0
    for name,vals in AXES:
        x=p["Seed"]["Universe"] if name=="SeedUniverse" else p[name]
        i=i*len(vals)+vals.index(x)
    return i
def pilot(n):
    # Deterministic spread through all dimensions; sample first, no random
    # hindsight fit. Full space can be addressed by integer index.
    assert 0<=n<=SPACE
    ids=random.Random(20261124).sample(range(SPACE),n)
    return [CONTROL,LOCK,WORK]+[decode(i) for i in ids]
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--pilot",type=int,default=256)
    p.add_argument("--out",type=Path,default=Path("v6_pilot.json"))
    p.add_argument("--offset",type=int)
    a=p.parse_args()
    profiles=pilot(a.pilot) if a.offset is None else [CONTROL,LOCK,WORK]+[decode(i) for i in range(a.offset,min(SPACE,a.offset+a.pilot))]
    sample=[0,1,SPACE//2,SPACE-1]+random.Random(42).sample(range(SPACE),10000)
    assert all(encode(decode(i))==i for i in sample)
    assert len({v["Id"] for v in profiles})==len(profiles)
    a.out.write_text(json.dumps(profiles,indent=2)+"\n")
    print(json.dumps({"nominal_native_parameter_space":SPACE,"profiles_emitted":len(profiles),"roundtrip_tests":len(sample),"actual_native_replays":0,"production_changes":False}))
if __name__=="__main__":main()
