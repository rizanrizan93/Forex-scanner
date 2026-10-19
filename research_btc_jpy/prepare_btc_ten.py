import pathlib,re,hashlib,sys,json,difflib
o=pathlib.Path(sys.argv[1]);o.mkdir(exist_ok=True)
src=pathlib.Path('research_btc_jpy/search_btc_position_high.cpp').read_text()
modified=src.replace('const vector<S>& signals(const P&p)','const vector<S>& rawSignals(const P&p)')
modified=modified.replace('struct Model{','const vector<S>& signals(const P&p);\nstruct Model{')
modified=re.sub(r'const double risks\[\]=\{[^}]+\},margins\[\]=\{[^}]+\};','const double risks[]={.04,.06,.08,.1,.12,.15,.2,.25,.3,.4},margins[]={.3,.4,.5,.6,.75,.95};',modified)
assert modified!=src and 'rawSignals' in modified
(o/'engine.hpp').write_text(modified)
(o/'ORIGINAL_ENGINE.cpp').write_text(src)
(o/'ENGINE_DIFF.patch').write_text(''.join(difflib.unified_diff(src.splitlines(True),modified.splitlines(True),fromfile='ORIGINAL_ENGINE.cpp',tofile='engine.hpp')))
(o/'SOURCE_METADATA.json').write_text(json.dumps({'original_sha256':hashlib.sha256(src.encode()).hexdigest(),'engine_sha256':hashlib.sha256(modified.encode()).hexdigest(),'driver_sha256':hashlib.sha256(pathlib.Path('research_btc_jpy/btc_ten_million.cpp').read_bytes()).hexdigest()},indent=2))
