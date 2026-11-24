from pathlib import Path
import shutil,json,hashlib
root=Path(__file__).resolve().parent
p=root/'native/native_replay/Replay.cs';s=p.read_text()
old='EurTarget=profile.EurTarget,BtcBatchOrders=profile.BtcBatchOrders,BtcBatchSeconds=profile.BtcBatchSeconds};ReplaySizing.Reset();'
new='EurTarget=profile.EurTarget,'+','.join(f'{k}=profile.{k}' for k in ['BtcBatchOrders','BtcBatchSeconds','BtcBatchRisk','BtcBatchMargin','BtcBatchZone','BtcBuyStop','BtcSellStop','BtcSellHours','XauTarget','XauStop','XauRisk','EurRisk','EurBE','EurStop'])+'};ReplaySizing.Reset();'
assert s.count(old)==1;s=s.replace(old,new)
old='int BtcBatchOrders=32,int BtcBatchSeconds=180);'
new='int BtcBatchOrders=32,int BtcBatchSeconds=180,double BtcBatchRisk=.025,double BtcBatchMargin=.1,double BtcBatchZone=.5,double BtcBuyStop=2,double BtcSellStop=1.5,double BtcSellHours=8,double XauTarget=4.5,double XauStop=2.4,double XauRisk=1.65,double EurRisk=.8,double EurBE=3,double EurStop=.845);'
assert s.count(old)==1;s=s.replace(old,new)
needle='EarlyPolicy.Mask=profile.EarlyXauOff?5:profile.EarlyMask;'
assert s.count(needle)==1
s=s.replace(needle,'if(profile.BtcBatchOrders<1||profile.BtcBatchOrders>128||profile.BtcBatchRisk<=0||profile.BtcBatchRisk>.025||profile.BtcBatchMargin<=0||profile.BtcBatchMargin>.1||profile.GrowthRisk<=0||profile.GrowthRisk>20.75||profile.XauRisk<=0||profile.XauRisk>1.65||profile.EurRisk<=0||profile.EurRisk>.8)throw new Exception("V8_PROFILE_OUTSIDE_RESEARCH_BOUNDS");'+needle)
p.write_text(s)
