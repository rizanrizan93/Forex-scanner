from pathlib import Path
import subprocess,json
r=Path(__file__).resolve().parent;root=r.parent;sdk=root/'dotnet';w=r/'work';src=(w/'replay/Replay.cs').read_text();header=src[:src.index('BrokerCalendar.CloseHour=')];body=src[src.index('record struct Row('):];main='var isXau=args[2]=="xau";var d=Data.Load(args[0],isXau,2026);var tape=TapeCache.LoadOrBuild(args[1],isXau,()=>isXau?Data.XauTape(d):Data.EurTape(d));Console.WriteLine("SIGNALS="+tape.Signals.Count);\n'
f=r/'tape_builder';f.mkdir(exist_ok=True);(f/'TapeBuilder.cs').write_text(header+main+body)
refs=next((sdk/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net8.0'));csc=next((sdk/'sdk').glob('*/Roslyn/bincore/csc.dll'))
files=list((w/'source').rglob('*.cs'))+[w/'tests/Global.cs',w/'replay/ApiStubs.cs',f/'TapeBuilder.cs']
rsp=f/'build.rsp';rsp.write_text('\n'.join(['-nologo','-target:exe','-langversion:latest','-nullable:enable','-define:REPLAY','-out:'+str(f/'TapeBuilder.dll')]+['-r:'+str(p) for p in refs.glob('*.dll')]+[str(p) for p in files]))
with (f/'compile.log').open('w') as out:subprocess.run([str(sdk/'dotnet'),str(csc),'@'+str(rsp)],stdout=out,stderr=out,check=True)
(f/'TapeBuilder.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net8.0','framework':{'name':'Microsoft.NETCore.App','version':'8.0.32'}}}))
