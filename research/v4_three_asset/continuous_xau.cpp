#include "continuous_prefix.cpp"
#include <iomanip>
struct Wallet{double cash=100,dd=0;int entries=0,wins=0,gaps=0;int64_t goal125=0,goal250=0,goal1000=0;};
Wallet runwallet(const vector<Event>&v,int64_t start,double seedrisk){
 Wallet a;double peak=100;int day=-1,used=0;int64_t next=start;bool growth=false;
 for(auto&e:v){
  if(e.t<next||e.t<start||e.exit>CONT_END||e.risk<=0)continue;
  int d=e.t/1440;if(d!=day){day=d;used=0;}if(used>=2)continue;
  double risk=growth?.05:seedrisk;
  double units=floor(min({a.cash*risk/(e.risk+risk*e.cost),a.cash*.5/(e.margin+.5*e.cost),MAXSTEPS[e.symbol]})+1e-12);
  if(!isfinite(units)||units<1)continue;
  peak=max(peak,a.cash+units*e.mfe);a.dd=max(a.dd,(peak-a.cash-units*e.mae)/peak);
  a.cash+=units*e.pnl;peak=max(peak,a.cash);a.dd=max(a.dd,(peak-a.cash)/peak);
  a.entries++;a.wins+=e.pnl>0;a.gaps+=e.gap>0;used++;
  if(a.cash>=125&&!a.goal125){a.goal125=e.exit;growth=true;}
  if(a.cash>=250&&!a.goal250)a.goal250=e.exit;
  if(a.cash>=1000&&!a.goal1000)a.goal1000=e.exit;
  next=e.exit+(e.pnl<0?60:5);if(a.dd>=.60||a.cash<=0)break;
 }
 return a;
}
int main(int argc,char**argv){
 if(argc==2&&string(argv[1])=="--selftest"){
  CONT_END=30000000;Event e{23000000,23000001,1,7,1,1,5,0,10,10,-1,0};
  Event q=e;q.t+=600000;q.exit=q.t+1;
  auto a=runwallet({e,q},22089600,.08);
  if(a.entries!=2||a.cash<=180||a.goal125==0)throw runtime_error("wallet not carried across years");
  if(runwallet({e,q},25771680,.08).entries!=0)throw runtime_error("start gate");
  cout<<"PASS no-reset synthetic fixture only\n";return 0;
 }
 if(argc!=2)return 2;fs::path root=argv[1];
 assets[1].t=readbin<int64_t>(root/"data/1_times.i64");
 assets[1].b=readbin<Bar>(root/"data/1_m1.f64");
 if(assets[1].t.empty()||assets[1].t.size()!=assets[1].b.size())throw runtime_error("price stream mismatch");
 CONT_END=assets[1].t.back()+1;
 ofstream f(root/"continuous_results.csv");f<<setprecision(12);
 f<<"start,base,sl,tp,hold,trend,dir,seedrisk,cost,end,dd,entries,wins,gaps,goal125,goal250,goal1000\n";
 uint64_t n=0;
 for(int b=0;b<36;b++){
  auto cs=readbin<Candidate>(root/"data"/("base"+to_string(b)+"_symbol1.bin"));
  for(int sl:{1,2})for(int tp:{1,2,3})for(int hold:{2,3})for(int cost:{1,2}){
   vector<Event> events;
   for(auto &c:cs){if(c.symbol!=1||c.idx<0||size_t(c.idx)>=assets[1].t.size()||assets[1].t[c.idx]!=c.t)throw runtime_error("bad tape");auto e=outcome(c,sl,tp,hold,cost);if(e.risk>0)events.push_back(e);}
   for(int trend:{1,2})for(int dir=0;dir<3;dir++){
    vector<Event> ev;for(auto&e:events)if((e.trend&(1<<trend))&&(dir==0||(dir==1&&e.side>0)||(dir==2&&e.side<0)))ev.push_back(e);
    for(double risk:{.05,.08})for(int year:{2012,2019}){
     auto a=runwallet(ev,year==2012?22089600:25771680,risk);
     f<<year<<','<<b<<','<<STOP[sl]<<','<<TP[tp]<<','<<HOLD[hold]<<','<<trend<<','<<dir<<','<<risk<<','<<cost<<','<<a.cash<<','<<a.dd<<','<<a.entries<<','<<a.wins<<','<<a.gaps<<','<<a.goal125<<','<<a.goal250<<','<<a.goal1000<<'\n';n++;
    }
   }
  }
  f.flush();cout<<"BASE "<<b<<" completed="<<n<<endl;
 }
 if(!f||n!=20736)throw runtime_error("incomplete replay");
 cout<<"CONTINUOUS_PUBLIC_XAU_COMPLETE cases="<<n<<" cutoff_minute="<<CONT_END<<" native_replays=0\n";
}
