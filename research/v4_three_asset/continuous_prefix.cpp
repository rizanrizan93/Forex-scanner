#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>
#include <omp.h>
using namespace std;namespace fs=std::filesystem;
struct Candidate{int64_t t;int32_t idx,symbol,side,trend;double atr,anchor;};static_assert(sizeof(Candidate)==40);
struct Bar{double o,h,l,c,s;};static_assert(sizeof(Bar)==40);
struct Asset{vector<int64_t> t;vector<Bar>b;};
struct Event{int64_t t,exit;int symbol,trend,side;double risk,margin,cost,pnl,mfe,mae;int gap;};
struct Params{int base,sl,tp,hold,trend,session,risk,universe,day,threshold,direction;};
struct Result{array<double,8>end{},dd{};array<int,8>trades{};array<int64_t,8>grad{};double score=-1e99;};
struct Row{Params p;Result r;};
const double STOP[]={.35,.75,1.25,2},TP[]={1,2,3,5,8},RISK[]={.05,.08},THRESH[]={250,500,1000,2000,1e12};
const int UNIVERSE[]={1,2,4,7,3,5,6};
const int HOLD[]={15,30,60,120,240,480},DAYS[]={1,2,4};const double STEP[]={1000,1,.01},MAXSTEPS[]={2000,2000,10000};
int64_t CONT_END=0;


vector<Asset>assets(3);vector<vector<Candidate>>bases(64);mutex mx;atomic<uint64_t> tested{0},annuals{0},passes{0},zeroall{0},fills{0},gapfills{0};uint64_t xorhash=0;vector<Row> winners;unordered_set<uint64_t> economic;
template<class T>vector<T>readbin(const fs::path&p){ifstream f(p,ios::binary|ios::ate);if(!f)throw runtime_error("missing:"+p.string());size_t n=f.tellg();if(n%sizeof(T))throw runtime_error("size");vector<T>a(n/sizeof(T));f.seekg(0);f.read((char*)a.data(),n);return a;}
double slip(int s,double p,double cost){return (s==0?.00001:s==1?.05:p*.0001)*cost;}
double fee(int s,double p,double cost){return (s==0?.00003:s==1?.03:p*.0005)*cost;}
Event outcome(const Candidate&c,int sm,int tm,int hm,double friction=1){
 const auto&a=assets[c.symbol];int k=c.idx,side=c.side,s=c.symbol;const auto&b=a.b[k];double spread=b.s*friction,sp=slip(s,b.o,friction),entry=b.o+(side>0?spread:0)+side*sp;
 double anch=c.anchor+(side<0?spread:0),distance=max(STOP[sm]*c.atr,side*(entry-anch));distance=max(distance,s==0?.00005:s==1?.5:1.);
 Event e{c.t,c.t,s,c.trend,side,0,0,0,0,0,0,0};if(s==2&&((c.t/1440+4)%7==0||(c.t/1440+4)%7==6||((c.t/1440+4)%7==5&&c.t%1440>=1260)))return e;if(side*(b.o-c.anchor)<=0||!isfinite(distance)||distance<=0)return e;
 double ef=fee(s,entry,friction),xf=fee(s,entry+distance,friction);double cost=spread+sp+ef;
 double stop=entry-side*distance,target=entry+side*TP[tm]*distance;
 if(c.t>=CONT_END)return e;
 int64_t deadline=min({c.t+(int64_t)HOLD[hm],(c.t/1440)*1440+1200,CONT_END});
 double preplanned=distance+ef+xf+sp+(s==2?entry*.0003*HOLD[hm]/1440.*friction:0);double preexpected=TP[tm]*distance-ef-xf-sp;if(preexpected/preplanned<.8)return e;
 double funding=0,mfe=-cost,mae=-cost,px=b.o;int64_t last=c.t;int j=k;bool exited=false;
 for(;j<(int)a.t.size()&&a.t[j]<CONT_END;j++){
  const auto&q=a.b[j];int64_t at=a.t[j];double ss=q.s*friction,op=q.o+(side<0?ss:0),hi=q.h+(side<0?ss:0),lo=q.l+(side<0?ss:0),sl=slip(s,q.o,friction);
  if(j>k&&at>a.t[j-1]+1)e.gap+=(int)(at-a.t[j-1]-1);
  if(s==2)funding+=q.o*.0003*max<int64_t>(0,at-last)/1440.*friction;last=at;
  if(at>=deadline){px=op-side*sl;e.exit=at;exited=true;break;}
  if(side*(op-stop)<=0){px=op-side*sl;e.exit=at+1;exited=true;break;}
  if(side*(op-target)>=0){px=op-side*sl;e.exit=at+1;exited=true;break;}
  double fav=side>0?min(hi,target):max(lo,target),adv=side>0?max(lo,stop):min(hi,stop);
  mfe=max(mfe,side*(fav-entry)-ef);mae=min(mae,side*(adv-entry)-ef-funding);
  bool hs=side>0?lo<=stop:hi>=stop,ht=side>0?hi>=target:lo<=target;
  if(hs||ht){px=(hs?stop:target)-side*sl;e.exit=at+1;exited=true;break;}
 }
 if(!exited){j=min(j-1,(int)a.t.size()-1);if(j<k)return e;const auto&q=a.b[j];px=q.c+(side<0?q.s*friction:0)-side*slip(s,q.o,friction);e.exit=a.t[j]+1;}
 double pnl=side*(px-entry)-ef-fee(s,px,friction)-funding;
 double planned=distance+ef+xf+sp+(s==2?entry*.0003*HOLD[hm]/1440.*friction:0);
 double expected=TP[tm]*distance-ef-xf-sp;if(expected/planned<.8)return e;
 e.risk=STEP[s]*planned;e.margin=STEP[s]*(b.o+spread)/200.;e.cost=STEP[s]*cost;e.pnl=STEP[s]*pnl;e.mfe=STEP[s]*max(mfe,pnl);e.mae=STEP[s]*min(mae,pnl);return e;
}
bool session(const Event&e,int z){int h=(e.t%1440)/60;if(z==5)return h<7;if(z==4)return h>=17&&h<20;if(z==0)return h<20;if(z==1)return e.symbol==0?(h>=7&&h<12):e.symbol==1?(h>=12&&h<17):h<20;if(z==2)return h>=7&&h<12;return h>=12&&h<17;}
uint64_t mix(uint64_t h,uint64_t v){h^=v;return h*1099511628211ULL;}
uint64_t fingerprint(const Result&r){uint64_t h=1469598103934665603ULL;for(int y=0;y<8;y++){h=mix(h,bit_cast<uint64_t>(r.end[y]));h=mix(h,bit_cast<uint64_t>(r.dd[y]));h=mix(h,r.trades[y]);h=mix(h,r.grad[y]);}return h;}
