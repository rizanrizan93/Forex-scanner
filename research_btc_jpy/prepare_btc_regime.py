"""Isolated research adapter. Keep old engine/model; add causal directional geometry."""
import pathlib,subprocess,sys,difflib,json,hashlib
out=pathlib.Path(sys.argv[1]);subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('prepare_btc_both.py')),str(out)],check=True)
p=out/'engine.hpp';old=p.read_text();s=old
s=s.replace('struct Model{','bool directional=false;P longP{},shortP{};int longExit=0,shortExit=0;\nmap<int,double> stopAnchors,entryRefs;\nstruct Model{')
s=s.replace('R simulate(const P&p,bool m1','R simulate(const P&base,bool m1')
s=s.replace('m1?minutes:agg[p.tf]','m1?minutes:agg[base.tf]')
s=s.replace('for(auto&s:signals(p)){int64_t st=', 'for(auto&s:signals(base)){const P&p=directional?(s.side>0?longP:shortP):base;int64_t st=')
s=s.replace('dist=stops[p.stop]*s.atr;', 'dist=stops[p.stop]*s.atr;\n  const int skey=side>0?s.mi:-s.mi-1;\n  if(directional&&entryRefs.count(skey)&&side*(first-entryRefs.at(skey))>.5*s.atr){r.skips++;continue;}\n  if(directional&&stopAnchors.count(skey)){double anchor=stopAnchors.at(skey);dist=side*(first-anchor);if(dist<.5*s.atr||dist>3.*s.atr){r.skips++;continue;}}')
# dist must be mutable after initial fill.
s=s.replace('const double first=v[idx].o+(side>0?spread(v[idx].o):0)+side*slip(v[idx].o),dist=', 'const double first=v[idx].o+(side>0?spread(v[idx].o):0)+side*slip(v[idx].o);double dist=')
needle='   if(p.be&&!breakeven)'
s=s.replace(needle,'   if(directional&&(side>0?longExit:shortExit)==2&&side*(close-first)>=1.5*dist){double proposed=close-side*1.5*dist;sl=side>0?max(sl,proposed):min(sl,proposed);}\n'+needle)
assert 'const P&p=directional' in s and 'entryRefs.at' in s and 'longExit:shortExit' in s
p.write_text(s)
(out/'REGIME_ADAPTER_DIFF.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),s.splitlines(True),fromfile='prior_engine.hpp',tofile='regime_engine.hpp')))
(out/'REGIME_SOURCE_HASHES.json').write_text(json.dumps(dict(prior_engine_sha256=hashlib.sha256(old.encode()).hexdigest(),new_engine_sha256=hashlib.sha256(s.encode()).hexdigest()),indent=2))
