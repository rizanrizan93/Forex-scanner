// Archived-basket fixed-fill sensitivity. NOT a native market replay.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <string>
using namespace std;
struct Basket{double pnl,ref;int32_t sym,seed;};struct Event{double time;int32_t kind,i;};
struct Model{int type,look,reduce,stage;};
struct Policy{Model m;int e,x,b,global;};
struct Result{double end,dd;int admitted;};
vector<Basket> baskets;vector<Event> events;
constexpr double RED[]={.25,.5,.75,.9},GLOBAL[]={.5,.6,.7,.8,.9,1.};
constexpr int LOOK[]={4,8,16,32};
array<vector<uint8_t>,16> adverse;
void init(){
 for(int type=0;type<4;type++)for(int k=0;k<4;k++){
  auto&flag=adverse[type*4+k];flag.resize(baskets.size());array<vector<double>,3>hist;
  for(auto&e:events){auto&t=baskets[e.i];auto&h=hist[t.sym];
   if(e.kind==1){h.push_back(t.pnl/t.ref);continue;}
   if(h.size()<(size_t)LOOK[k])continue;
   int n=LOOK[k],wins=0,streak=0;double sum=0,cash=1,peak=1,dd=0;
   for(auto it=h.end()-n;it!=h.end();it++){double r=*it;wins+=r>0;streak=r<0?streak+1:0;sum+=r;cash*=1+r;peak=max(peak,cash);dd=max(dd,1-cash/peak);}
   flag[e.i]=type==0?streak>=max(2,n/4):type==1?dd>.15:type==2?wins*2<n:sum<0;
  }
 }
}
Result simulate(const Policy&p,bool control=false){
 double cash=100,peak=100,dd=0;int n=0;double size[1100]={};
 double weights[]={p.e*.1*GLOBAL[p.global],p.x*.1*GLOBAL[p.global],p.b*.1*GLOBAL[p.global]};
 const auto&flag=adverse[p.m.type*4+p.m.look];
 for(auto&e:events){const auto&t=baskets[e.i];
  if(e.kind==0){
   double w=(control||t.seed)?1:weights[t.sym];
   if(!control&&!t.seed&&flag[e.i]){
    bool applies=p.m.stage==0||(p.m.stage==1&&cash<1000)||(p.m.stage==2&&cash>=1000&&cash<100000)||(p.m.stage==3&&cash>=100000);
    if(applies)w*=RED[p.m.reduce];
   }
   size[e.i]=cash/t.ref*w;n+=w>0;
  }else{cash+=size[e.i]*t.pnl;if(!isfinite(cash)||cash<=0)return{cash,1,n};peak=max(peak,cash);dd=max(dd,1-cash/peak);}
 }
 return {cash,dd,n};
}
struct Ranked{Policy p;Result r;};
void row(ostream&o,const Ranked&a){auto&p=a.p;auto&r=a.r;o<<p.m.type<<','<<LOOK[p.m.look]<<','<<RED[p.m.reduce]<<','<<p.m.stage<<','<<p.e*.1<<','<<p.x*.1<<','<<p.b*.1<<','<<GLOBAL[p.global]<<','<<r.end<<','<<r.dd<<','<<r.admitted<<'\n';}
int main(int argc,char**argv){
 if(argc!=4)return 2;ifstream in(argv[1],ios::binary);int32_t n,m;in.read((char*)&n,4);in.read((char*)&m,4);if(n!=1047||m!=2094||sizeof(Basket)!=24||sizeof(Event)!=16)throw runtime_error("layout");
 baskets.resize(n);events.resize(m);in.read((char*)baskets.data(),n*sizeof(Basket));in.read((char*)events.data(),m*sizeof(Event));if(!in)throw runtime_error("read");init();
 auto control=simulate({{0,0,0,0},10,10,10,5},true);
 if(abs(control.end-1662133293.0811067)>.05)throw runtime_error("archive cash parity");
 int shard=stoi(argv[2]);if(shard<0||shard>=16)return 2;
 vector<Ranked> top;uint64_t count=0,better=0,tenb=0,eligible=0;
 for(int model=shard*16;model<(shard+1)*16;model++){
  Model m{model/64,(model/16)%4,(model/4)%4,model%4};
  for(int e=0;e<=10;e++)for(int x=0;x<=10;x++)for(int b=0;b<=10;b++)for(int g=0;g<6;g++){
   Policy p{m,e,x,b,g};auto r=simulate(p);count++;
   if(r.dd>=.60||!isfinite(r.end))continue;
   eligible++;better+=r.end>control.end;tenb+=r.end>=1e10;
   if(top.size()<30||r.end>top.back().r.end){
    top.push_back({p,r});sort(top.begin(),top.end(),[](auto&a,auto&b){return a.r.end>b.r.end;});if(top.size()>30)top.pop_back();
   }
  }
 }
 if(count!=127776)throw runtime_error("count");
 ofstream f(string(argv[3])+"/top.csv");f<<setprecision(17)<<"type,look,reduce,stage,eur,xau,btc,global,end,closed_dd,admitted\n";for(auto&r:top)row(f,r);
 ofstream j(string(argv[3])+"/summary.json");j<<setprecision(17)<<"{\"shard\":"<<shard<<",\"evaluated\":"<<count<<",\"eligible_closed_dd\":"<<eligible<<",\"higher_than_archived_balance\":"<<better<<",\"at_least_10b_closed_dd\":"<<tenb<<",\"control_end\":"<<control.end<<",\"control_closed_basket_dd\":"<<control.dd<<",\"new_native_replays\":0}\n";
 cout<<"FIXED_PATH_SHARD "<<shard<<" evaluated "<<count<<" closed_dd_eligible "<<eligible<<" above_archive "<<better<<" at_least_10b "<<tenb<<endl;
}