// XAU source-inspired USDJPY M1 study. Does not modify / represent parity of frozen XAU cBot.
// Closed H1 + M15 strict filter, closed M5 regression BUY / 24-bar sweep->confirm SELL.
// Single net 0.01-lot multiple, USDJPY PnL in USD, buy ask, sell bid; stop-first; bar-level mark.
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
#include <sstream>
#include <string>
#include <vector>
using namespace std;
struct Bar{int64_t m;float o,h,l,c;};
struct Agg{int64_t t=0;float o=0,h=0,l=0,c=0;int n=0,bias=0;double e50=0,e200=0,atr=0,fit=0,dev=0;};
struct Signal{int idx=0,side=0,mode=0,utcHour=0,year=0;double atr=0,anchor=0;};
struct P{int id=0,session=0,mode=0,filter=0,hold=0,cooldown=0,stop=0,tp=0,risk=0,margin=0;};
struct Result{double eq=100,dd=0,pf=0;int trades=0,wins=0,skips=0,signals=0;};
static vector<Bar> bars;
static vector<Agg> m5,m15,h1;
static vector<Signal> setups;
static const int holding[]={120,240,360,480};
static const double atrStop[]={1.2,1.8,2.4,2.65,3.2,4.0};
static const double targetR[]={2,3,4,5.5,6.6,8,10};
static const double riskR[]={.025,.04,.06,.08,.10,.121,.125,.15};
static const double marginR[]={.1,.2,.35,.5};
int64_t parseMin(const string&v){tm z={};z.tm_year=atoi(v.substr(0,4).c_str())-1900;z.tm_mon=atoi(v.substr(5,2).c_str())-1;z.tm_mday=atoi(v.substr(8,2).c_str());z.tm_hour=atoi(v.substr(11,2).c_str());z.tm_min=atoi(v.substr(14,2).c_str());return int64_t(timegm(&z))/60;}
int utcYear(int64_t t){time_t v=time_t(t*60);tm a={};gmtime_r(&v,&a);return a.tm_year+1900;}
int utcHour(int64_t t){return int((t%1440)/60);}
bool load(const char*path){
 ifstream f(path);if(!f)return false;string line;getline(f,line);int64_t prev=-1;
 while(getline(f,line)){
  if(line.size()<35)continue;stringstream ss(line);string d,a,h,l,c;
  if(!getline(ss,d,',')||!getline(ss,a,',')||!getline(ss,h,',')||!getline(ss,l,',')||!getline(ss,c,','))continue;
  Bar b{parseMin(d),stof(a),stof(h),stof(l),stof(c)};
  if(b.m<=prev||b.o<60||b.l>min(b.o,b.c)+1e-4||b.h<max(b.o,b.c)-1e-4||b.h<b.l)return false;
  bars.push_back(b);prev=b.m;
 }
 return bars.size()>3900000;
}
void add(vector<Agg>& dst,const Bar& b,int w){
 int64_t start=b.m-(b.m%w);
 if(dst.empty()||dst.back().t!=start){Agg r;r.t=start;r.o=b.o;r.h=b.h;r.l=b.l;r.c=b.c;r.n=1;dst.push_back(r);}
 else{Agg& a=dst.back();a.h=max(a.h,b.h);a.l=min(a.l,b.l);a.c=b.c;a.n++;}
}
void compute(){
 for(const auto&b:bars){add(m5,b,5);add(m15,b,15);add(h1,b,60);}
 auto strict=[](vector<Agg>&xs){
  for(size_t i=0;i<xs.size();i++){
   auto &b=xs[i];
   b.e50=i?xs[i-1].e50+2./51*(b.c-xs[i-1].e50):b.c;
   b.e200=i?xs[i-1].e200+2./201*(b.c-xs[i-1].e200):b.c;
   double slope=i>=2?b.e50-xs[i-2].e50:0;
   b.bias=(b.c>b.e200&&slope>=0)?1:(b.c<b.e200&&slope<=0)?-1:0;
  }
 };
 strict(h1);strict(m15);
 vector<double> tr(m5.size());
 for(size_t i=0;i<m5.size();i++){
  auto&b=m5[i];tr[i]=max({double(b.h-b.l),i?abs(double(b.h-m5[i-1].c)):0.,i?abs(double(b.l-m5[i-1].c)):0.});
  if(i>=13){double sm=0;for(int k=0;k<14;k++)sm+=tr[i-k];b.atr=sm/14.;}
  if(i>=47){
   double mean=0,weighted=0,variance=0;
   for(int k=0;k<48;k++){double v=m5[i-47+k].c;mean+=v/48.;weighted+=k*v;}
   double slope=(weighted-48.*47/2*mean)/(48.*(48.*48-1)/12.);
   b.fit=mean+slope*47/2.;
   for(int k=0;k<48;k++){double d=m5[i-47+k].c-mean;variance+=d*d/48.;}
   b.dev=sqrt(variance);
  }
 }
 size_t hIdx=0,qIdx=0,bIdx=0;int lastSweepHigh=-999,lastSweepLow=-999;double sweepLow=0,sweepHigh=0;
 for(int i=0;i<int(m5.size());i++){
  const Agg& b=m5[i];int64_t close=b.t+5;
  while(hIdx+1<h1.size()&&h1[hIdx+1].t+60<=close)hIdx++;
  while(qIdx+1<m15.size()&&m15[qIdx+1].t+15<=close)qIdx++;
  while(bIdx<bars.size()&&bars[bIdx].m<close)bIdx++;
  if(bIdx>=bars.size())break;
  bool good=b.n==5&&bars[bIdx].m-close<=2&&bIdx>0&&bars[bIdx-1].m==close-1;
  bool filters=h1[hIdx].t+60<=close&&m15[qIdx].t+15<=close && h1[hIdx].n==60&&m15[qIdx].n==15;
  int strictBias=filters?(h1[hIdx].bias==1&&m15[qIdx].bias==1?1:(h1[hIdx].bias==-1&&m15[qIdx].bias==-1?-1:0)):0;
  if(i>55&&good&&b.atr>0&&filters){
   // Frozen XAU BUY regression lower-band reclaim, using completed prior regression only.
   const Agg&p=m5[i-1],&p2=m5[i-2];
   bool longRaw=b.c>p.fit-1.5*p.dev && p.c<=p2.fit-1.5*p2.dev && b.c>b.o;
   // Frozen SELL: reclaim failure 1-3 bars after a 24-bar high sweep.
   bool shortRaw=i-lastSweepHigh>0&&i-lastSweepHigh<=3&&b.c<sweepLow-.05*b.atr&&b.c<b.o;
   if(longRaw&&strictBias==1){
    double anchor=1e9;for(int k=max(0,i-2);k<=i;k++)anchor=min(anchor,double(m5[k].l));
    setups.push_back(Signal{int(bIdx),1,1,utcHour(close),utcYear(close),b.atr,anchor-.1*b.atr});
   }
   if(shortRaw&&strictBias==-1){
    setups.push_back(Signal{int(bIdx),-1,2,utcHour(close),utcYear(close),b.atr,sweepHigh+.1*b.atr});
   }
   if(shortRaw)lastSweepHigh=-999;
  }
  if(i>=24){
   double pl=1e9,ph=-1e9;for(int j=i-24;j<i;j++){pl=min(pl,double(m5[j].l));ph=max(ph,double(m5[j].h));}
   if(b.h>ph&&b.c<ph&&b.n==5){lastSweepHigh=i;sweepLow=b.l;sweepHigh=b.h;}
  }
 }
}
bool accept(const P&p,const Signal&s){
 if(p.mode==1&&s.side!=1)return false;
 if(p.mode==2&&s.side!=-1)return false;
 if(p.session==0&&(s.utcHour<12||s.utcHour>=17))return false;
 if(p.session==1&&(s.utcHour<7||s.utcHour>=12))return false;
 if(p.session==2&&(s.utcHour<12||s.utcHour>=20))return false;
 if(p.session==3&&(s.utcHour<0||s.utcHour>=24))return false;
 return true;
}
Result replay(const P&p,int start,int last,double cost=.02){
 Result r;double eq=100,peak=100,dd=0,gp=0,gl=0;
 int64_t busyTo=-1,lastLoss=-9999999;
 for(const auto&s:setups){
  if(s.year<start||s.year>last||!accept(p,s))continue;
  int64_t at=bars[s.idx].m;
  if(at<=busyTo||at-lastLoss<p.cooldown*1440)continue;
  r.signals++;
  const Bar& first=bars[s.idx];double px=first.o+(s.side==1?cost:0),dist=max(atrStop[p.stop]*s.atr,s.side*(px-s.anchor));
  if(dist<.025||dist>2.5){r.skips++;continue;}
  double riskUnit=dist/px+(.06/1000.),planned=eq*riskR[p.risk];
  int units=int(floor(min(planned/riskUnit,eq*200*marginR[p.margin])/1000.))*1000;
  if(units<1000){r.skips++;continue;}
  double sl=px-s.side*dist,tp=px+s.side*dist*targetR[p.tp];
  int64_t closeAt=at+holding[p.hold];if(p.session!=3)closeAt=min(closeAt,at-at%1440+19*60+59);
  double entryFee=.03*(units/1000.);
  double pnl=0;bool closed=false;
  for(size_t j=s.idx;j<bars.size();j++){
   const Bar& b=bars[j];
   if(utcYear(b.m)>last)break;
   bool gap=j>size_t(s.idx)&&b.m-bars[j-1].m>5;
   double ao=b.o+cost,ah=b.h+cost,al=b.l+cost;
   bool hitStop=s.side==1?b.l<=sl:ah>=sl;
   bool hitTP=s.side==1?b.h>=tp:al<=tp;
   double worst=s.side==1?max(double(b.l),sl):min(ah,sl);
   if(gap)worst=s.side==1?b.o:ao;
   double mark=eq+s.side*(worst-px)*units/max(50.,worst)-2*entryFee;
   dd=max(dd,1-max(0.,mark)/max(.01,peak));
   double exit=0;
   if(gap)exit=s.side==1?b.o:ao;
   else if(hitStop)exit=s.side==1?min(sl,double(b.o)):max(sl,ao);
   else if(hitTP)exit=s.side==1?max(tp,double(b.o)):min(tp,ao);
   else if(b.m>=closeAt)exit=s.side==1?b.o:ao;
   if(exit>0){
    pnl=s.side*(exit-px)*units/exit-2*entryFee;
    eq=max(0.,eq+pnl);r.trades++;if(pnl>0){gp+=pnl;r.wins++;}else{gl-=pnl;lastLoss=b.m;}
    busyTo=b.m;closed=true;break;
   }
  }
  if(!closed)busyTo=bars.back().m;
  peak=max(peak,eq);dd=max(dd,1-eq/max(.01,peak));
  if(eq<5)break;
 }
 r.eq=eq;r.dd=100*dd;r.pf=gl>0?gp/gl:0;
 return r;
}
int main(int argc,char**argv){
 if(argc<2||!load(argv[1])){cerr<<"INPUT_M1_INVALID\n";return 2;}
 compute();
 cout<<"DATA_OK bars="<<bars.size()<<" m5="<<m5.size()<<" m15="<<m15.size()<<" h1="<<h1.size()<<" xau_signal_count="<<setups.size()<<"\n";
 uint64_t seed=0x3977474;auto rnd=[&](){seed+=0x9e3779b97f4a7c15ULL;auto x=seed;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);};auto pk=[&](int n){return int(rnd()%n);};
 vector<P> config;config.reserve(6000);
 P base;base.id=0;base.session=0;base.mode=0;base.hold=3;base.stop=3;base.tp=4;base.risk=6;base.margin=3;config.push_back(base);
 P rc=base;rc.id=1;rc.stop=2;rc.tp=3;rc.risk=5;config.push_back(rc);
 for(int i=2;i<6002;i++){P p;p.id=i;p.session=pk(4);p.mode=pk(3);p.hold=pk(4);p.cooldown=pk(4);p.stop=pk(6);p.tp=pk(7);p.risk=pk(8);p.margin=pk(4);config.push_back(p);}
 struct Row{P p;Result all,tr,va,te,fee4,fee6;};
 vector<Row> selected;selected.reserve(config.size());int tested=0,valid=0;
 for(const auto&p:config){
  Result full=replay(p,2016,2026,.02);tested++;
  if(full.trades>=15){valid++;selected.push_back(Row{p,full,Result{},Result{},Result{},Result{},Result{}});}
  if(tested%1000==0)cerr<<"SCREENED "<<tested<<"\n";
 }
 sort(selected.begin(),selected.end(),[](const Row&a,const Row&b){bool aa=a.all.dd<50,bb=b.all.dd<50;if(aa!=bb)return aa;return a.all.eq>b.all.eq;});
 // Validate top 75 under DD 50%, plus baseline/RC independently.
 const size_t stressN=min(size_t(100),selected.size());
 for(size_t i=0;i<stressN;i++){
  auto &x=selected[i];x.tr=replay(x.p,2016,2020,.02);x.va=replay(x.p,2021,2023,.02);x.te=replay(x.p,2024,2026,.02);
  x.fee4=replay(x.p,2016,2026,.04);x.fee6=replay(x.p,2016,2026,.06);
 }
 auto wr=[](ostream&o,const Result&r){o<<fixed<<setprecision(4)<<r.eq<<","<<r.dd<<","<<r.trades<<","<<r.pf<<","<<r.skips<<","<<r.signals;};
 ofstream f("xau_to_usdjpy_candidates.csv");
 f<<"id,signal_mode,session,hold_index,cooldown_days,stop_atr,TP_R,risk_fraction,margin_fraction,full_eq,full_dd,full_trades,full_pf,full_skips,full_signals,train_eq,train_dd,train_trades,train_pf,train_skips,train_signals,val_eq,val_dd,val_trades,val_pf,val_skips,val_signals,test_eq,test_dd,test_trades,test_pf,test_skips,test_signals,4pip_eq,4pip_dd,4pip_trades,4pip_pf,4pip_skips,4pip_signals,6pip_eq,6pip_dd,6pip_trades,6pip_pf,6pip_skips,6pip_signals\n";
 int pass=0;for(auto&x:selected){
  if(x.all.dd<50)pass++;
  f<<x.p.id<<","<<x.p.mode<<","<<x.p.session<<","<<x.p.hold<<","<<x.p.cooldown<<","<<atrStop[x.p.stop]<<","<<targetR[x.p.tp]<<","<<riskR[x.p.risk]<<","<<marginR[x.p.margin]<<",";
  wr(f,x.all);f<<",";wr(f,x.tr);f<<",";wr(f,x.va);f<<",";wr(f,x.te);f<<",";wr(f,x.fee4);f<<",";wr(f,x.fee6);f<<"\n";
 }
 cout<<"SCAN_DONE tested="<<tested<<" validTrades="<<valid<<" underDD50="<<pass<<" target100K="<<count_if(selected.begin(),selected.end(),[](const Row&x){return x.all.dd<50&&x.all.eq>=100000;})<<"\n";
 for(size_t i=0;i<min(size_t(10),selected.size());i++){const auto &x=selected[i];cout<<"TOP "<<i+1<<" id="<<x.p.id<<" equity="<<x.all.eq<<" dd="<<x.all.dd<<" trades="<<x.all.trades<<" train="<<x.tr.eq<<" val="<<x.va.eq<<" test="<<x.te.eq<<" fee4="<<x.fee4.eq<<" fee6="<<x.fee6.eq<<" mode="<<x.p.mode<<"\n";}
 for(int id:{0,1}){auto &p=config[id];auto r=replay(p,2016,2026,.02);cout<<"BASELINE id="<<id<<" equity="<<r.eq<<" dd="<<r.dd<<" trades="<<r.trades<<" signals="<<r.signals<<"\n";}
}
