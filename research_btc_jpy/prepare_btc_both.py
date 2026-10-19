import pathlib,re,json,difflib,hashlib,sys
root=pathlib.Path(__file__).parent
out=pathlib.Path(sys.argv[1]);out.mkdir(exist_ok=True)
src=(root/'search_btc_position_high.cpp').read_text()
r=[.10,.15,.20,.25,.30,.40,.50,.60]
r+= [round(i/100,2) for i in range(1,41) if round(i/100,2) not in r]
m=[.5,.75,.95];m+=[round(i/100,2) for i in range(10,96) if round(i/100,2) not in m]
s=src.replace('const vector<S>& signals(const P&p)','const vector<S>& rawSignals(const P&p)')
s=s.replace('struct Model{','const vector<S>& signals(const P&p);\ndouble shortRisk=-1,shortMargin=-1;\nstruct Model{')
s=re.sub(r'const double risks\[\]=\{[^}]+\},margins\[\]=\{[^}]+\};','const double risks[]={'+','.join(map(str,r))+'},margins[]={'+','.join(map(str,m))+'};',s)
s=s.replace('stops[]={.5,.75,1.,1.5,2.,3.}','stops[]={.5,.75,1.,1.5,2.,3.,4.}')
s=s.replace('int trades=0,wins=0,adds=0,skips=0,liquidations=0;','int trades=0,wins=0,adds=0,skips=0,liquidations=0,buys=0,sells=0;double buyPnl=0,sellPnl=0;')
s=s.replace('const double frac=margins[p.margin],risk=risks[p.risk];','const double frac=side<0&&shortMargin>=0?shortMargin:margins[p.margin],risk=side<0&&shortRisk>=0?shortRisk:risks[p.risk];')
s=s.replace('r.trades++;r.adds+=adds;','r.trades++;if(side>0){r.buys++;r.buyPnl+=pnl;}else{r.sells++;r.sellPnl+=pnl;}r.adds+=adds;')
assert 'shortMargin>=0' in s and 'r.sells++' in s
(out/'engine.hpp').write_text(s)
(out/'ORIGINAL_ENGINE.cpp').write_text(src)
(out/'ENGINE_DIFF.patch').write_text(''.join(difflib.unified_diff(src.splitlines(True),s.splitlines(True),fromfile='ORIGINAL_ENGINE.cpp',tofile='engine.hpp')))
driver=(root/'btc_ten_million.cpp').read_text().split('int main(int argc,char**argv){')[0]
driver=driver.split('void sanity(){')[0]
(out/'shared_driver.hpp').write_text(driver)
(out/'SOURCE_HASHES.json').write_text(json.dumps({'source_sha256':hashlib.sha256(src.encode()).hexdigest(),'adapter_sha256':hashlib.sha256(s.encode()).hexdigest()},indent=2))
