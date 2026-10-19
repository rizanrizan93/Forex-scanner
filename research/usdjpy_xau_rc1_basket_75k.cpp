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

// Research-only XAU-style staged-basket experiment, not a bit-identical RC1 cBot port.
// H1/M15 + M5 lookahead-free signals are precomputed by compute().
// Commission 0.03 USD per 0.01 lot per side; spread unit JPY, USDJPY pip=0.01 JPY.
struct Model{P p;int stages,ttl,entryShare,ddThrottle,addConfirm,be;};
static const double initialShare[]={.3,.4,.5,.6,.7,1.0};
static const int ttl[]={45,90,180};
static const double riskCap[]={.025,.04,.06,.08,.10,.121,.125,.15,.20};
static const int maxHold[]={120,240,360,480};
static const double costs[]={.02,.04,.06};
struct ExitResult{double eq=100,dd=0,gain=0,loss=0;int trades=0,skips=0,adds=0,winning=0,eligible=0;};
static vector<uint8_t> confirmed; // bit0 BUY, bit1 SELL when last *completed* M5 candle confirms.
void preConfirm(){
 confirmed.assign(bars.size(),0);
 size_t k=0;
 for(size_t i=0;i<bars.size();i++){
  int64_t time=bars[i].m;
  while(k+1<m5.size()&&m5[k+1].t+5<=time)k++;
  if(k==0||m5[k].t+5>time)continue;
  const auto&a=m5[k];const auto&b=m5[k-1];
  if(a.n!=5||time-(a.t+5)>5)continue;
  if(a.c>a.o&&a.c>b.h)confirmed[i]|=1;
  if(a.c<a.o&&a.c<b.l)confirmed[i]|=2;
 }
}
ExitResult simulate(const Model &model,int y0,int y1,double spread){
 ExitResult r;
 const P&p=model.p;
 double balance=100,peak=100,dd=0;
 int64_t busy=-1,prevLoss=-99999999;
 // Iterate causally over independent entry episodes, never forcing parameter-selected favorable intrabar order.
 for(const auto&s:setups){
  if(s.year<y0||s.year>y1||!accept(p,s))continue;
  const int64_t signalMin=bars[s.idx].m;
  if(signalMin<=busy||signalMin-prevLoss<int64_t(p.cooldown)*1440)continue;
  r.eligible++;
  const int side=s.side;
  const double quote=bars[s.idx].o;
  const double entry=quote+(side==1?spread:0.);
  const double dist=max(atrStop[p.stop]*s.atr,side*(entry-s.anchor));
  if(dist<.025||dist>3.){r.skips++;continue;}
  const double target=entry+side*dist*targetR[p.tp];
  double sl=entry-side*dist;
  double currentRisk=riskCap[p.risk];double draw=1-balance/max(peak,1.);
  if(model.ddThrottle>=1&&draw>=.15)currentRisk*=.65;
  if(model.ddThrottle>=2&&draw>=.30)currentRisk*=.5;
  if(model.ddThrottle>=3&&draw>=.40)currentRisk*=.5;
  const double riskBudget=balance*currentRisk;
  const double marginCapacity=balance*marginR[p.margin]*200.; // base USD exposure
  const double maxUnits=floor(marginCapacity/1000.)*1000.;
  // Budget SL distance in USD per base unit; first stage must leave remaining risk for adds.
  const double initialBudget=riskBudget*initialShare[model.entryShare];
  const double riskUnit=(dist+spread*.05)/entry+0.00006; // 0.06USD / 1000 units both sides -> 0.00006 USD/unit
  int n=int(floor(min(maxUnits,initialBudget/riskUnit)/1000.))*1000;
  if(n<1000){r.skips++;continue;}
  const double initEntry=entry;
  double avg=entry;
  double commission=n/1000.*.03;
  double allocatedRisk=n*riskUnit;
  int lastIdx=s.idx;
  bool stageOne=false,stageTwo=false,beChanged=false,closed=false;
  const int64_t at=signalMin,cutoff=at-at%1440+1199; // closes at 19:59 UTC (no future bar)
  int64_t expires=at+maxHold[p.hold];
  if(p.session!=3)expires=min(expires,cutoff);
  if(expires<at)expires=at;
  for(size_t j=s.idx;j<bars.size();j++){
   const auto&b=bars[j];
   if(utcYear(b.m)>y1)break;
   const bool gap=j>size_t(s.idx)&&(b.m-bars[j-1].m>5);
   const double openAsk=b.o+spread,highAsk=b.h+spread,lowAsk=b.l+spread;
   const bool hs=side==1?b.l<=sl:highAsk>=sl;
   const bool ht=side==1?b.h>=target:lowAsk<=target;
   const double adverse=gap?(side==1?b.o:openAsk):(side==1?max(double(b.l),sl):min(highAsk,sl));
   // Conservative (but not tick-accurate) floating mark at min adverse bar excursion.
   const double equityWorst=max(0.,balance+side*(adverse-avg)*n/max(60.,adverse)-commission-n/1000.*.03);
   dd=max(dd,1-equityWorst/max(peak,1e-8));
   double exit=0;
   if(gap)exit=side==1?b.o:openAsk;
   else if(hs)exit=side==1?min(double(b.o),sl):max(openAsk,sl);
   else if(ht)exit=side==1?max(double(b.o),target):min(openAsk,target);
   else if(b.m>=expires)exit=side==1?b.o:openAsk;
   if(exit>0){
     double pnl=side*(exit-avg)*n/exit-commission-n/1000.*.03;
     balance=max(0.,balance+pnl);
     if(pnl>0){r.gain+=pnl;r.winning++;}else{r.loss-=pnl;prevLoss=b.m;}
     r.trades++;busy=b.m;closed=true;break;
   }
   if(model.stages>1&&j>size_t(s.idx)&&b.m-at<=ttl[model.ttl]){
     const double touch1=initEntry-side*.2*dist,touch2=initEntry-side*.4*dist;
     for(int stage=1;stage<model.stages;stage++){
       bool &done=(stage==1?stageOne:stageTwo);
       if(done)continue;
       double depthPrice=(stage==1?touch1:touch2);
       bool touched=side==1?b.l<=depthPrice:highAsk>=depthPrice;
       if(!touched)continue;
       if(model.addConfirm>0&&!(confirmed[j]&(side==1?1:2)))continue;
       // Fill at the level or the worse tradable open. No adds on stop/TP minute.
       const double fill=side==1?min(depthPrice+spread,openAsk):max(depthPrice,double(b.o));
       const double rpu=(max(0.,side*(fill-sl)))/fill+.00006;
       const double remainingBudget=max(0.,riskBudget-allocatedRisk);
       double share=(model.stages==2)?1.:(stage==1?.52:1.);
       const double budget=remainingBudget*share;
       const int q=int(floor(min(max(0.,maxUnits-n),budget/max(1e-9,rpu))/1000.))*1000;
       if(q>=1000){
         avg=(n*avg+q*fill)/(n+q);
         n+=q;commission+=q/1000.*.03;allocatedRisk+=q*rpu;r.adds++;
       }
       done=true;
     }
   }
   // Break-even applies only after the trigger minute; no same-minute favorable-before-adverse assumption.
   if(model.be&&!beChanged){
    const bool reached=side==1?b.h>=initEntry+2*dist:lowAsk<=initEntry-2*dist;
    if(reached){double ns=initEntry+side*(spread+.001);sl=side==1?max(sl,ns):min(sl,ns);beChanged=true;}
   }
   lastIdx=int(j);
   if(j>size_t(s.idx)+1800)break;
  }
  if(!closed){busy=bars.back().m;}
  peak=max(peak,balance);
  dd=max(dd,1-balance/max(peak,1e-8));
  if(balance<5.)break;
 }
 r.eq=balance;r.dd=100*dd;
 return r;
}
struct Row{Model model;ExitResult full,train,valid,hold,wide,doubled;bool checked=false;};
void writeRes(ostream&os,const ExitResult&r){os<<fixed<<setprecision(6)<<r.eq<<","<<r.dd<<","<<r.trades<<","<<r.skips<<","<<r.adds<<","<<r.winning<<","<<r.eligible;}
void writeP(ostream&os,const Model&x){const P&p=x.p;os<<p.id<<","<<p.session<<","<<p.mode<<","<<p.hold<<","<<p.cooldown<<","<<atrStop[p.stop]<<","<<targetR[p.tp]<<","<<riskCap[p.risk]<<","<<marginR[p.margin]<<","<<x.stages<<","<<initialShare[x.entryShare]<<","<<ttl[x.ttl]<<","<<x.ddThrottle<<","<<x.addConfirm<<","<<x.be;}
int main(int argc,char**argv){
 if(argc<2||!load(argv[1])){cerr<<"M1_DATA_FAILED\n";return 2;}
 compute();preConfirm();
 cout<<"M1_DATA_OK count="<<bars.size()<<" m5="<<m5.size()<<" m15="<<m15.size()<<" h1="<<h1.size()<<" XAU_signals="<<setups.size()<<"\n";
 uint64_t seed=202610191236ULL;auto rnd=[&](){seed+=0x9e3779b97f4a7c15ULL;auto x=seed;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);};auto pk=[&](int n){return int(rnd()%n);};
 constexpr int N=75000;
 vector<Row> rows;rows.reserve(N);
 for(int i=0;i<N;i++){
   Model m{};
   m.p.id=i+1;m.p.session=pk(4);m.p.mode=pk(3);m.p.hold=pk(4);m.p.cooldown=pk(4);
   m.p.stop=pk(6);m.p.tp=pk(7);m.p.risk=pk(9);m.p.margin=pk(4);
   m.stages=1+pk(3);m.entryShare=pk(6);m.ttl=pk(3);m.ddThrottle=pk(4);m.addConfirm=pk(2);m.be=pk(2);
   if(m.stages==1){m.entryShare=5;m.ttl=0;m.addConfirm=0;}
   ExitResult r=simulate(m,2016,2026,.02);
   if(r.trades>=12)rows.push_back(Row{m,r});
   if((i+1)%10000==0)cerr<<"SCREENED "<<i+1<<"\n";
 }
 sort(rows.begin(),rows.end(),[](const Row&a,const Row&b){bool aa=a.full.dd<50,bb=b.full.dd<50;if(aa!=bb)return aa;return a.full.eq>b.full.eq;});
 int ddbound=0,success=0;for(auto&x:rows){if(x.full.dd<50){ddbound++;if(x.full.eq>=100000)success++;}}
 const int validateN=min(100,int(rows.size()));
 for(int i=0;i<validateN;i++){auto&x=rows[i];x.train=simulate(x.model,2016,2020,.02);x.valid=simulate(x.model,2021,2023,.02);x.hold=simulate(x.model,2024,2026,.02);x.wide=simulate(x.model,2016,2026,.04);x.doubled=simulate(x.model,2016,2026,.06);x.checked=true;}
 ofstream f("xau_basket_usdjpy_75k_screen.csv");
 f<<"id,session,mode,hold,cooldown,stop_atr,tp_R,risk,margin,stages,initial_share,add_ttl,dd_throttle,confirm_add,BE2R,full_eq,full_dd,full_trades,full_skips,full_adds,full_wins,full_eligible,train_eq,train_dd,train_trades,train_skips,train_adds,train_wins,train_eligible,val_eq,val_dd,val_trades,val_skips,val_adds,val_wins,val_eligible,oos_eq,oos_dd,oos_trades,oos_skips,oos_adds,oos_wins,oos_eligible,cost4_eq,cost4_dd,cost4_trades,cost4_skips,cost4_adds,cost4_wins,cost4_eligible,cost6_eq,cost6_dd,cost6_trades,cost6_skips,cost6_adds,cost6_wins,cost6_eligible\n";
 for(auto&x:rows){writeP(f,x.model);f<<",";writeRes(f,x.full);f<<",";writeRes(f,x.train);f<<",";writeRes(f,x.valid);f<<",";writeRes(f,x.hold);f<<",";writeRes(f,x.wide);f<<",";writeRes(f,x.doubled);f<<"\n";}
 cout<<"COMPLETE tested="<<N<<" eligible="<<rows.size()<<" dd_under50="<<ddbound<<" target100k="<<success<<"\n";
 for(int i=0;i<min(12,validateN);i++){auto&x=rows[i];cout<<"TOP "<<i+1<<" id="<<x.model.p.id<<" eq="<<x.full.eq<<" dd="<<x.full.dd<<" trades="<<x.full.trades<<" adds="<<x.full.adds<<" train="<<x.train.eq<<" valid="<<x.valid.eq<<" holdout="<<x.hold.eq<<" wide="<<x.wide.eq<<" double="<<x.doubled.eq<<"\n";}
}