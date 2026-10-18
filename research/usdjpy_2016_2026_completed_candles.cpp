#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <unordered_set>
#include <vector>
using namespace std;
struct Bar { string date; double o,h,l,c,atr,ema[6],prevHigh[4],prevLow[4],mean,sd; };
struct P { int fam,fast,slow,look,side,filter,stop,rr,risk,margin,hold,throttle,thr; uint64_t key; };
struct R { double eq=100,dd=0,pf=0; int trades=0,skips=0,wins=0; };
struct Item {P p;R calibration,train,valid,holdout,full,cost4,cost6;double score=0;};
static vector<Bar> B;
static const int emas[]={5,10,20,30,50,100}, looks[]={5,10,20,40};
static const double stops[]={0.4,0.6,0.845,1.0,1.3,1.7,2.0,2.5}, rr[]={2,3,4,6,8,10}, risks[]={.025,.04,.06,.08,.10,.12,.15,.2075}, margins[]={.1,.2,.35,.5}, thresh[]={.25,.4,.6,.8,1.0,1.4}, holds[]={1,2,3,5,8,15,30};
uint64_t mix(uint64_t &x){x+=0x9e3779b97f4a7c15ULL;uint64_t z=x;z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;z=(z^(z>>27))*0x94d049bb133111ebULL;return z^(z>>31);}
P makeP(uint64_t seed){P p{};auto pick=[&](int n){return int(mix(seed)%uint64_t(n));};
p.fam=pick(7);p.fast=pick(6);p.slow=pick(6);p.look=pick(4);p.side=pick(3);p.filter=pick(3);p.stop=pick(8);p.rr=pick(6);p.risk=pick(8);p.margin=pick(4);p.hold=pick(7);p.throttle=pick(3);p.thr=pick(6);
// Normalize parameters that do not affect the executable signal.
if(p.fam!=2&&p.fam!=3)p.look=0;
if(p.fam==0||p.fam==2||p.fam==3||p.fam==4||p.fam==6)p.thr=0;
// EMA pullback always uses the fast EMA. EMA crossover uses both.
// For other families, both EMAs are inactive without a trend/counter filter.
if(p.filter==0&&p.fam!=0&&p.fam!=6){p.fast=0;p.slow=0;}
if(p.filter==0&&p.fam==0)p.slow=0;
uint64_t k=p.fam;k=k*6+p.fast;k=k*6+p.slow;k=k*4+p.look;k=k*3+p.side;k=k*3+p.filter;k=k*8+p.stop;k=k*6+p.rr;k=k*8+p.risk;k=k*4+p.margin;k=k*7+p.hold;k=k*3+p.throttle;k=k*6+p.thr;p.key=k;return p;
}
bool load(string path){
 ifstream f(path);string line;getline(f,line);
 while(getline(f,line)){stringstream ss(line);string d,o,h,l,c; if(!getline(ss,d,',')||!getline(ss,o,',')||!getline(ss,h,',')||!getline(ss,l,',')||!getline(ss,c,','))continue;
 if(d<"2014-01-01"||d>"2026-10-15")continue;
 try{Bar z{};z.date=d;z.o=stod(o);z.h=stod(h);z.l=stod(l);z.c=stod(c);if(z.o>0&&z.h>=z.l&&z.l>0)B.push_back(z);}catch(...){}}
 if(B.size()<2000)return false;
 for(size_t i=0;i<B.size();i++){auto &b=B[i];double prev=i?B[i-1].c:b.c;double tr=max({b.h-b.l,abs(b.h-prev),abs(b.l-prev)});
 b.atr=i?(B[i-1].atr*13+tr)/14:tr;
 for(int j=0;j<6;j++){double a=2.0/(emas[j]+1);b.ema[j]=i?B[i-1].ema[j]+a*(b.c-B[i-1].ema[j]):b.c;}
 for(int j=0;j<4;j++){double high=-1e20,low=1e20;for(int k=max(0,int(i)-looks[j]);k<int(i);k++){high=max(high,B[k].h);low=min(low,B[k].l);}b.prevHigh[j]=high;b.prevLow[j]=low;}
 int lo=max(0,int(i)-19),len=int(i)-lo+1;double mean=0,sd=0;for(int k=lo;k<=int(i);k++)mean+=B[k].c;mean/=len;for(int k=lo;k<=int(i);k++)sd+=(B[k].c-mean)*(B[k].c-mean);b.mean=mean;b.sd=sqrt(sd/len);
 }
 return true;
}
int entrySignal(int i,const P&p){
 if(i<202)return 0;
 const Bar &z=B[i-1], &prev=B[i-2];double f=z.ema[p.fast],s=z.ema[p.slow],t=thresh[p.thr];int sig=0;
 if(p.fam==0){if(z.l<f&&z.c>f&&z.c>z.o)sig=1;else if(z.h>f&&z.c<f&&z.c<z.o)sig=-1;}
 else if(p.fam==1){if(z.c-z.o>t*z.atr&&z.c>prev.h)sig=1;else if(z.o-z.c>t*z.atr&&z.c<prev.l)sig=-1;}
 else if(p.fam==2){if(z.c>z.prevHigh[p.look])sig=1;else if(z.c<z.prevLow[p.look])sig=-1;}
 else if(p.fam==3){if(z.l<z.prevLow[p.look]&&z.c>z.prevLow[p.look]&&z.c>z.o)sig=1;else if(z.h>z.prevHigh[p.look]&&z.c<z.prevHigh[p.look]&&z.c<z.o)sig=-1;}
 else if(p.fam==4){if(z.c>z.o&&prev.c<prev.o&&z.c>prev.o&&z.o<prev.c)sig=1;else if(z.c<z.o&&prev.c>prev.o&&z.c<prev.o&&z.o>prev.c)sig=-1;}
 else if(p.fam==5){if(z.c-z.o>t*z.atr)sig=1;else if(z.o-z.c>t*z.atr)sig=-1;}
 else if(p.fam==6){if(f>s&&prev.ema[p.fast]<=prev.ema[p.slow])sig=1;else if(f<s&&prev.ema[p.fast]>=prev.ema[p.slow])sig=-1;}
 if(p.side==1&&sig<0)return 0;if(p.side==2&&sig>0)return 0;
 if(p.filter==1&&sig*(f-s)<=0)return 0;
 if(p.filter==2&&sig*(f-s)>=0)return 0;
 return sig;
}
R run(const P &p,int begin,int finish,double fee=0.02){
 R r;double eq=100,peak=100,maxdd=0,gprofit=0,gloss=0;int side=0,qty=0,age=0;double entry=0,sl=0,tp=0;
 for(int i=begin;i<finish;i++){
 const Bar &b=B[i];
 if(side==0){
 int signal=entrySignal(i,p);
 if(signal){
 double dist=stops[p.stop]*B[i-1].atr,risk=risks[p.risk],draw=1-eq/max(1.,peak);
 if(p.throttle==1){if(draw>.15)risk*=.5;if(draw>.25)risk*=.5;}
 if(p.throttle==2){if(draw>.10)risk*=.5;if(draw>.20)risk*=.5;}
 double desired=eq*risk*b.o/max(dist,.001),capacity=eq*200*margins[p.margin];
 int q=int(floor(min(desired,capacity)/1000.))*1000;
 if(q>=1000&&dist>.05){side=signal;qty=q;entry=b.o;sl=entry-signal*dist;tp=entry+signal*dist*rr[p.rr];age=i;}
 else r.skips++;
 }}
 if(side!=0){
 bool stop=side==1?(b.l<=sl):(b.h>=sl),take=side==1?(b.h>=tp):(b.l<=tp);
 // Conservative adverse-first excursion; clamp to stop since worse excursions follow stop execution.
 double worst=side==1?max(b.l,sl):min(b.h,sl);
 if(stop && ((side==1&&b.o<sl)||(side==-1&&b.o>sl)))worst=b.o;
 double marked=max(0.,eq+((worst-entry)*side-fee)*qty/worst);
 maxdd=max(maxdd,1-marked/max(peak,1e-8));
 double closePx=0;
 if(stop)closePx=sl;else if(take)closePx=tp;else if(i-age>=holds[p.hold])closePx=b.c;
 if(closePx){
 if(stop&&((side==1&&b.o<sl)||(side==-1&&b.o>sl)))closePx=b.o;
 else if(!stop&&take&&((side==1&&b.o>tp)||(side==-1&&b.o<tp)))closePx=b.o;
 double pnl=((closePx-entry)*side-fee)*qty/closePx;
 eq=max(0.,eq+pnl);
 if(pnl>0){gprofit+=pnl;r.wins++;}else gloss-=pnl;
 r.trades++;side=0;
 }
 }
 peak=max(peak,eq);maxdd=max(maxdd,1-eq/max(peak,1e-8));
 if(eq<5)break;
 }
 if(side!=0 && eq>=5){auto &b=B[finish-1];double pnl=((b.c-entry)*side-fee)*qty/b.c;eq=max(0.,eq+pnl);r.trades++;if(pnl>0){gprofit+=pnl;r.wins++;}else gloss-=pnl;}
 r.eq=eq;r.dd=100*maxdd;r.pf=gloss>0?gprofit/gloss:0;
 return r;
}
void showR(ostream&f,const R&r){f<<r.eq<<","<<r.dd<<","<<r.trades<<","<<r.pf<<","<<r.skips;}
void showP(ostream&f,const P&p){f<<p.key<<","<<p.fam<<","<<emas[p.fast]<<","<<emas[p.slow]<<","<<looks[p.look]<<","<<(p.side==0?0:p.side==1?1:-1)<<","<<p.filter<<","<<stops[p.stop]<<","<<rr[p.rr]<<","<<risks[p.risk]<<","<<margins[p.margin]<<","<<holds[p.hold]<<","<<p.throttle<<","<<thresh[p.thr];}
int main(int argc,char**argv){
 if(argc<2||!load(argv[1])){cerr<<"INPUT_DATA_UNAVAILABLE_OR_INCOMPLETE\n";return 2;}
 int begin=-1,mid=-1,hold=-1;
 for(int i=0;i<int(B.size());i++){if(begin<0&&B[i].date>="2016-01-01")begin=i;if(mid<0&&B[i].date>="2021-01-01")mid=i;if(hold<0&&B[i].date>="2024-01-01")hold=i;}
 if(begin<0||mid<0||hold<0){cerr<<"SPLIT_MISSING\n";return 3;}
 const int requested=1000000;int evaluated=0,eligible=0,duplicates=0;uint64_t seed=20261018;
 vector<Item> potential;potential.reserve(20000);unordered_set<uint64_t> seen;seen.reserve(requested*2);
 for(int j=0;evaluated<requested;j++){
  P p=makeP(mix(seed));if(!seen.insert(p.key).second){duplicates++;continue;}
  evaluated++;R pre=run(p,begin,hold);
  if(pre.trades>=20&&pre.dd<50&&pre.eq>105&&pre.pf>1.03){
   eligible++;Item it;it.p=p;it.calibration=pre;it.score=log(max(pre.eq,1.)/100.)-0.02*pre.dd;
   potential.push_back(it);
  }
  if(evaluated%100000==0)cerr<<"SCREEN_DONE "<<evaluated<<"\n";
 }
 sort(potential.begin(),potential.end(),[](const Item&a,const Item&b){return a.score>b.score;});
 if(potential.size()>5000)potential.resize(5000);
 int fullpass=0,holdpass=0,reach100k=0;vector<Item> completed;
 for(auto &it:potential){
  it.train=run(it.p,begin,mid);it.valid=run(it.p,mid,hold);it.holdout=run(it.p,hold,int(B.size()));it.full=run(it.p,begin,int(B.size()));
  it.cost4=run(it.p,begin,int(B.size()),.04);it.cost6=run(it.p,begin,int(B.size()),.06);
  if(it.full.eq>=100000 && it.full.dd<50)reach100k++;
  if(it.full.dd<50 && it.full.trades>=20)fullpass++;
  if(it.train.eq>100&&it.train.dd<50&&it.train.trades>=8&&it.valid.eq>100&&it.valid.dd<50&&it.valid.trades>=5&&it.holdout.eq>100&&it.holdout.dd<50&&it.holdout.trades>=5)holdpass++;
  completed.push_back(it);
 }
 sort(completed.begin(),completed.end(),[](const Item&a,const Item&b){bool aok=a.full.dd<50&&a.full.trades>=20,bok=b.full.dd<50&&b.full.trades>=20;if(aok!=bok)return aok;return a.full.eq>b.full.eq;});
 ofstream f("ranked_results.csv");f<<"key,family,fast,slow,look,side,filter,stop_atr,target_r,risk_fraction,margin_fraction,hold_days,throttle,threshold,cal_eq,cal_dd,cal_trades,cal_pf,cal_skips,train_eq,train_dd,train_trades,train_pf,train_skips,valid_eq,valid_dd,valid_trades,valid_pf,valid_skips,oos_eq,oos_dd,oos_trades,oos_pf,oos_skips,full_eq,full_dd,full_trades,full_pf,full_skips,cost4_eq,cost4_dd,cost4_trades,cost4_pf,cost4_skips,cost6_eq,cost6_dd,cost6_trades,cost6_pf,cost6_skips\n";
 for(auto &z:completed){showP(f,z.p);f<<",";showR(f,z.calibration);f<<",";showR(f,z.train);f<<",";showR(f,z.valid);f<<",";showR(f,z.holdout);f<<",";showR(f,z.full);f<<",";showR(f,z.cost4);f<<",";showR(f,z.cost6);f<<"\n";}
 ofstream report("audit_summary.json");
 report<<"{\n\"status\":\"D1_2016_2026_OCT15_CLOSED_BAR_ONLY_NOT_NATIVE_TICK\",\n\"source\":\"becoin.net Yahoo Finance-derived USDJPY daily OHLC\",\n\"first\":\""<<B[begin].date<<"\",\"last\":\""<<B.back().date<<"\",\n\"calibration_end\":\"2023-12-31\",\"holdout_start\":\"2024-01-01\",\n\"requested_unique\":1000000,\"evaluated_unique\":"<<evaluated<<",\"duplicates_rejected\":"<<duplicates<<",\"eligible_calibration\":"<<eligible<<",\"shortlist_retested\":"<<completed.size()<<",\"pass_full_dd50\":"<<fullpass<<",\"pass_separate_periods\":"<<holdpass<<",\"reach_100k_full_dd50\":"<<reach100k<<",\"top\": [\n";
 for(int k=0;k<int(min(size_t(12),completed.size()));k++){auto &v=completed[k];report<<(k?",\n":"")<<"{\"rank\":"<<k+1<<",\"key\":"<<v.p.key<<",\"balance\":"<<v.full.eq<<",\"max_dd\":"<<v.full.dd<<",\"trades\":"<<v.full.trades<<",\"pf\":"<<v.full.pf<<",\"holdout_balance\":"<<v.holdout.eq<<",\"holdout_trades\":"<<v.holdout.trades<<",\"cost4_balance\":"<<v.cost4.eq<<",\"cost4_dd\":"<<v.cost4.dd<<"}";}
 report<<"\n]}\n";
 cout<<"EVALUATED_UNIQUE="<<evaluated<<" CALIBRATION_PASS="<<eligible<<" SHORTLIST="<<completed.size()<<" FULL_DD50="<<fullpass<<" SEPARATE_PERIOD_PASS="<<holdpass<<" TARGET100K="<<reach100k<<"\n";
 for(int k=0;k<int(min(size_t(10),completed.size()));k++){auto &v=completed[k];cout<<"TOP_"<<k+1<<" key="<<v.p.key<<" equity="<<v.full.eq<<" dd="<<v.full.dd<<" pf="<<v.full.pf<<" trades="<<v.full.trades<<" oos="<<v.holdout.eq<<" oosTrades="<<v.holdout.trades<<" cost4="<<v.cost4.eq<<"\n";}
}
