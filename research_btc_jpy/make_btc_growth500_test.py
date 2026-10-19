import pathlib,sys,subprocess
root=pathlib.Path(__file__).parent;out=pathlib.Path(sys.argv[1])
subprocess.run([sys.executable,str(root/'make_btc_regime_test.py'),str(out)],check=True)
old=(out/'regime_fixtures.cpp').read_text();tail=old[old.index('template<class T,size_t N>int ix'):]
tail=tail.replace('configs.size()==7776,"profile_count7776"','configs.size()==10368,"profile_count10368"')
tail=tail.replace('int64_t t=parse("2020-01-01 00:00:00");', '''activate500(7844,0,.21,0,.95,.3);auto control=simulate(longP,true,parse("2019-01-01 00:00:00"),endtime);
 ck(abs(control.eq-955554.2421913373)<1e-5&&abs(control.dd-59.92601001623199)<1e-8&&control.buys==63&&control.sells==0,"growth_control955k_exact");
 int64_t t=parse("2020-01-01 00:00:00");''')
head=(root/'btc_growth500.cpp').read_text().split('void activate500(')[0]
fn=(root/'btc_growth500.cpp').read_text().split('void activate500(')[1].split('int main(int argc')[0]
(out/'growth500_fixtures.cpp').write_text(head+'void activate500('+fn+'\n'+tail)
