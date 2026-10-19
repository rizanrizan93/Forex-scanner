// USDJPY M1 research-only: F0245-inspired M15 sweep/H1 bias with frozen EUR core as a structural reference.
// Not byte-identical F0245. No cTrader orders or bridge writes.
// USD base currency, JPY quote. Margin in USD, pnl conversion in USD using exit JPY quote.
// No invented intrabar ordering: STOP_FIRST, and any break-even update applies only to next minute.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>
using namespace std;
struct Bar{int64_t minute;float o,h,l,c;};
struct Aggregate{int64_t open=0;float o=0,h=0,l=0,c=0;int count=0;double atr=0,prior5H=0,prior5L=0,prior8H=0,prior8L=0,prior12H=0,prior12L=0;int h1bias=99;};
struct Signal{int idx=0,side=0;float atr=0;int hour=0;int year=0;int mcount=0;};
struct P{int look=8,bias=0,side=0,session=0,layers=3,hold=240,be=2;double atrStop=3.0,tpR=4,risk=.2725,margin=.5,minBody=.2,spread=.02;int id=0;};
struct Result{double eq=100,dd=0,pf=0;int trades=0,wins=0,signals=0,skips=0,adds=0;};
static vector<Bar> bars;
static vector<Signal> signals;
static vector<Aggregate> m15,h1;
static int64_t parseMin(const string& s){int Y=atoi(s.substr(0,4).c_str()),m=atoi(s.substr(5,2).c_str()),d=atoi(s.substr(8,2).c_str()),hh=atoi(s.substr(11,2).c_str()),mm=atoi(s.substr(14,2).c_str());tm v={};v.tm_year=Y-1900;v.tm_mon=m-1;v.tm_mday=d;v.tm_hour=hh;v.tm_min=mm;return int64_t(timegm(&v))/60;}
int year(int64_t min){time_t t=time_t(min*60);tm x={};gmtime_r(&t,&x);return x.tm_year+1900;}
int hour(int64_t min){time_t t=time_t(min*60);tm x={};gmtime_r(&t,&x);return x.tm_hour;}
bool load(string path){
 ifstream f(path);string line;getline(f,line);
 int64_t prev=-1;while(getline(f,line)){if(line.size()<30)continue;stringstream s(line);string t,a,b,c,d;
 if(!getline(s,t,',')||!getline(s,a,',')||!getline(s,b,',')||!getline(s,c,',')||!getline(s,d,','))continue;
 Bar row{};row.minute=parseMin(t);row.o=atof(a.c_str());row.h=atof(b.c_str());row.l=atof(c.c_str());row.c=atof(d.c_str());
 if(row.minute<=prev||row.o<50||row.l<50||row.h<row.l||row.l>min(row.o,row.c)||row.h<max(row.o,row.c))return false;
 bars.push_back(row);prev=row.minute;
 }
 return bars.size()>3800000;
}
void aggregate(){
 auto add=[](vector<Aggregate>& v,int width,const Bar& b){
  int64_t slot=b.minute-b.minute%width;
  if(v.empty()||v.back().open!=slot){Aggregate x; x.open=slot;x.o=b.o;x.h=b.h;x.l=b.l;x.c=b.c;x.count=1;v.push_back(x);}
  else{auto& x=v.back();x.h=max(x.h,b.h);x.l=min(x.l,b.l);x.c=b.c;x.count++;}
 };
 for(auto &b:bars){add(m15,15,b);add(h1,60,b);}
 double ema=0; for(size_t i=0;i<h1.size();i++){auto &b=h1[i];ema=i?ema+(2.0/51.0)*(b.c-ema):b.c;h1[i].atr=ema;double slope=i>=2?ema-h1[i-2].atr:0;h1[i].h1bias=b.c>ema&&slope>0?1:b.c<ema&&slope<0?-1:0;}
 vector<double> tr(m15.size());for(size_t i=0;i<m15.size();i++){const auto& a=m15[i];tr[i]=max({double(a.h-a.l),i?abs(double(a.h-m15[i-1].c)):0.,i?abs(double(a.l-m15[i-1].c)):0.});if(i>=13){double sm=0;for(int k=0;k<14;k++)sm+=tr[i-k];m15[i].atr=sm/14;}}
 size_t hidx=0;
 for(size_t i=0;i<m15.size();i++){
  auto& a=m15[i];int64_t available=a.open+15;
  while(hidx+1<h1.size()&&h1[hidx+1].open+60<=available)hidx++;
  a.h1bias=(h1[hidx].open+60<=available)?h1[hidx].h1bias:99;
  for(int look: {5,8,12}){
   double hi=-1e99,lo=1e99; if(i>=size_t(look)){for(size_t k=i-look;k<i;k++){hi=max(hi,double(m15[k].h));lo=min(lo,double(m15[k].l));}}
   if(look==5){a.prior5H=hi;a.prior5L=lo;}
   else if(look==8){a.prior8H=hi;a.prior8L=lo;}
   else{a.prior12H=hi;a.prior12L=lo;}
  }
 }
 size_t bidx=0;
 for(size_t i=14;i<m15.size();i++){
  const auto &m=m15[i];int64_t timestamp=m.open+15;
  while(bidx<bars.size()&&bars[bidx].minute<timestamp)bidx++;
  if(bidx>=bars.size())break;
  if(bars[bidx].minute-timestamp>2)continue;
  if(m.count<12||m.atr<=0||m.h1bias==99)continue;
  Signal s;s.idx=int(bidx);s.atr=m.atr;s.hour=hour(timestamp);s.year=year(timestamp);s.mcount=m.count;
  // expand distinct signal templates here; during replay calculate the predicate at s.idx using cached data.
  signals.push_back(s);
 }
}
bool satisfies(const P&p,const Signal&s,const Aggregate &a,int& side){
 auto prior=[&](){if(p.look==5)return pair<double,double>{a.prior5H,a.prior5L};if(p.look==12)return pair<double,double>{a.prior12H,a.prior12L};return pair<double,double>{a.prior8H,a.prior8L};};
 auto [ph,pl]=prior();
 double body=a.h>a.l?(a.c-a.o)/(a.h-a.l):0;
 side=a.l<pl&&a.c>pl&&body>p.minBody?1:a.h>ph&&a.c<ph&&body<-p.minBody?-1:0;
 if(!side||ph<50||pl<50)return false;
 if(p.side==1&&side==-1)return false;if(p.side==-1&&side==1)return false;
 if(p.bias==0&&a.h1bias!=0)return false;
 if(p.bias==1&&a.h1bias!=side)return false;
 if(p.bias==2&&a.h1bias!=-side)return false;
 if(p.session==0&&(s.hour<7||s.hour>=12))return false;
 if(p.session==1&&(s.hour<12||s.hour>=20))return false;
 if(p.session==2&&(s.hour<7||s.hour>=20))return false;
 return true;
}
int64_t expiryMin(int64_t start,int hold){
 // Same-day cutoff 20:00 UTC as archived EUR source, except 24/7 research session when session==3.
 int64_t floorDay=start-(start%1440);
 return min(start+hold, floorDay+20*60);
}
Result replay(const P&p,int yr1,int yr2,double spreadOverride=-1){
 Result r;double eq=100,peak=100,dd=0,gp=0,gl=0,fee=spreadOverride>=0?spreadOverride:p.spread;
 // Iterate through M15 candidate timestamps; calculate actual positions on contiguous M1.
 int64_t busyUntil=-1;size_t cursor=0;
 for(const Signal&sg:signals){
  if(sg.year<yr1||sg.year>yr2)continue;
  if(bars[sg.idx].minute<=busyUntil)continue;
  int64_t eventTime=bars[sg.idx].minute;
  while(cursor<m15.size()&&m15[cursor].open+15<=eventTime)cursor++;
  if(cursor==0)continue;
  const Aggregate &a=m15[cursor-1];if(a.open+15>eventTime||eventTime-(a.open+15)>2)continue;
  int side=0;if(!satisfies(p,sg,a,side))continue;
  r.signals++;
  double entry=bars[sg.idx].o+(side==1?fee:0),stopDist=max(.035,min(1.5,p.atrStop*double(sg.atr)));
  double stop=entry-side*stopDist,tp=entry+side*stopDist*p.tpR;
  double riskBudget=eq*p.risk;
  // 1 lot is 1000 USD base; leverage 200, cap margin share
  double marginBudget=eq*p.margin*200;
  const auto unitRisk=[&](double price){return max(.00001,abs(price-stop))/entry+0.00006/1000.;};
  int qty=(int)floor(min((riskBudget*(p.layers==3?.4:1.))/unitRisk(entry),marginBudget)/1000.)*1000;
  if(qty<1000){r.skips++;continue;}
  int n=qty;double costPaid=qty/1000.*.03,entryAvg=entry,breakeven=entry;
  bool hasAdds1=false,hasAdds2=false,movedBE=false;
  int64_t maxHold=p.session==3?bars[sg.idx].minute+p.hold:expiryMin(bars[sg.idx].minute,p.hold);
  double stage1price=entry-side*stopDist*.2,stage2price=entry-side*stopDist*.4;
  double currentStageBudget=riskBudget*.6;
  double stage1Part=pow(2.,1.5)/(pow(2.,1.5)+pow(3.,1.5));
  double pnl=0;
  int lastidx=sg.idx,untilCount=0;
  for(size_t k=sg.idx;k<bars.size();k++){
   const Bar &bar=bars[k];if(year(bar.minute)>yr2)break;
   double askOpen=bar.o+fee,askHigh=bar.h+fee,askLow=bar.l+fee,askClose=bar.c+fee;
   double worst=side==1?bar.l:askHigh;
   // On gaps, fill at first tradable quote; avoid fictitious execution at missing minute.
   bool missing=k>size_t(sg.idx)&&(bar.minute-bars[k-1].minute>5);
   bool hitStop=side==1?bar.l<=stop:askHigh>=stop;
   bool hitTP=side==1?bar.h>=tp:askLow<=tp;
   double px=0;
   if(missing){px=side==1?bar.o:askOpen;}
   else if(hitStop){px=stop;if(side==1)px=min(stop,double(bar.o));else px=max(stop,askOpen);}
   else if(hitTP){px=tp;if(side==1)px=max(tp,double(bar.o));else px=min(tp,askOpen);}
   else if(bar.minute>=maxHold){px=side==1?bar.o:askOpen;}
   // Floating drawdown bounded by executable stop, but opening gaps can exceed it.
   double adverse=side==1?max(double(bar.l),stop):min(askHigh,stop);
   if(hitStop&&missing)adverse=px;
   double equityWorst=max(0.,eq+(side*(adverse-entryAvg))*n/max(adverse,50.)-costPaid-n/1000.*.03);
   dd=max(dd,1-equityWorst/max(peak,.01));
   if(px>0){
     pnl=(side*(px-entryAvg))*n/px-costPaid-n/1000.*.03;
     eq=max(0.,eq+pnl);r.trades++;if(pnl>0){gp+=pnl;r.wins++;}else gl-=pnl;
     busyUntil=bar.minute;lastidx=int(k);break;
   }
   // Only add after no stop/take on this minute, and no updated stop from future same-minute extremes.
   if(p.layers==3){
    for(int stage=0;stage<2;stage++){
      bool &added=stage==0?hasAdds1:hasAdds2;
      if(added)continue;
      double level=stage==0?stage1price:stage2price;
      bool touched=side==1?bar.l<=level:askHigh>=level;
      if(touched){
       double riskForStage=currentStageBudget*(stage==0?stage1Part:1-stage1Part);
       double fill=side==1?level+fee:level;
       double perUnitRisk=abs(fill-stop)/entry+.00006/1000.;
       int left=(int)floor(max(0.,marginBudget-n)/1000.)*1000;
       int units=(int)floor(min(riskForStage/perUnitRisk,double(left))/1000.)*1000;
       if(units>=1000){
        entryAvg=(entryAvg*n+fill*units)/(n+units);
        n+=units;costPaid+=units/1000.*.03;r.adds++;
       }
       added=true;
      }
    }
   }
   if(p.be>0&&!movedBE){
    bool trigger=side==1?bar.h>=entry+p.be*stopDist:askLow<=entry-p.be*stopDist;
    if(trigger){double revised=entry+side*(fee+0.001);stop=side==1?max(stop,revised):min(stop,revised);movedBE=true;}
   }
   lastidx=int(k);
   if(k>size_t(sg.idx)+p.hold+400)break;
  }
  // Continuous mark peak at trade exit, no simultaneous positions.
  peak=max(peak,eq);dd=max(dd,1-eq/max(peak,.01));
  if(eq<5)break;
 }
 r.eq=eq;r.dd=100*dd;r.pf=gl>0?gp/gl:0;return r;
}
int main(int argc,char**argv){
 if(argc<2||!load(argv[1])){cerr<<"M1_SOURCE_REJECTED\n";return 2;}
 aggregate();
 ofstream summary("m1_data_validation.json");summary<<"{\"bars\":"<<bars.size()<<",\"first\":"<<bars.front().minute<<",\"last\":"<<bars.back().minute<<",\"m15\":"<<m15.size()<<",\"h1\":"<<h1.size()<<",\"signal_times\":"<<signals.size()<<"}\n";summary.close();
 cout<<"M1_VERIFIED bars="<<bars.size()<<" M15="<<m15.size()<<" H1="<<h1.size()<<" signal_times="<<signals.size()<<"\n";
 uint64_t seed=20261019;
 auto random=[&](){seed+=0x9e3779b97f4a7c15ULL;uint64_t z=seed;z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;z=(z^(z>>27))*0x94d049bb133111ebULL;return z^(z>>31);};
 auto pick=[&](int n){return int(random()%n);};
 vector<P> params;
 params.push_back(P{}); // EUR-cBot inspired baseline scaled to JPY
 for(int i=0;i<1800;i++){
  P p;p.id=i+1;
  p.look=vector<int>{5,8,12}[pick(3)];p.bias=pick(4);p.side=pick(3)-1;p.session=pick(4);p.layers=pick(2)?3:1;
  p.hold=vector<int>{60,120,240,480}[pick(4)];p.be=vector<int>{0,2}[pick(2)];
  p.atrStop=vector<double>{1.5,2,3,4}[pick(4)];
  p.tpR=vector<double>{2,4,6,8,10}[pick(5)];
  p.risk=vector<double>{.04,.08,.12,.20,.2725}[pick(5)];
  p.margin=vector<double>{.1,.25,.5}[pick(3)];
  p.minBody=vector<double>{.2,.35,.5}[pick(3)];
  params.push_back(p);
 }
 struct Row{P p;Result train,valid,test,full,cost2,cost4;};
 vector<Row> all;all.reserve(params.size());
 for(const auto &p:params){
  auto tr=replay(p,2016,2020);
  auto va=replay(p,2021,2023);
  auto te=replay(p,2024,2026);
  auto full=replay(p,2016,2026);
  if(full.trades>=15)all.push_back({p,tr,va,te,full,Result{},Result{}});
  if(p.id%300==0)cerr<<"SCREEN "<<p.id<<"\n";
 }
 // Rank by continuous full balance, then stress top 100 only.
 sort(all.begin(),all.end(),[](const Row &a,const Row &b){return a.full.eq>b.full.eq;});
 for(int i=0;i<int(all.size())&&i<100;i++){all[i].cost2=replay(all[i].p,2016,2026,.04);all[i].cost4=replay(all[i].p,2016,2026,.08);}
 int achieved=0,under50=0,segpass=0;
 for(const auto &x:all){if(x.full.dd<50&&x.full.trades>=15){under50++;if(x.full.eq>=100000)achieved++;}
 if(x.train.eq>100&&x.valid.eq>100&&x.test.eq>100&&x.train.dd<50&&x.valid.dd<50&&x.test.dd<50&&x.train.trades>=5&&x.valid.trades>=5&&x.test.trades>=5)segpass++;}
 auto write=[&](ostream&os,const Result&r){os<<fixed<<setprecision(4)<<r.eq<<","<<r.dd<<","<<r.trades<<","<<r.pf<<","<<r.skips<<","<<r.adds;};
 ofstream f("m1_candidate_results.csv");
 f<<"id,look,bias,side,session,layers,hold_min,be_R,stop_atr,tp_R,risk,margin,body_min,train_eq,train_dd,train_trades,train_pf,train_skips,train_adds,valid_eq,valid_dd,valid_trades,valid_pf,valid_skips,valid_adds,test_eq,test_dd,test_trades,test_pf,test_skips,test_adds,full_eq,full_dd,full_trades,full_pf,full_skips,full_adds,fee4_eq,fee4_dd,fee4_trades,fee4_pf,fee4_skips,fee4_adds,fee8_eq,fee8_dd,fee8_trades,fee8_pf,fee8_skips,fee8_adds\n";
 for(const auto&x:all){const P&p=x.p;f<<p.id<<","<<p.look<<","<<p.bias<<","<<p.side<<","<<p.session<<","<<p.layers<<","<<p.hold<<","<<p.be<<","<<p.atrStop<<","<<p.tpR<<","<<p.risk<<","<<p.margin<<","<<p.minBody<<",";
 write(f,x.train);f<<",";write(f,x.valid);f<<",";write(f,x.test);f<<",";write(f,x.full);f<<",";write(f,x.cost2);f<<",";write(f,x.cost4);f<<"\n";}
 cout<<"SIMULATION_COMPLETE tested="<<params.size()<<" evaluated_min_trades="<<all.size()<<" under50="<<under50<<" target100k="<<achieved<<" segments_consistent="<<segpass<<"\n";
 for(int i=0;i<int(all.size())&&i<10;i++){auto &x=all[i];cout<<"TOP "<<i+1<<" id="<<x.p.id<<" full="<<x.full.eq<<" DD="<<x.full.dd<<" trades="<<x.full.trades<<" OOS="<<x.test.eq<<" train="<<x.train.eq<<" val="<<x.valid.eq<<" stress4="<<x.cost2.eq<<" stress8="<<x.cost4.eq<<"\n";}
}
