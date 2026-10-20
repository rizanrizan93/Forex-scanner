from pathlib import Path
import subprocess,json,sys,os
root=Path(__file__).resolve().parent;sdk=Path(sys.argv[1]).resolve();mode=sys.argv[2]
refs=next((sdk/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net8.0'));csc=next((sdk/'sdk').glob('*/Roslyn/bincore/csc.dll'))
files=list((root/'source').rglob('*.cs'))+[root/'tests/Global.cs']
if mode=='btc':folder=root/'audit';name='BtcTests';files += [root/'replay/ApiStubs.cs',folder/(name+'.cs')]
elif mode=='replay':folder=root/'replay';name='Replay';files += [folder/'ApiStubs.cs',folder/(name+'.cs')]
else:folder=root/'validation'/mode;name=mode;files += list(folder.glob('*.cs'))
args=['-nologo','-target:exe','-langversion:latest','-nullable:enable','-define:REPLAY','-out:'+str(folder/(name+'.dll'))]+['-r:'+str(p) for p in refs.glob('*.dll')]+[str(p) for p in files]
rsp=folder/'build.rsp';rsp.write_text('\n'.join(args))
with (folder/'compile.log').open('w') as out:subprocess.run([str(sdk/'dotnet'),str(csc),'@'+str(rsp)],stdout=out,stderr=out,check=True)
(folder/(name+'.runtimeconfig.json')).write_text(json.dumps({'runtimeOptions':{'tfm':'net8.0','framework':{'name':'Microsoft.NETCore.App','version':'8.0.32'}}}))
if mode!='replay':
 cmd=[str(sdk/'dotnet'),str(folder/(name+'.dll'))]+sys.argv[3:]
 with (folder/'result.json').open('w') as out,(folder/'events.log').open('w') as err:subprocess.run(cmd,stdout=out,stderr=err,check=True)
 print((folder/'result.json').read_text())
