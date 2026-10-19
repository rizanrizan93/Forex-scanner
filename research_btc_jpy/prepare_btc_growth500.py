import pathlib,subprocess,sys,difflib,hashlib,json
out=pathlib.Path(sys.argv[1]);root=pathlib.Path(__file__).parent
subprocess.run([sys.executable,str(root/'prepare_btc_regime.py'),str(out)],check=True)
p=out/'engine.hpp';old=p.read_text();s=old.replace('stops[]={.5,.75,1.,1.5,2.,3.,4.}', 'stops[]={.5,.75,1.,1.5,2.,3.,4.,2.5}')
s=s.replace('int yearcounts[8]={};', 'double yearPnl[8]={};int yearcounts[8]={};')
s=s.replace('if(y>=0&&y<8)r.yearcounts[y]++;', 'if(y>=0&&y<8){r.yearcounts[y]++;r.yearPnl[y]+=pnl;}')
assert 'r.yearPnl[y]+=pnl' in s
p.write_text(s)
(out/'GROWTH500_DIFF.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),s.splitlines(True),fromfile='regime_engine.hpp',tofile='growth500_engine.hpp')))
(out/'GROWTH500_HASHES.json').write_text(json.dumps(dict(prior=hashlib.sha256(old.encode()).hexdigest(),adapter=hashlib.sha256(s.encode()).hexdigest()),indent=2))
