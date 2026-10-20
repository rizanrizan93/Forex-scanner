from pathlib import Path
import shutil,difflib,json,hashlib
r=Path(__file__).resolve().parent;origin=r.parent/'research_weekend_v121/work';w=r/'work';w.mkdir(exist_ok=True)
for n in ['source','tests','replay','validation','audit']:
 for p in list((origin/n).rglob('*.cs'))+list((origin/n).rglob('*.csproj')):
  dest=w/p.relative_to(origin);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
for n in ['run_local.py','build_native.py','BuildAlgo.cs','AssemblyInfo.cs']:shutil.copy2(origin/n,w/n)
# Vendor dependencies are copied for native compilation only, never shipped as strategy source.
shutil.copytree(origin/'vendor',w/'vendor',dirs_exist_ok=True)
changes=[]
def edit(n,fn):
 p=w/n;before=p.read_text();after=fn(before);p.write_text(after);changes.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='V121/'+n,tofile='LF122/'+n))
def engine(s):
 s=s.replace('risk=side>0?.23:.18,margin=side>0?.95:.30','risk=side>0?.23:.18')
 s=s.replace('Math.Min(100,Math.Min(reference*risk/riskUnit,reference*margin/(fill*(.1+.0005))))','Math.Min(100,reference*risk/riskUnit)')
 return s.replace('RIZAN BTC 8500283 V1 ','RIZAN BTC LF122 ')
def host(s):
 s=s.replace('internal double ResearchBtcMargin(Position p)=>p.VolumeInUnits*(Symbols.GetSymbol("BTCUSD").PipValue/Symbols.GetSymbol("BTCUSD").PipSize)*p.EntryPrice/10;','internal double ResearchBtcMargin(Position p)=>Symbols.GetSymbol("BTCUSD").GetEstimatedMargin(p.TradeType,p.VolumeInUnits);')
 s=s.replace('internal double ReservedMargin()=>Account.Margin+Positions.Where(p=>p.SymbolName=="BTCUSD").Sum(p=>Math.Max(0,ResearchBtcMargin(p)-Symbols.GetSymbol("BTCUSD").GetEstimatedMargin(p.TradeType,p.VolumeInUnits)));','internal double ReservedMargin()=>Account.Margin;')
 s=s.replace('        // Never grant BTC the account\'s 200x leverage in the model budget.\n        units=Math.Min(units,marginAvailable/(value*price*(.1+.0005)));','        // Follow broker-estimated symbol margin, as XAU/EUR do. No fixed BTC leverage floor.')
 s=s.replace('Math.Max(q*value*price/10,sym.GetEstimatedMargin(side>0?TradeType.Buy:TradeType.Sell,q))','sym.GetEstimatedMargin(side>0?TradeType.Buy:TradeType.Sell,q)')
 s=s.replace('if(after>0&&OpenRisk()+pendingRisk+q*value*(distance+price*.0012)<=after*PortfolioRiskPercent/100&&ReservedMargin()+pendingMargin+margin<=after*.5&&margin+q*value*price*.0005<=Account.FreeMargin-pendingMargin)', 'if(double.IsFinite(margin)&&margin>0&&after>0&&OpenRisk()+pendingRisk+q*value*(distance+price*.0012)<=after*PortfolioRiskPercent/100&&margin<=marginAvailable&&margin+q*value*price*.0005<=reference*(side>0?.95:.30)&&ReservedMargin()+pendingMargin+margin<=after*.5&&margin+q*value*price*.0005<=Account.FreeMargin-pendingMargin)')
 return s.replace('RIZAN THREE FROZEN V121 ','RIZAN THREE LF122 ').replace('version=1.2.1-three-frozen-weekend','version=1.2.2-research-leverage-follow')
edit('source/BtcEngine.cs',engine);edit('source/PortfolioHost.cs',host)
edit('source/RizanXauEurPortfolio.cs',lambda s:s.replace('class RizanXauEurBtcPortfolio :','class RizanXauEurBtcLeverageFollow :'))
edit('source/RizanPortfolio.csproj',lambda s:s.replace('<Version>1.2.1</Version>','<Version>1.2.2</Version>'))
edit('AssemblyInfo.cs',lambda s:s.replace('1.2.1.0','1.2.2.0'))
edit('BuildAlgo.cs',lambda s:s.replace('RizanXauEurBtcPortfolio_FROZEN_WEEKEND_V1_2_1.algo','RizanXauEurBtcPortfolio_RESEARCH_LEVERAGE_FOLLOW_V1_2_2.algo'))
edit('replay/Replay.cs',lambda s:s.replace('??"10",CultureInfo.InvariantCulture)','??"200",CultureInfo.InvariantCulture)'))
(r/'CHANGE_FROM_V121.diff').write_text(''.join(changes))
for sub in ['xau','eur']:
 for p in (origin/'source'/sub).glob('*.cs'):assert p.read_bytes()==(w/p.relative_to(origin)).read_bytes()
print('Prepared LF122; eight XAU/EUR source files unchanged; no changes to BtcCore/BtcWeekendPolicy')

# The regression fixture must address the variant's isolated checkpoint key.
p=w/'validation/WeekendTests/WeekendTests.cs';p.write_text(p.read_text().replace('RIZAN BTC 8500283 V1 ','RIZAN BTC LF122 '))
f=w/'validation/LeverageTests';f.mkdir(exist_ok=True)
shutil.copy2(r/'tests/LeverageTests.cs',f/'LeverageTests.cs')
shutil.copy2(w/'replay/ApiStubs.cs',f/'ApiStubs.cs');shutil.copy2(w/'tests/Global.cs',f/'Global.cs')

p=w/'audit/BtcTests.cs';p.write_text(p.read_text().replace('RIZAN BTC 8500283 V1 ','RIZAN BTC LF122 '))
