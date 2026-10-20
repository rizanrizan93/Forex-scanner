from pathlib import Path
import subprocess,json,sys
sdk=Path(sys.argv[1]).resolve();r=Path(__file__).resolve().parent/'replay';refs=next((sdk/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net8.0'));csc=next((sdk/'sdk').glob('*/Roslyn/bincore/csc.dll'))
a=['-nologo','-target:exe','-langversion:latest','-out:'+str(r/'GateTests.dll')]+['-r:'+str(p) for p in refs.glob('*.dll')]+[str(r/'BtcMacroGate.cs'),str(r/'GateTests.cs'),str(r.parent/'source/BtcCore.cs')]
(r/'gate.rsp').write_text('\n'.join(a));subprocess.run([str(sdk/'dotnet'),str(csc),'@'+str(r/'gate.rsp')],check=True)
(r/'GateTests.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net8.0','framework':{'name':'Microsoft.NETCore.App','version':'8.0.0','rollForward':'LatestPatch'}}}))
subprocess.run([str(sdk/'dotnet'),str(r/'GateTests.dll'),str(r.parent/'data')],check=True)
