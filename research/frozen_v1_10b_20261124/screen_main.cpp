#include "screen_prefix.cpp"
struct Y { double cash=100,dd=0; int trades=0,eur=0,btc=0,gaps=0; int64_t goal=0; };
Y run(const vector<Event>&e,int year,double risk,int mask,int trend,int se,int direction){
 Y r;double peak=100;int64_t next=CUTS[year];int day=-1,used=0;
 for(const auto&t:e){
  if(t.t<CUTS[year]||t.t<next)continue;if(t.t>=CUTS[year+1])break;
  if(!(mask&(1<<t.symbol))||!(t.trend&(1<<trend))||!session(t,se)||(direction==1&&t.side<0))continue;
  int d=t.t/1440;if(d!=day){day=d;used=0;}if(used>=2)continue;
  double q=floor(min({r.cash*risk/(t.risk+risk*t.cost),r.cash*.5/(t.margin+.5*t.cost),MAXSTEPS[t.symbol]})+1e-12);
  if(q<1)continue;
  peak=max(peak,r.cash+q*t.mfe);r.dd=max(r.dd,(peak-(r.cash+q*t.mae))/peak);
  r.cash+=q*t.pnl;peak=max(peak,r.cash);r.dd=max(r.dd,(peak-r.cash)/peak);
  r.trades++;r.eur+=t.symbol==0;r.btc+=t.symbol==2;r.gaps+=t.gap>0;used++;
  next=t.exit+(t.pnl<0?60:5);
  if(r.cash>=1000){r.goal=t.exit;break;}if(r.dd>=.6||r.cash<=0)break;
 }
 return r;
}
int main(int argc,char**argv){
 if(argc>1&&string(argv[1])=="--selftest"){
  Event x{CUTS[0]+10,CUTS[0]+11,0,7,1,200,5,0,20,20,-200,0};
  auto a=run({x},0,.08,1,2,0,1);if(a.trades!=0)throw runtime_error("unaffordable minimum lot must skip");
  x.risk=1;x.pnl=100;x.mae=-1;x.mfe=100;auto b=run({x},0,.08,4,2,0,1);if(b.trades!=0)throw runtime_error("asset filter");
  auto c=run({x},0,.08,1,2,0,1);if(c.trades!=1||c.cash<=100)throw runtime_error("single admitted trade");
  cout<<"PASS screening minlot, asset filter, chronology fixture; real_orders=0\n";return 0;
 }
 if(argc!=2)return 2;fs::path root=argv[1];
 for(int sid:{0,2}){assets[sid].t=readbin<int64_t>(root/"data"/(to_string(sid)+"_times.i64"));assets[sid].b=readbin<Bar>(root/"data"/(to_string(sid)+"_m1.f64"));if(assets[sid].t.size()!=assets[sid].b.size())throw runtime_error("input rows");}
 vector<int>bs={1,3,5,7,13,15,17,19,25,27,33,35};
 ofstream out(root/"results/screen.csv");out.precision(17);out<<"base,sl,tp,hold,trend,session,risk,mask,direction,cost,year,balance,dd_upper,trades,eur,btc,gap_trades,goal_minute,days_to_1000\n";
 int rows=0;auto started=chrono::steady_clock::now();
 for(int base:bs){
  vector<Candidate>cand;for(int sid:{0,2}){auto a=readbin<Candidate>(root/"data"/("base"+to_string(base)+"_symbol"+to_string(sid)+".bin"));cand.insert(cand.end(),a.begin(),a.end());}
  sort(cand.begin(),cand.end(),[](const auto&a,const auto&b){return a.t<b.t||(a.t==b.t&&a.symbol<b.symbol);});
  for(int sl:{1,2})for(int tp:{2,3})for(int hold:{3,4})for(int cost:{1,2}){
   vector<Event>events;for(const auto&c:cand){auto e=outcome(c,sl,tp,hold,cost);if(e.risk>0)events.push_back(e);}
   for(int trend:{1,2})for(int se:{0,2})for(double risk:{.05,.08})for(int mask:{1,4,5})for(int direction:{0,1})for(int year=0;year<8;year++){
    auto r=run(events,year,risk,mask,trend,se,direction);double days=r.goal?(r.goal-CUTS[year])/1440.:-1;
    out<<base<<','<<sl<<','<<tp<<','<<hold<<','<<trend<<','<<se<<','<<risk<<','<<mask<<','<<direction<<','<<cost<<','<<2019+year<<','<<r.cash<<','<<r.dd<<','<<r.trades<<','<<r.eur<<','<<r.btc<<','<<r.gaps<<','<<r.goal<<','<<days<<'\n';rows++;
   }
  }
  out.flush();cout<<"BASE "<<base<<" rows="<<rows<<" seconds="<<chrono::duration<double>(chrono::steady_clock::now()-started).count()<<endl;
 }
 cout<<"DONE rows="<<rows<<" unique_configurations="<<rows/16<<" actual_annual_screens="<<rows<<endl;
}
