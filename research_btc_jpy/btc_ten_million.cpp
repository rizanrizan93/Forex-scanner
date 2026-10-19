#define main original_main
#include "engine.hpp"
#undef main
#include <numeric>
#include <unordered_map>
bool custom=false;vector<S> active;
const vector<S>& signals(const P&p){return custom?active:rawSignals(p);}
struct F{int id,vol,rsi,week,loc,daily;P p;};
vector<P> primitives(){
 vector<P> v;for(int tf=1;tf<4;tf++)for(int f=0;f<12;f++)for(int look=0;look<4;look++){
  if((f==3||f==5||f==6||f==8||f==9||f==11)&&look)continue;
  for(int th=0;th<3;th++)for(int tr=0;tr<3;tr++)for(int se=0;se<(tf==3?1:4);se++)for(int si=0;si<3;si++){
   P p{};p.tf=tf;p.family=f;p.look=look;p.threshold=th;p.trend=tr;p.session=se;p.side=si;v.push_back(p);
  }
 }return v;
}
F recipe(int id){
 static vector<P> base=primitives();uint64_t n=base.size()*900ULL,a=104729;while(gcd(a,n)!=1)a+=2;
 uint64_t x=((id-1)*a+20261019ULL)%n;F f{};f.id=id;f.p=base[x%base.size()];x/=base.size();
 f.vol=x%5;x/=5;f.rsi=x%5;x/=5;f.week=x%4;x/=4;f.loc=x%3;x/=3;f.daily=x%3;
 return f;
}
struct A{S s;double ratio,rsi,location;int weekday,daily;};
map<int,vector<A>> annotations;
vector<B> dailyBars;
const vector<A>& annotated(const P&p){
 int k=key(p);auto it=annotations.find(k);if(it!=annotations.end())return it->second;
 vector<A> v;size_t d=0;const auto& b=agg[p.tf];
 for(auto&s:rawSignals(p)){
  const auto& a=b[s.bar-1];int64_t t=minutes[s.mi].t;
  while(d+1<dailyBars.size()&&dailyBars[d+1].t+1440<=t)d++;
  int tr=0;if(dailyBars[d].t+1440<=t){auto&z=dailyBars[d];tr=z.c>z.e80&&z.e20>z.e80?1:z.c<z.e80&&z.e20<z.e80?-1:0;}
  double ratio=a.atr/max(b[max(0,s.bar-21)].atr,1e-12);
  v.push_back({s,ratio,a.rsi,(a.c-a.l)/max(a.h-a.l,1e-12),int((t/1440+4)%7),tr});
 }
 return annotations.emplace(k,move(v)).first->second;
}
void activate(const F&f){
 custom=false;const auto& v=annotated(f.p);active.clear();
 for(auto&a:v){
  if(!accept(f.p,a.s,minutes[a.s.mi].t))continue;
  bool vol=f.vol==0||(f.vol==1&&a.ratio<.75)||(f.vol==2&&a.ratio>=.75&&a.ratio<=1.25)||(f.vol==3&&a.ratio>1.25)||(f.vol==4&&a.ratio>=1);
  bool rsi=f.rsi==0||(f.rsi==1&&(a.s.side>0?a.rsi>=55:a.rsi<=45))||(f.rsi==2&&(a.s.side>0?a.rsi<=45:a.rsi>=55))||(f.rsi==3&&a.rsi>=45&&a.rsi<=55)||(f.rsi==4&&a.rsi>=20&&a.rsi<=80);
  bool week=f.week==0||(f.week==1&&a.weekday>=1&&a.weekday<=5)||(f.week==2&&(a.weekday==0||a.weekday==6))||(f.week==3&&a.weekday>=2&&a.weekday<=4);
  bool loc=f.loc==0||(f.loc==1&&(a.s.side>0?a.location>=.65:a.location<=.35))||(f.loc==2&&(a.s.side>0?a.location<=.35:a.location>=.65));
  bool dt=f.daily==0||(f.daily==1&&a.daily==a.s.side)||(f.daily==2&&a.daily==-a.s.side);
  if(vol&&rsi&&week&&loc&&dt)active.push_back(a.s);
 }
 custom=true;
}
uint64_t mix(uint64_t x){x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
P config(const F&f,int j){
 const int n=6*8*4*10*6*3*3;uint64_t a=mix(f.id)|1;while(gcd(a,uint64_t(n))!=1)a+=2;
 uint64_t z=(mix(f.id+99991)+uint64_t(j)*a)%n;P p=f.p;p.id=(f.id-1)*10+j+1;
 p.stop=z%6;z/=6;p.tp=z%8;z/=8;p.hold=z%4;z/=4;p.risk=z%10;z/=10;p.margin=z%6;z/=6;p.layers=z%3;z/=3;p.be=z%3;return p;
}
string fh="recipe_id,vol_gate,rsi_gate,weekday_gate,close_location_gate,daily_trend_gate";
void fields(ostream&o,const F&f){o<<f.id<<","<<f.vol<<","<<f.rsi<<","<<f.week<<","<<f.loc<<","<<f.daily;}
struct Q{F f;P p;R r;};
void keep(vector<Q>&v,Q q,int n){v.push_back(q);sort(v.begin(),v.end(),[](auto&a,auto&b){return a.r.eq>b.r.eq;});if(int(v.size())>n)v.pop_back();}
vector<string> split(const string&s){stringstream ss(s);vector<string>v;string z;while(getline(ss,z,','))v.push_back(z);return v;}
void setup(const string&file){
 btc=true;symbol="BTCUSD";load(file);for(int i=0;i<4;i++)agg[i]=aggregate(widths[i]);h4=agg[2];dailyBars=agg[3];
}
void sanity(){
 P p{692365,2,8,0,2,1,1,1,4,6,3,9,5,2,2};custom=false;auto r=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
 if(abs(r.eq-1005025.5238208736)>1e-5||abs(r.dd-67.92092400829017)>1e-8||r.trades!=63)throw runtime_error("ORIGINAL_692365_PARITY_FAILED");
 cout<<"ORIGINAL_BASELINE_PARITY_PASS "<<setprecision(17)<<r.eq<<" "<<r.dd<<endl;
 // Disabled extra gates must leave exact accepted signal timestamps and results unchanged.
 F f{};f.p=p;activate(f);auto c=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
 if(c.eq!=r.eq||c.dd!=r.dd||c.trades!=r.trades)throw runtime_error("ZERO_GATE_PARITY_FAILED");
 custom=false;cout<<"ZERO_GATE_PARITY_PASS"<<endl;
}
int main(int argc,char**argv){try{
 if(argc==2&&string(argv[1])=="--test"){engineFixtures();return 0;}
 if(argc<4)return 2;string mode=argv[1];outdir=argv[3];setup(argv[2]);sanity();int64_t start=parse("2019-01-01 00:00:00");
 if(mode=="search"){
  int shard=stoi(argv[4]);ofstream out(outdir+"/ALL_CONFIGURATIONS.csv");out<<setprecision(17)<<fh<<","<<ph<<","<<rh<<"\n";
  vector<Q>top,dd60,dd55,dd50,dd45;int count=0,recipes=0,zero=0,qualified=0;
  for(int i=1;i<=1000000;i++){if((i-1)%10!=shard)continue;auto f=recipe(i);activate(f);recipes++;if(active.empty())zero++;
   for(int j=0;j<10;j++){
    P p=config(f,j);R r=simulate(p,true,start,endtime);fields(out,f);out<<",";params(out,p);out<<",";result(out,r);out<<"\n";count++;
    if(r.trades>=30){
     Q q{f,p,r};keep(top,q,5);if(r.dd<60){keep(dd60,q,20);qualified++;}if(r.dd<55)keep(dd55,q,5);if(r.dd<50)keep(dd50,q,5);if(r.dd<45)keep(dd45,q,3);
    }
   }
   if(recipes%2000==0)cout<<"SEARCH shard="<<shard<<" recipes="<<recipes<<" cases="<<count<<" dd60_best="<<(dd60.empty()?0:dd60[0].r.eq)<<endl;
  }
  map<int,Q> chosen;for(auto&v:vector<vector<Q>>{top,dd60,dd55,dd50,dd45})for(auto&q:v)chosen[q.p.id]=q;
  ofstream s(outdir+"/SELECTED.csv");s<<setprecision(17)<<fh<<","<<ph<<","<<rh<<"\n";for(auto&[id,q]:chosen){fields(s,q.f);s<<",";params(s,q.p);s<<",";result(s,q.r);s<<"\n";}
  ofstream info(outdir+"/SUMMARY.json");info<<"{\"shard\":"<<shard<<",\"recipes\":"<<recipes<<",\"configurations\":"<<count<<",\"recipes_without_accepted_signals\":"<<zero<<",\"eligible_DD60\":"<<qualified<<",\"minimum_baskets\":30,\"grammar_primitives\":"<<primitives().size()<<",\"grammar_space\":"<<primitives().size()*900<<",\"fundamental_families\":12}\n";
  if(recipes!=100000||count!=1000000)throw runtime_error("COUNT_MISMATCH");cout<<"COMPLETE recipes="<<recipes<<" configs="<<count<<endl;
 }else if(mode=="audit"){
  ifstream f(argv[4]);string line;getline(f,line);auto h=split(line);map<string,int>cols;for(int k=0;k<int(h.size());k++)cols[h[k]]=k;
  ofstream s(outdir+"/ALL_SELECTED_STRESS.csv");s<<setprecision(17)<<"case,"<<fh<<","<<ph<<","<<rh<<"\n";
  while(getline(f,line)){
   auto row=split(line);auto val=[&](string k){return stod(row.at(cols.at(k)));};int id=val("id"),rid=val("recipe_id");F recipeDef=recipe(rid);P p=config(recipeDef,(id-1)%10);if(p.id!=id)throw runtime_error("ID_REGEN_FAILED");
   activate(recipeDef);
   vector<tuple<string,Model,int64_t,int64_t>>cs={{"BASE",{},start,endtime},{"COST1_5",{1.5},start,endtime},{"COST2",{2},start,endtime},{"DELAY_NEXT_M1",{1.,0,1},start,endtime},{"LEVERAGE2",{1.,2},start,endtime},{"LEVERAGE5",{1.,5},start,endtime},{"NO_ADDS",{1.,0,0,1},start,endtime},{"SEGMENT_2019_2022",{},start,parse("2023-01-01 00:00:00")},{"SEGMENT_2023_2024",{},parse("2023-01-01 00:00:00"),parse("2025-01-01 00:00:00")},{"SEGMENT_2025_OCT2026",{},parse("2025-01-01 00:00:00"),endtime}};
   for(auto&[name,model,a,z]:cs){auto r=simulate(p,true,a,z,model,outdir+"/candidate_"+to_string(id)+"_"+name);
    if(name=="BASE"&&(abs(r.eq-val("equity"))>max(1e-6,abs(r.eq)*1e-9)||abs(r.dd-val("floating_dd"))>1e-8||r.trades!=int(val("trades"))))throw runtime_error("RAW_SELECTED_PARITY_FAILED");
    s<<name<<",";fields(s,recipeDef);s<<",";params(s,p);s<<",";result(s,r);s<<"\n";
   }
   cout<<"AUDITED "<<id<<endl;
  }
 }else throw runtime_error("BAD_MODE");
}catch(exception&e){cerr<<e.what()<<endl;return 1;}}
