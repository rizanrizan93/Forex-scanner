import pathlib,sys
root=pathlib.Path(__file__).parent;out=pathlib.Path(sys.argv[1])
s=(root/'btc_regime.cpp').read_text().split('int main(int argc,char**argv){')[0]
old=(root/'btc_both.cpp').read_text();s+='\n'+old.split('\n')[1]+'\nvoid parity(){'+old.split('void parity(){')[1].split('int main(')[0]
s+=r'''
int main(){
 directional=false;custom=false;engineFixtures();minutes.clear();templates.clear();
 setup("source/data/BTCUSD_M1.csv");parity();
 auto ck=[](bool ok,string s){if(!ok)throw runtime_error(s);cout<<"PASS "<<s<<endl;};
 geometry();ck(configs.size()==3888,"profile_count3888");
 int64_t t=parse("2020-01-01 00:00:00");P p{};p.stop=2;p.tp=3;p.hold=3;p.risk=findrisk(.05);p.margin=1;
 auto bars=[&](){minutes={{t,100,100.2,99.8,100},{t+1,100,102.2,99.9,102},{t+2,102,102.2,100.4,101},{t+3,101,101.2,100.8,101}};active={{0,0,1,0,1}};custom=true;directional=true;longP=shortP=p;shortRisk=shortMargin=-1;longExit=shortExit=0;stopAnchors.clear();entryRefs.clear();};
 bars();auto fixed=simulate(p,true,t,t+4);bars();longExit=2;auto trail=simulate(p,true,t,t+4);ck(trail.eq<fixed.eq&&trail.eq>100,"trailing_after_closed_bar_next_minute");
 bars();stopAnchors[0]=100.5;auto invalid=simulate(p,true,t,t+4);ck(invalid.trades==0&&invalid.skips==1,"invalid_structure_stop_reject");
 bars();entryRefs[0]=98;auto chase=simulate(p,true,t,t+4);ck(chase.trades==0&&chase.skips==1,"chase_filter_reject");
 bars();stopAnchors[0]=99.4;minutes[1].l=99.3;auto anchor=simulate(p,true,t,t+4);ck(anchor.trades==1&&anchor.eq<100,"structural_stop_executes");
 cout<<"REGIME_FIXTURES_PASS 5 plus9legacy and2baselineparity"<<endl;
}
'''
(out/'regime_fixtures.cpp').write_text(s)
