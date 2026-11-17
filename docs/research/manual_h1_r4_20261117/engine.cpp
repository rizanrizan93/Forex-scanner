#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <unordered_set>
#include <vector>
#include <omp.h>
using namespace std;
#pragma pack(push,1)
struct Bar{double o,h,l,c;int64_t t;int32_t day,year;int16_t minute,dow;};
struct Event{int32_t entry,touch,style,s;double atr,level;int32_t trend;};
#pragma pack(pop)
static_assert(sizeof(Bar)==52);static_assert(sizeof(Event)==36);
struct Config{int style,g,f;double score=0;uint64_t signature=0;};
struct Outcome{bool valid=false;int entry_i=0,exit_i=0,reason=0,missing=0;int64_t exit_t=0;double entry=0,stop=0,tp=0,unit=0,r=0,minr=0,maxr=0;};
struct Stats{int n=0,wins=0;double sum=0,sq=0,pos=0,neg=0,eq=100,peak=100,dd=0,closed_dd=0,closed_peak=100;uint64_t signature=0;};
const double STOPS[]={.75,1,1.5},TARGETS[]={2,3,4};
#ifdef EXTENDED_HOLD
const int HOLDS[]={480,1440,2880};
#else
const int HOLDS[]={240,480,720};
#endif
vector<Bar>b;vector<Event>e;vector<unsigned char>news;vector<double>hclose;array<vector<int>,14>styles;
template<class T>vector<T> readbin(string p){ifstream f(p,ios::binary|ios::ate);if(!f)throw runtime_error("Missing "+p);auto n=f.tellg();if(n%sizeof(T))throw runtime_error("Bad size "+p);vector<T>v(size_t(n)/sizeof(T));f.seekg(0);f.read((char*)v.data(),n);return v;}
uint64_t mix(uint64_t x){x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
double pf(const Stats&s){return s.neg>0?s.pos/s.neg:0;}
double score(const Stats&s){if(s.n<2)return -1e9;double mean=s.sum/s.n,var=max(0.,(s.sq-s.sum*s.sum/s.n)/(s.n-1));return mean-1.96*sqrt(var/s.n);}
void add(Stats&s,const Outcome&o,const Event&ev){s.n++;s.sum+=o.r;s.sq+=o.r*o.r;s.pos+=max(0.,o.r);s.neg+=max(0.,-o.r);s.wins+=o.r>0;double budget=s.eq*.005;s.peak=max(s.peak,s.eq+budget*o.maxr);s.dd=max(s.dd,100*(s.peak-s.eq-budget*o.minr)/s.peak);s.eq+=budget*o.r;s.peak=max(s.peak,s.eq);s.closed_peak=max(s.closed_peak,s.eq);s.closed_dd=max(s.closed_dd,100*(s.closed_peak-s.eq)/s.closed_peak);s.signature^=mix(uint64_t(ev.entry)*1315423911ULL+o.exit_i)^mix(uint64_t(llround(o.r*1e8)));}
bool match(const Event&ev,int f,double cost,int delay){int r=f/4,ses=(f/2)%2,cap=f%2;int i=ev.entry+delay;if(i>=int(b.size())||b[i].t!=b[ev.entry].t+delay||b[i].day!=b[ev.entry].day||b[i].minute>=1435||b[i].minute<(ses?840:420)||b[i].dow>=5||!news[i]||!(ev.trend&(1<<r)))return false;double price=b[i].o+(ev.s==1?.30*cost:0)+ev.s*.05*cost;return abs(price-ev.level)<=ev.atr*(cap?1:.5);}
Outcome replay(const Event&ev,int g,double cost=1,int delay=0){
 Outcome o;int i=ev.entry+delay;if(i>=int(b.size())||b[i].t!=b[ev.entry].t+delay)return o;
 int si=g/18,ti=(g/6)%3,hi=(g/2)%3,trail=g%2;double spread=.30*cost,slip=.05*cost,fee=.07*cost;
 o.entry_i=i;o.entry=b[i].o+(ev.s==1?spread:0)+ev.s*slip;double risk=max(STOPS[si]*ev.atr,2*spread);
 o.stop=o.entry-ev.s*risk;o.tp=o.entry+ev.s*TARGETS[ti]*ev.atr;o.unit=risk+fee+slip;double stop=o.stop;bool armed=false;int64_t armedat=-1;
 int64_t cutoff=min(b[i].t+HOLDS[hi],b[i].t+(1435-b[i].minute));
#ifdef EXTENDED_HOLD
 int64_t utcday=b[i].t/1440;int weekday=int((utcday+3)%7);int64_t friday=(utcday+(4-weekday+7)%7)*1440+1255;
 cutoff=min(b[i].t+HOLDS[hi],friday);
 if(cutoff<=b[i].t)return o;
#endif
 for(int k=i;k<int(b.size());k++){
  auto z=b[k];double op=z.o+(ev.s==-1?spread:0),lo=z.l+(ev.s==-1?spread:0),hh=z.h+(ev.s==-1?spread:0),exit=0;int reason=0;
  if(k>i&&z.t>b[k-1].t+1)o.missing+=int(z.t-b[k-1].t-1);
  if(z.t>=cutoff){exit=op-ev.s*slip;reason=3;}
#ifdef GAP_STRESS
  else if(k>i&&z.t-b[k-1].t>6){exit=(ev.s==1?min(op,stop):max(op,stop))-ev.s*slip;reason=5;}
#endif
  else{
   if(trail&&armed&&z.t>armedat&&z.t%60==0&&isfinite(hclose[k])){double candidate=hclose[k]-ev.s*1.5*ev.atr;stop=ev.s==1?max(stop,candidate):min(stop,candidate);}
   bool sl=ev.s==1?lo<=stop:hh>=stop,tp=ev.s==1?hh>=o.tp:lo<=o.tp;
   if(sl){exit=(ev.s==1?min(op,stop):max(op,stop))-ev.s*slip;reason=abs(stop-o.stop)>1e-9?4:1;}
   else if(tp){exit=o.tp-ev.s*slip;reason=2;}
   double carry_mark=0;
#ifdef EXTENDED_HOLD
   carry_mark=max(0,int((z.t-1260)/1440-(b[i].t-1260)/1440))*(cost>=2?1.:cost>1?.5:.2);
#endif
   double adverse=ev.s==1?max(lo,min(op,stop)):min(hh,max(op,stop));
   double favorable=ev.s==1?min(hh,o.tp):max(lo,o.tp);
   o.minr=min(o.minr,(ev.s*(adverse-o.entry)-fee-slip-carry_mark)/o.unit);o.maxr=max(o.maxr,(ev.s*(favorable-o.entry)-fee-slip-carry_mark)/o.unit);
   if(!armed&&ev.s*(favorable-o.entry)>=ev.atr){armed=true;armedat=z.t;}
  }
  if(reason){o.valid=true;o.exit_i=k;o.exit_t=z.t+(reason==3?0:1);o.reason=reason;double carry=0;
#ifdef EXTENDED_HOLD
   int nights=int((z.t-1260)/1440-(b[i].t-1260)/1440);carry=max(0,nights)*(cost>=2?1.:cost>1?.5:.2);
#endif
   o.r=(ev.s*(exit-o.entry)-fee-carry)/o.unit;o.minr=min(o.minr,o.r);o.maxr=max(o.maxr,o.r);return o;}
 }return o;
}
Stats portfolio(const Config&c,int ymin,int ymax,double cost=1,int delay=0,ofstream*ledger=nullptr){Stats st;int64_t busy=-1;int day=-1,daily=0;for(int id:styles[c.style]){auto&ev=e[id];if(b[ev.entry].year<ymin||b[ev.entry].year>ymax||!match(ev,c.f,cost,delay))continue;int i=ev.entry+delay;if(day!=b[i].day){day=b[i].day;daily=0;}if(daily>=2||b[i].t<busy)continue;auto o=replay(ev,c.g,cost,delay);if(!o.valid)continue;daily++;busy=o.exit_t;add(st,o,ev);if(ledger)*ledger<<c.style<<','<<c.g<<','<<c.f<<','<<cost<<','<<delay<<','<<id<<','<<o.entry_i<<','<<o.exit_i<<','<<o.exit_t<<','<<ev.s<<','<<o.entry<<','<<o.stop<<','<<o.tp<<','<<o.unit<<','<<o.r<<','<<o.minr<<','<<o.maxr<<','<<o.reason<<','<<o.missing<<'\n';}return st;}
void row(ostream&o,const Config&c,string block,double cost,int delay,const Stats&s){o<<c.style<<','<<c.g<<','<<c.f<<','<<block<<','<<cost<<','<<delay<<','<<s.n<<','<<pf(s)<<','<<(s.n?s.sum/s.n:0)<<','<<s.sum<<','<<s.eq<<','<<s.dd<<','<<s.closed_dd<<','<<score(s)<<','<<s.wins<<','<<s.signature<<'\n';}
void header(ostream&o){o<<"style,g,f,block,cost,delay,n,pf,mean_r,sum_r,balance_100,dd_bound_pct,closed_dd_pct,score,wins,signature\n"<<setprecision(17);}
vector<Config>configs(string path){ifstream f(path);string line;getline(f,line);vector<Config>v;while(getline(f,line)){replace(line.begin(),line.end(),',',' ');istringstream s(line);Config c;if(s>>c.style>>c.g>>c.f)v.push_back(c);}return v;}
void screen(){vector<vector<Config>>tops(14);vector<vector<string>>rows(14);
 #pragma omp parallel for schedule(dynamic)
 for(int style=0;style<14;style++){unordered_set<uint64_t>seen;vector<Config>all;
  for(int g=0;g<54;g++)for(int f=0;f<12;f++){Config c{style,g,f};auto st=portfolio(c,2019,2022);ostringstream ss;ss<<setprecision(17);row(ss,c,"train_2019_22",1,0,st);rows[style].push_back(ss.str());if(st.n<150||pf(st)<1.10||st.sum<=0)continue;c.score=score(st);c.signature=st.signature;all.push_back(c);}
  sort(all.begin(),all.end(),[](auto&a,auto&b){if(a.score!=b.score)return a.score>b.score;return tie(a.style,a.g,a.f)<tie(b.style,b.g,b.f);});
  for(auto c:all){if(seen.count(c.signature))continue;seen.insert(c.signature);tops[style].push_back(c);if(tops[style].size()==3)break;}
  #pragma omp critical
  cerr<<"SCREEN style="<<style<<" shortlist="<<tops[style].size()<<'\n';
 }
 ofstream out("results/screen.csv");header(out);for(auto&v:rows)for(auto&s:v)out<<s;ofstream sh("results/shortlist.csv");sh<<"style,g,f,screen_score,signature\n"<<setprecision(17);for(auto&v:tops)for(auto&c:v)sh<<c.style<<','<<c.g<<','<<c.f<<','<<c.score<<','<<c.signature<<'\n';
}
void evaluate(string file,bool final){auto cs=configs(file);ofstream out(final?"results/final.csv":"results/validation.csv");header(out);ofstream ledger(final?"results/final_ledger.csv":"results/validation_ledger.csv");ledger<<"style,g,f,cost,delay,event_i,entry_i,exit_i,exit_t,direction,entry,stop,tp,risk_unit,net_r,min_r,max_r,reason,missing\n"<<setprecision(17);for(auto c:cs){vector<pair<double,int>>scenarios=final?vector<pair<double,int>>{{1,0},{1,1},{1,5},{1.5,0},{1.5,1},{1.5,5},{2,0},{2,1},{2,5}}:vector<pair<double,int>>{{1,0},{1.5,1}};for(auto [cost,delay]:scenarios){int maxy=final?2025:2024;auto total=portfolio(c,final?2025:2019,maxy,cost,delay,&ledger);row(out,c,final?"2025":"all_2019_24",cost,delay,total);if(!final){row(out,c,"train_2019_22",cost,delay,portfolio(c,2019,2022,cost,delay));row(out,c,"validation_2023_24",cost,delay,portfolio(c,2023,2024,cost,delay));for(int y=2019;y<=2024;y++)row(out,c,to_string(y),cost,delay,portfolio(c,y,y,cost,delay));}}}}
void audit(){ofstream a("results/scalar_samples.csv");a<<"event_i,g,cost,delay,entry_i,exit_i,exit_t,entry,stop,tp,unit,r,minr,maxr,reason,missing\n"<<setprecision(17);int n=0;for(int id=0;id<int(e.size())&&n<600;id++){if(b[e[id].entry].year>2024||mix(id)%53)continue;int g=mix(id+71)%54,delay=int(mix(id+91)%3);double cost=(mix(id+11)%3+2)*.5;auto o=replay(e[id],g,cost,delay);if(!o.valid)continue;n++;a<<id<<','<<g<<','<<cost<<','<<delay<<','<<o.entry_i<<','<<o.exit_i<<','<<o.exit_t<<','<<o.entry<<','<<o.stop<<','<<o.tp<<','<<o.unit<<','<<o.r<<','<<o.minr<<','<<o.maxr<<','<<o.reason<<','<<o.missing<<'\n';}}
int main(int argc,char**argv){try{b=readbin<Bar>("inputs/bars.bin");e=readbin<Event>("inputs/events.bin");news=readbin<unsigned char>("inputs/news.bin");hclose=readbin<double>("inputs/h1_close.bin");if(news.size()!=b.size()||hclose.size()!=b.size())throw runtime_error("Input length mismatch");for(int i=0;i<int(e.size());i++)styles[e[i].style].push_back(i);string mode=argc>1?argv[1]:"screen";if(mode=="screen")screen();else if(mode=="audit")audit();else evaluate(argc>2?argv[2]:"results/shortlist.csv",mode=="final");}catch(exception&x){cerr<<x.what()<<'\n';return 1;}}
