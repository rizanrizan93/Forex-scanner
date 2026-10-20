"""Native .algo via official cTrader.Automate 1.0.21 tasks, no REPLAY define.
Vendor inputs: cTrader.Automate 1.0.21 and Microsoft.NETCore.App.Ref 6.0.36.
"""
from pathlib import Path
import argparse,subprocess,shutil,json
p=argparse.ArgumentParser();p.add_argument('--sdk',type=Path,required=True);a=p.parse_args();r=Path(__file__).resolve().parent;sdk=a.sdk.resolve();dotnet=sdk/'dotnet';csc=next((sdk/'sdk').glob('*/Roslyn/bincore/csc.dll'))
(r/'native').mkdir(exist_ok=True);(r/'builder').mkdir(exist_ok=True)
refs6=sorted((r/'vendor/net6ref/ref/net6.0').glob('*.dll'));refs8=sorted(next((sdk/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net8.0')).glob('*.dll'))
args=['-nologo','-target:library','-langversion:latest','-nullable:enable','-out:'+str(r/'native/RizanXauEurBtcPortfolio.dll')]+['-r:'+str(p) for p in refs6]+['-r:'+str(r/'vendor/automate/lib/net6.0/cAlgo.API.dll')]+[str(p) for p in (r/'source').rglob('*.cs')]+[str(r/'tests/Global.cs'),str(r/'AssemblyInfo.cs')]
rsp=r/'native/build.rsp';rsp.write_text('\n'.join(args))
with (r/'native/compile.log').open('w') as f:subprocess.run([str(dotnet),str(csc),'@'+str(rsp)],stdout=f,stderr=f,check=True)
for f in (r/'vendor/automate/tools/net6.0').glob('*.dll'):shutil.copy(f,r/'builder'/f.name)
sdkdir=next((sdk/'sdk').glob('8.*'))
for n in ['Microsoft.Build.Framework.dll','Microsoft.Build.Utilities.Core.dll']:shutil.copy(sdkdir/n,r/'builder'/n)
args=['-nologo','-target:exe','-langversion:latest','-out:'+str(r/'builder/BuildAlgo.dll')]+['-r:'+str(p) for p in refs8]+['-r:'+str(r/'builder'/n) for n in ['Microsoft.Build.Framework.dll','Microsoft.Build.Utilities.Core.dll']]+[str(r/'BuildAlgo.cs')]
rsp=r/'builder/build.rsp';rsp.write_text('\n'.join(args));subprocess.run([str(dotnet),str(csc),'@'+str(rsp)],check=True)
(r/'builder/BuildAlgo.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net8.0','framework':{'name':'Microsoft.NETCore.App','version':'8.0.32'}}}))
with (r/'native/bundle.log').open('w') as f:subprocess.run([str(dotnet),str(r/'builder/BuildAlgo.dll'),str(r)],cwd=r/'builder',stdout=f,stderr=f,check=True)
print((r/'native/bundle.log').read_text())
