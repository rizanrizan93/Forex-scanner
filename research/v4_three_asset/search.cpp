// Research-only hierarchical search. Inherits pinned M1 outcome implementation.
// Not a native Frozen V1 ledger, no broker IO.
#include "../frozen_v1_10b_20261124/screen_prefix.cpp"
#include <iomanip>
struct Group{int trend,session,mask,dir;};
struct Config{int seedrisk,growthrisk,daily,loss,win;};
const double SR[]={.03,.05,.08}, GR[]={.02,.03,.05};
const int DM[]={1,2,4,6}, LC[]={0,15,30,60}, WC[]={0,2,5};
constexpr int GROUPS=3*6*7*3, LEAVES=3*3*4*4*3;
constexpr uint64_t SPACE=36ULL*4*5*6*GROUPS*LEAVES;
static_assert(SPACE==705438720ULL);
bool match(const Event&e,const Group&g){
 return (g.mask&(1<<e.symbol))&&(e.trend&(1<<g.trend))&&session(e,g.session)
 &&(g.dir==0||(g.dir==1&&e.side>0)||(g.dir==2&&e.side<0));
}
struct Gate{int n=0,positive=0;double sum=0,gain=0,loss=0;};
Gate signalgate(const vector<Event>&v){
 Gate q;array<double,4> yr{};int64_t next=CUTS[0];
 for(const auto&e:v){
  if(e.t>=CUTS[4])break;
  if(e.t<next||e.t<CUTS[0]||e.risk<=0)continue;
  int y=upper_bound(CUTS,CUTS+5,e.t)-CUTS-1;
  if(y<0||y>=4||e.exit>CUTS[y+1])continue;
  double r=e.pnl/e.risk;q.n++;q.sum+=r;yr[y]+=r;
  if(r>0)q.gain+=r;else q.loss-=r;
  next=e.exit;
 }
 for(double v:yr)q.positive+=v>0;
 return q;
}
bool signalpass(const Gate&q){return q.n>=40&&q.positive>=3&&q.sum/q.n>.02&&q.gain>1.08*q.loss;}
struct Annual{double cash=100,dd=0;int n=0,wins=0,gaps=0;int64_t g125=0,g250=0,g1000=0;uint64_t trace=1469598103934665603ULL;};
Annual wallet(const vector<Event>&v,int year,const Config&c){
 Annual a;double peak=100;int day=-1,used=0;bool graduated=false;
 int64_t next=CUTS[year];
 auto it=lower_bound(v.begin(),v.end(),CUTS[year],[](const Event&e,int64_t t){return e.t<t;});
 for(;it!=v.end();++it){
  const auto&e=*it;if(e.t>=CUTS[year+1])break;
  if(e.t<next||e.exit>CUTS[year+1]||e.risk<=0)continue;
  int d=e.t/1440;if(d!=day){day=d;used=0;}if(used>=DM[c.daily])continue;
  double risk=graduated?GR[c.growthrisk]:SR[c.seedrisk];
  double units=floor(min({a.cash*risk/(e.risk+risk*e.cost),a.cash*.5/(e.margin+.5*e.cost),MAXSTEPS[e.symbol]})+1e-12);
  if(!isfinite(units)||units<1)continue;
  peak=max(peak,a.cash+units*e.mfe);
  a.dd=max(a.dd,(peak-(a.cash+units*e.mae))/peak);
  a.cash+=units*e.pnl;peak=max(peak,a.cash);a.dd=max(a.dd,(peak-a.cash)/peak);
  a.n++;a.wins+=e.pnl>0;a.gaps+=e.gap>0;used++;
  a.trace=mix(mix(mix(a.trace,e.t),e.symbol),bit_cast<uint64_t>(units));
  a.trace=mix(a.trace,e.exit);
  if(a.cash>=125&&!a.g125){a.g125=e.exit;graduated=true;}
  if(a.cash>=250&&!a.g250)a.g250=e.exit;
  if(a.cash>=1000&&!a.g1000)a.g1000=e.exit;
  next=e.exit+(e.pnl<0?LC[c.loss]:WC[c.win]);
  if(a.dd>=.60||a.cash<=0)break;
 }
 return a;
}
struct Fold{int n=0,g125=0,g250=0,g1000=0,trades=0,wins=0,gaps=0;double worst=1e99,dd=0,logsum=0;uint64_t trace=1469598103934665603ULL;};
Fold fold(const array<vector<Event>,2>&ev,const Config&c,int lo,int hi){
 Fold f;for(int z=0;z<2;z++)for(int y=lo;y<hi;y++){
  auto a=wallet(ev[z],y,c);f.n++;f.g125+=a.g125!=0;f.g250+=a.g250!=0;f.g1000+=a.g1000!=0;
  f.trades+=a.n;f.wins+=a.wins;f.gaps+=a.gaps;f.worst=min(f.worst,a.cash);f.dd=max(f.dd,a.dd);
  f.logsum+=log(max(.000001,a.cash)/100);f.trace=mix(f.trace,a.trace);
 }return f;
}
bool devpass(const Fold&f){return f.n==8&&f.g125>=6&&f.g250>=4&&f.g1000>=1&&f.worst>=60&&f.dd<.60&&f.logsum>0;}
bool evalpass(const Fold&f){return f.n==6&&f.g125>=4&&f.g250>=2&&f.worst>=60&&f.dd<.60&&f.logsum>0;}
int main(int argc,char**argv){
 if(argc==2&&string(argv[1])=="--selftest"){
  Group g{2,0,1,1};Config c{2,2,3,0,0};
  Event e{CUTS[0]+10,CUTS[0]+11,0,7,1,1,5,0,30,30,-1,0};
  if(!match(e,g)||match(e,{2,0,4,1})||match(e,{2,0,1,2}))throw runtime_error("group filter");
  auto a=wallet({e},0,c);if(a.n!=1||a.cash<=125||a.g125==0)throw runtime_error("graduation");
  e.risk=1000;if(wallet({e},0,c).n)throw runtime_error("unaffordable");
  e.risk=1;e.t=CUTS[4]+10;e.exit=e.t+1;if(signalgate({e}).n)throw runtime_error("future fold leakage");
  Event gold=e; gold.symbol=1; gold.risk=9; gold.margin=20; gold.t=CUTS[0]+10;gold.exit=gold.t+1; if(wallet({gold},0,c).n)throw runtime_error("XAU minimum unit affordability");gold.risk=2;if(wallet({gold},0,c).n!=1)throw runtime_error("XAU affordable unit");if(!match(gold,{2,0,2,1})||match(gold,{2,0,5,1}))throw runtime_error("XAU mask");
  cout<<"PASS XAU affordability, synthetic chronology, minlot, direction, graduation, fold isolation; space="<<SPACE<<" real_replays=0\n";return 0;
 }
 if(argc!=3){cerr<<"usage: search ROOT BASE_0_TO_35\n";return 2;}
 fs::path root=argv[1];int base=stoi(argv[2]);if(base<0||base>=36)return 2;
 for(int s:{0,1,2}){
  assets[s].t=readbin<int64_t>(root/"data"/(to_string(s)+"_times.i64"));
  assets[s].b=readbin<Bar>(root/"data"/(to_string(s)+"_m1.f64"));
  if(assets[s].t.size()!=assets[s].b.size()||assets[s].t.empty())throw runtime_error("bad price input");
 }
 vector<Candidate>cand;for(int s:{0,1,2}){
  auto a=readbin<Candidate>(root/"data"/("base"+to_string(base)+"_symbol"+to_string(s)+".bin"));
  for(const auto&c:a)if(c.symbol!=s||c.idx<0||size_t(c.idx)>=assets[s].t.size()||assets[s].t[c.idx]!=c.t)throw runtime_error("bad tape");
  cand.insert(cand.end(),a.begin(),a.end());
 }
 sort(cand.begin(),cand.end(),[](const auto&a,const auto&b){return a.t<b.t||(a.t==b.t&&a.symbol<b.symbol);});
 fs::create_directories(root/"results");string stem="v4_base"+to_string(base);
 ofstream out(root/"results"/(stem+".csv"));out<<setprecision(12);
 out<<"base,sl,tp,hold,trend,session,mask,dir,seedrisk,growthrisk,daily,losscool,wincool,dev125,dev250,dev1000,devworst,devdd,devlog,devtrades,devwins,devgaps,devtrace,devpass,eval125,eval250,eval1000,evalworst,evaldd,evallog,evalpass,partial125,partial250,partial1000,partialworst,partialdd\n";
 uint64_t groups=0,group_pass=0,wallets=0,dev_pass=0,eval_pass=0,annuals=0;
 unordered_set<uint64_t> traces;
 for(int sl=0;sl<4;sl++)for(int tp=0;tp<5;tp++)for(int hold=0;hold<6;hold++){
  array<vector<Event>,2> events;
  for(int z=0;z<2;z++)for(const auto&c:cand){auto e=outcome(c,sl,tp,hold,z+1);if(e.risk>0)events[z].push_back(e);}
  for(int tr=0;tr<3;tr++)for(int se=0;se<6;se++)for(int mask=1;mask<=7;mask++)for(int dir=0;dir<3;dir++){
   groups++;Group g{tr,se,mask,dir};array<vector<Event>,2> ev;
   for(int z=0;z<2;z++)for(const auto&e:events[z])if(match(e,g))ev[z].push_back(e);
   if(!signalpass(signalgate(ev[0]))||!signalpass(signalgate(ev[1])))continue;
   group_pass++;
   for(int sr=0;sr<3;sr++)for(int gr=0;gr<3;gr++)for(int d=0;d<4;d++)for(int l=0;l<4;l++)for(int w=0;w<3;w++){
    Config c{sr,gr,d,l,w};auto f=fold(ev,c,0,4);wallets++;annuals+=f.n;bool ok=devpass(f);
    Fold test,partial;bool ok2=false;
    if(ok){dev_pass++;traces.insert(f.trace);test=fold(ev,c,4,7);annuals+=test.n;ok2=evalpass(test);
     if(ok2){eval_pass++;partial=fold(ev,c,7,8);annuals+=partial.n;}}
    out<<base<<','<<STOP[sl]<<','<<TP[tp]<<','<<HOLD[hold]<<','<<tr<<','<<se<<','<<mask<<','<<dir<<','<<SR[sr]<<','<<GR[gr]<<','<<DM[d]<<','<<LC[l]<<','<<WC[w]<<','<<f.g125<<','<<f.g250<<','<<f.g1000<<','<<f.worst<<','<<f.dd<<','<<f.logsum<<','<<f.trades<<','<<f.wins<<','<<f.gaps<<','<<f.trace<<','<<ok<<',';
    if(ok)out<<test.g125<<','<<test.g250<<','<<test.g1000<<','<<test.worst<<','<<test.dd<<','<<test.logsum<<','<<ok2<<',';
    else out<<",,,,,,,";
    if(ok2)out<<partial.g125<<','<<partial.g250<<','<<partial.g1000<<','<<partial.worst<<','<<partial.dd;else out<<",,,,";
    out<<'\n';
   }
  }
  out.flush();if(!out)throw runtime_error("write results");
 }
 ofstream meta(root/"results"/(stem+".json"));
 meta<<"{\"base\":"<<base<<",\"nominal_space_shard\":"<<4ULL*5*6*GROUPS*LEAVES<<",\"signal_groups_evaluated\":"<<groups<<",\"signal_groups_passed\":"<<group_pass<<",\"wallet_configs_evaluated\":"<<wallets<<",\"annual_cost_trials\":"<<annuals<<",\"dev_passed\":"<<dev_pass<<",\"distinct_dev_entry_traces\":"<<traces.size()<<",\"eval_passed\":"<<eval_pass<<",\"native_replays\":0,\"complete\":true}\n";
 cout<<"COMPLETE base="<<base<<" groups="<<groups<<" wallet_configs="<<wallets<<" eval_passed="<<eval_pass<<" annual_cost_trials="<<annuals<<endl;
}
