// Differential lookahead regression: mutate only future OHLC, compare all
// account results through an intraday cutoff. Never modifies replay input files.
#define main research_original_main
#ifdef SESSION_VARIANT
#include "search_sessions_direct.cpp"
#else
#include "search_direct_m1.cpp"
#endif
#undef main
void rebuild(){
 for(int i=0;i<3;i++)agg[i]=aggregate(widths[i]);h4=aggregate(240);templates.clear();
#ifdef SESSION_VARIANT
 days.clear();buildDays();
#endif
}
int main(int argc,char**argv){try{
 if(argc<4)return 2;symbol=argv[2];btc=symbol=="BTCUSD";load(argv[1]);rebuild();
 int64_t begin=parse("2019-01-01 00:00:00"),cut=parse("2023-05-15 13:30:00");
 vector<P> ps;vector<R> before;for(int i=0;i<500;i++){P p{};p.id=i;p.tf=pick(3);p.family=pick(12);p.look=pick(4);p.threshold=pick(3);p.trend=pick(3);p.session=pick(4);p.side=pick(3);p.stop=pick(6);p.tp=pick(8);p.hold=pick(4);p.risk=pick(8);p.margin=pick(3);p.layers=pick(3);p.be=pick(3);ps.push_back(p);before.push_back(simulate(p,true,begin,cut));}
 int changed=0;for(auto&b:minutes)if(b.t>=cut){b.o*=1.234;b.h*=1.234;b.l*=1.234;b.c*=1.234;changed++;}rebuild();
 for(size_t i=0;i<ps.size();i++){auto a=before[i],b=simulate(ps[i],true,begin,cut);if(a.eq!=b.eq||a.dd!=b.dd||a.bdd!=b.bdd||a.gain!=b.gain||a.loss!=b.loss||a.trades!=b.trades||a.wins!=b.wins||a.adds!=b.adds||a.skips!=b.skips||a.liquidations!=b.liquidations)throw runtime_error("PREFIX_INVARIANCE_FAILED id="+to_string(i));}
 ofstream f(argv[3]);f<<"{\"symbol\":\""<<symbol<<"\",\"tested_parameters\":500,\"cutoff_UTC\":\"2023-05-15 13:30:00\",\"future_bars_mutated_only_in_memory\":"<<changed<<",\"exact_prefix_results_equal\":true,\"scope\":\"Differential regression on500 configurations; not a proof of all platform behaviors. Modified future prices never persisted or used as historical data.\"}\n";cout<<"PREFIX_INVARIANCE_PASS "<<symbol<<" 500\n";
 }catch(exception&e){cerr<<e.what()<<endl;return 1;}}
