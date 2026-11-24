"""Apply after extend_native.py, on isolated research source only."""
from pathlib import Path
import sys,shutil
root=Path(sys.argv[1]);here=Path(__file__).resolve().parent
def edit(path,pairs):
    p=root/path;s=p.read_text()
    for a,b in pairs:
        assert s.count(a)==1,(path,a,s.count(a))
        s=s.replace(a,b)
    p.write_text(s)
shutil.copyfile(here/"EarlyRiskPolicy.cs",root/"native_replay/EarlyRiskPolicy.cs")
p=root/"native_replay/Replay.cs";s=p.read_text()
# Self-test before loading data.
needle="BrokerCalendar.CloseHour="
assert s.count(needle)==1
s=s.replace(needle,'if(args.Length==1&&args[0]=="--early-risk-selftest"){EarlyRiskPolicy.SelfTest();return;}\n'+needle)
needle="double EurStop=.845);"
assert s.count(needle)==1
s=s.replace(needle,"double EurStop=.845,int EarlyRiskMask=0,int EarlyRiskLook=8,double EarlyRiskThreshold=.5,double EarlyRiskFactor=.25,double EarlyRiskLimit=1000);")
needle="ReplaySizing.Reset();var scenario="
assert s.count(needle)==1
s=s.replace(needle,"EarlyRiskPolicy.Configure(profile.EarlyRiskMask,profile.EarlyRiskLook,profile.EarlyRiskThreshold,profile.EarlyRiskFactor,profile.EarlyRiskLimit);ReplaySizing.Reset();var scenario=")
assert s.count("trades.Add(new(")>=4
s=s.replace("trades.Add(new(","RecordV5(new(")
needle=" void Record(Leg l,DateTime at)"
assert s.count(needle)==1
s=s.replace(needle," void RecordV5(Trade t){trades.Add(t);EarlyRiskPolicy.Record(t.Symbol,t.Exit,t.Pnl);}\n"+needle)
p.write_text(s)
edit("source/xau/RizanRobot.cs",[
    ('Contract.Symbol=="EURUSD" ? FrozenCore.EurScale(_state.Eur) : 1,_state.PeakEquity,',
     '(Contract.Symbol=="EURUSD" ? FrozenCore.EurScale(_state.Eur) : 1)*EarlyRiskPolicy.Factor(Contract.Symbol,now,Account.Balance),_state.PeakEquity,')])
edit("source/eur/RizanRobot.cs",[
    ('Contract.Symbol=="EURUSD" ? Math.Min(FrozenCore.EurScale(_state.Eur),s.AsiaExtra ? .1 : 1) : 1,_state.PeakEquity);',
     '(Contract.Symbol=="EURUSD" ? Math.Min(FrozenCore.EurScale(_state.Eur),s.AsiaExtra ? .1 : 1) : 1)*EarlyRiskPolicy.Factor(Contract.Symbol,now,Account.Balance),_state.PeakEquity);')])
edit("source/BtcEngine.cs",[
    ("double reference=Math.Min(Account.Balance,Account.Equity),risk=(side>0?.23:.18)*RP.C.BtcRisk;risk=EntryFamilies.IsAdded(s.Origin)?Math.Min(risk,.025):risk;",
     "double reference=Math.Min(Account.Balance,Account.Equity),risk=(side>0?.23:.18)*RP.C.BtcRisk;risk=EntryFamilies.IsAdded(s.Origin)?Math.Min(risk,.025):risk;_earlyRiskFactor=EarlyRiskPolicy.Factor(Instrument,now,Account.Balance);risk*=_earlyRiskFactor;"),
    ("double BatchRiskFraction=>EntryFamilies.IsAdded(state.EntryOrigin)?Math.Min(RP.C.BtcBatchRisk,.025):RP.C.BtcBatchRisk;",
     "double _earlyRiskFactor=1;double BatchRiskFraction=>(EntryFamilies.IsAdded(state.EntryOrigin)?Math.Min(RP.C.BtcBatchRisk,.025):RP.C.BtcBatchRisk)*_earlyRiskFactor;"),
    ("double BatchMarginFraction=>EntryFamilies.IsAdded(state.EntryOrigin)?Math.Min(RP.C.BtcBatchMargin,.025):RP.C.BtcBatchMargin;",
     "double BatchMarginFraction=>(EntryFamilies.IsAdded(state.EntryOrigin)?Math.Min(RP.C.BtcBatchMargin,.025):RP.C.BtcBatchMargin)*_earlyRiskFactor;")])
print("V5 early-risk native research adapter applied; no economic parity claimed")
