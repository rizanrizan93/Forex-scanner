"""Research adapter only. Apply AFTER Work's isolated patch, never to LIVE source."""
from pathlib import Path
import sys
root=Path(sys.argv[1]);p=root/"native_replay/Replay.cs";s=p.read_text()
old="EurTarget=profile.EurTarget};ReplaySizing.Reset();"
new="""EurTarget=profile.EurTarget,BtcBatchOrders=profile.BtcBatchOrders,BtcBatchSeconds=profile.BtcBatchSeconds,BtcBatchRisk=profile.BtcBatchRisk,BtcBatchMargin=profile.BtcBatchMargin,BtcBatchZone=profile.BtcBatchZone,BtcBuyStop=profile.BtcBuyStop,BtcSellStop=profile.BtcSellStop,BtcSellHours=profile.BtcSellHours,XauTarget=profile.XauTarget,XauStop=profile.XauStop,XauRisk=profile.XauRisk,EurRisk=profile.EurRisk,EurBE=profile.EurBE,EurStop=profile.EurStop};ReplaySizing.Reset();"""
assert s.count(old)==1
s=s.replace(old,new)
old="double BtcSellRsiMin=30);"
new="double BtcSellRsiMin=30,int BtcBatchOrders=32,int BtcBatchSeconds=180,double BtcBatchRisk=.025,double BtcBatchMargin=.1,double BtcBatchZone=.5,double BtcBuyStop=2,double BtcSellStop=1.5,double BtcSellHours=8,double XauTarget=4.5,double XauStop=2.4,double XauRisk=1.65,double EurRisk=.8,double EurBE=3,double EurStop=.845);"
assert s.count(old)==1;s=s.replace(old,new)
needle="EarlyPolicy.Mask=profile.EarlyXauOff?5:profile.EarlyMask;"
assert s.count(needle)==1
s=s.replace(needle,"""if(profile.BtcBatchOrders<1||profile.BtcBatchOrders>128||profile.BtcBatchRisk<=0||profile.BtcBatchRisk>.025||profile.BtcBatchMargin<=0||profile.BtcBatchMargin>.1||profile.GrowthRisk<=0||profile.GrowthRisk>20.75||profile.XauRisk<=0||profile.XauRisk>1.65||profile.EurRisk<=0||profile.EurRisk>.8)throw new Exception("V5_PROFILE_OUTSIDE_RESEARCH_BOUNDS");"""+needle)
p.write_text(s)
print("V5 isolated native adapter applied; controls retain frozen defaults; no economic parity claimed")
