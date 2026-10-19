// Independent exploratory strategy research. Never connects to a broker.
// Closed signal bars, next-bar market entry; stop-first ambiguous OHLC;
// depth-add decisions at a completed bar execute on the next bar open.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>
using namespace std;
struct B{int64_t t;double o,h,l,c,atr=0,e20=0,e80=0,rsi=50;int n=1,mi=0;};
struct S{int bar,mi,side,trend;double atr;};
struct P{int id,tf,family,look,threshold,trend,session,side,stop,tp,hold,risk,margin,layers,be;};
struct R{double eq=100,dd=0,bdd=0,gain=0,loss=0,maxerr=0;int trades=0,wins=0,adds=0,skips=0,liquidations=0;};
vector<B> minutes;array<vector<B>,4> agg;vector<B> h4;
map<int,vector<S>> templates;
string symbol,outdir;bool btc;int64_t endtime;
const int widths[]={15,60,240,1440},looks[]={8,16,32,64},holds[]={4,8,16,32};
const double stops[]={.75,1.,1.5,2.,3.,4.},tps[]={1.,1.5,2.,3.,4.,6.,8.,12.};
const double risks[]={.01,.02,.04,.06,.08,.10,.15,.20},margins[]={.1,.25,.5};
const char*names[]={"sweep_reclaim","structure_break","break_retest","trend_pullback","channel_reversion","rsi_reversal","inside_break","compression_break","displacement_follow","engulf_reversal","range_expansion_fade","ema_cross"};
int64_t parse(const string&s){tm a={};a.tm_year=stoi(s.substr(0,4))-1900;a.tm_mon=stoi(s.substr(5,2))-1;a.tm_mday=stoi(s.substr(8,2));a.tm_hour=stoi(s.substr(11,2));a.tm_min=stoi(s.substr(14,2));return timegm(&a)/60;}
string iso(int64_t t){time_t v=t*60;tm a={};gmtime_r(&v,&a);char s[24];strftime(s,sizeof s,"%Y-%m-%d %H:%M:%S",&a);return s;}
void load(const string&path){ifstream f(path);string s;getline(f,s);int64_t prev=0;
 while(getline(f,s)){stringstream ss(s);string d,o,h,l,c;if(!getline(ss,d,',')||!getline(ss,o,',')||!getline(ss,h,',')||!getline(ss,l,',')||!getline(ss,c,','))throw runtime_error("CSV");
 B b{parse(d),stod(o),stod(h),stod(l),stod(c)};if(b.t<=prev||b.l<=0||b.l>min(b.o,b.c)||b.h<max(b.o,b.c)||!isfinite(b.c))throw runtime_error("BAD_BAR");prev=b.t;b.mi=minutes.size();minutes.push_back(b);}
 if(minutes.size()<2000000)throw runtime_error("INCOMPLETE_INPUT");
 endtime=minutes.back().t+1;
}
vector<B> aggregate(int w){vector<B> v;
 for(auto&b:minutes){int64_t t=b.t-b.t%w;if(v.empty()||v.back().t!=t){B a=b;a.t=t;v.push_back(a);}else{auto&a=v.back();a.h=max(a.h,b.h);a.l=min(a.l,b.l);a.c=b.c;a.n++;}}
 double at=0,up=0,dn=0;
 for(size_t i=0;i<v.size();i++){auto&a=v[i];double pc=i?v[i-1].c:a.o,tr=max({a.h-a.l,abs(a.h-pc),abs(a.l-pc)});at=i?at+(tr-at)/14:tr;a.atr=at;a.e20=i?v[i-1].e20+2./21*(a.c-v[i-1].e20):a.c;a.e80=i?v[i-1].e80+2./81*(a.c-v[i-1].e80):a.c;up=i?up+(max(0.,a.c-pc)-up)/14:0;dn=i?dn+(max(0.,pc-a.c)-dn)/14:0;a.rsi=dn>0?100-100/(1+up/dn):100;}
 return v;}
int key(const P&p){return ((p.tf*12+p.family)*4+p.look)*3+p.threshold;}
const vector<S>& signals(const P&p){int k=key(p);auto it=templates.find(k);if(it!=templates.end())return it->second;auto&v=agg[p.tf];vector<S> ss;int look=looks[p.look],w=widths[p.tf];double thresh=.1*p.threshold;size_t ht=0;
 for(int i=max(100,look+2);i+1<int(v.size());i++){auto&a=v[i];auto&prev=v[i-1];int64_t avail=a.t+w;
  if(a.n<w*.8||v[i+1].t!=avail||a.atr<=0||minutes[a.mi].t!=a.t||minutes[v[i+1].mi].t!=avail)continue;
  while(ht+1<h4.size()&&h4[ht+1].t+240<=avail)ht++;
  if(h4[ht].t+240>avail)continue;
  int trend=h4[ht].c>h4[ht].e80&&h4[ht].e20>h4[ht].e80?1:h4[ht].c<h4[ht].e80&&h4[ht].e20<h4[ht].e80?-1:0;
  double hi=-1e90,lo=1e90;for(int j=i-look;j<i;j++){hi=max(hi,v[j].h);lo=min(lo,v[j].l);}
  double body=(a.c-a.o)/a.atr,pad=thresh*a.atr;int side=0;
  switch(p.family){
   case 0:side=a.l<lo-pad&&a.c>lo&&body>thresh?1:a.h>hi+pad&&a.c<hi&&body<-thresh?-1:0;break;
   case 1:side=a.c>hi+pad?1:a.c<lo-pad?-1:0;break;
   case 2:{double ph=-1e90,pl=1e90;for(int j=i-look-1;j<i-1;j++){ph=max(ph,v[j].h);pl=min(pl,v[j].l);}side=prev.c>ph&&a.l<=ph+pad&&a.c>ph&&body>thresh?1:prev.c<pl&&a.h>=pl-pad&&a.c<pl&&body<-thresh?-1:0;break;}
   case 3:side=a.e20>a.e80&&a.l<=a.e20-pad&&a.c>a.e20&&body>thresh?1:a.e20<a.e80&&a.h>=a.e20+pad&&a.c<a.e20&&body<-thresh?-1:0;break;
   case 4:side=a.c<lo+(hi-lo)*(.1+thresh)&&body>thresh?1:a.c>hi-(hi-lo)*(.1+thresh)&&body<-thresh?-1:0;break;
   case 5:side=prev.rsi<25+5*p.threshold&&a.rsi>prev.rsi&&body>0?1:prev.rsi>75-5*p.threshold&&a.rsi<prev.rsi&&body<0?-1:0;break;
   case 6:side=prev.h<v[i-2].h&&prev.l>v[i-2].l?(a.c>prev.h+pad?1:a.c<prev.l-pad?-1:0):0;break;
   case 7:{double sm=0;for(int j=i-4;j<i;j++)sm+=v[j].h-v[j].l;side=sm/4<prev.atr*(.6+thresh)?(a.c>hi+pad?1:a.c<lo-pad?-1:0):0;break;}
   case 8:side=body>1.2+thresh&&a.c>prev.h?1:body<-1.2-thresh&&a.c<prev.l?-1:0;break;
   case 9:side=prev.c<prev.o&&a.c>a.o&&a.o<=prev.c+pad&&a.c>=prev.o&&body>.5+thresh?1:prev.c>prev.o&&a.c<a.o&&a.o>=prev.c-pad&&a.c<=prev.o&&body<-.5-thresh?-1:0;break;
   case 10:side=a.h-a.l>a.atr*(1.5+thresh)?(a.l<lo&&a.c>a.l+.75*(a.h-a.l)?1:a.h>hi&&a.c<a.l+.25*(a.h-a.l)?-1:0):0;break;
   case 11:side=prev.e20<=prev.e80&&a.e20>a.e80&&body>thresh?1:prev.e20>=prev.e80&&a.e20<a.e80&&body<-thresh?-1:0;break;
  }
  if(side)ss.push_back({i+1,v[i+1].mi,side,trend,a.atr});
 }
 return templates.emplace(k,move(ss)).first->second;
}
bool accept(const P&p,const S&s,int64_t t){if(p.side==1&&s.side<0)return false;if(p.side==2&&s.side>0)return false;if(p.trend==1&&s.trend!=s.side)return false;if(p.trend==2&&s.trend!=-s.side)return false;int h=(t%1440)/60;return p.session==0||(p.session==1&&h>=0&&h<8)||(p.session==2&&h>=7&&h<16)||(p.session==3&&h>=12&&h<21);}
struct Model{double scale=1,lev=0;int delay=0,noadd=0;};
R simulate(const P&p,bool m1,int64_t begin,int64_t end,Model model={},const string&log=""){
 R r;double balance=100,peak=100,bpeak=100;int64_t busy=-1;
 const auto&v=m1?minutes:agg[p.tf];const double lev=model.lev>0?model.lev:(btc?10.:200.);
 const double step=btc?.01:1000.,maxqty=btc?100.:2000000.;
 const double fee=btc?.0005:.00003,carry=btc?.0003:.0001;
 const double rawSpread=btc?.0005:.01,rawSlip=btc?.0001:.001;
 ofstream ledger,curve;if(!log.empty()){ledger.open(log+"_ledger.csv");curve.open(log+"_equity.csv");ledger<<"signal_utc,entry_utc,exit_utc,side,quantity,entry_average,exit_price,gross_pnl,entry_commission,exit_commission,financing,net_pnl,balance,adds,reason\n";curve<<"timestamp,equity,balance,running_peak,drawdown_pct\n";ledger<<setprecision(12);curve<<setprecision(12);}
 auto spread=[&](double x){return btc?x*rawSpread:rawSpread;};auto slip=[&](double x){return (btc?x*rawSlip:rawSlip)*model.scale;};
 auto mark=[&](double equity,int64_t t){peak=max(peak,equity);r.dd=max(r.dd,100*(1-equity/max(peak,1e-12)));if(curve&&((t%60==0)||equity<=0))curve<<iso(t)<<","<<equity<<","<<balance<<","<<peak<<","<<100*(1-equity/max(peak,1e-12))<<"\n";};
 for(auto&s:signals(p)){int64_t st=minutes[s.mi].t;if(st<begin||st>=end||st<=busy||!accept(p,s,st))continue;
  int idx=m1?s.mi:s.bar;if(model.delay){auto it=lower_bound(v.begin()+idx,v.end(),st+model.delay,[](const B&b,int64_t t){return b.t<t;});idx=it-v.begin();if(idx>=int(v.size())||v[idx].t>=end)continue;}
  const int side=s.side;const double first=v[idx].o+(side>0?spread(v[idx].o):0)+side*slip(v[idx].o),dist=stops[p.stop]*s.atr;
  const double stop=first-side*dist,tp=first+side*dist*tps[p.tp];double sl=stop;
  if(dist<=0||stop<=0){r.skips++;continue;}
  const double frac=margins[p.margin],risk=risks[p.risk];
  auto pu=[&](double e){return btc?abs(e-stop)+2*e*fee*model.scale+slip(e):abs(e-stop)/e+2*fee*model.scale+slip(e)/e;};
  auto margin=[&](double n,double price){return btc?n*price/lev:n/lev;};
  double budget=balance*risk,initial=p.layers&&!model.noadd?.4:1.;double maxN=balance*frac/((btc?first:1.)*(1./lev+fee*model.scale));
  double n=floor(min({budget*initial/pu(first),maxN,maxqty})/step+1e-12)*step;
  if(n<step||margin(n,first)+n*(btc?first:1.)*fee*model.scale>balance*frac+1e-9){r.skips++;continue;}
  double avg=first,commission=n*(btc?first:1.)*fee*model.scale,financing=0;int adds=0,nextStage=1;bool pending=false;int64_t at=v[idx].t,lasttime=at,expires=min(end,st+int64_t(holds[p.hold])*widths[p.tf]);
  double initialBalance=balance;double xprice=0,gross=0,outfee=0;string why="END";int exitidx=idx;bool breakeven=false;
  for(int j=idx;j<int(v.size())&&v[j].t<end;j++){
   auto&b=v[j];lasttime=b.t;exitidx=j;
   if(j>idx){double dt=double(b.t-v[j-1].t)/1440.;financing+=n*(btc?b.o:1.)*carry*dt*model.scale;}
   double ask=b.o+spread(b.o),exitopen=side>0?b.o:ask;
   if(pending&&j>idx){
    double fill=b.o+(side>0?spread(b.o):0)+side*slip(b.o),equity=balance+(btc?side*(exitopen-avg)*n:side*(exitopen-avg)*n/exitopen)-commission-financing;
    double existing=n*(btc?max(0.,side*(avg-stop)):max(0.,side*(avg-stop))/fill)+commission+financing;
    double freeRisk=max(0.,equity*risk-existing),cap=btc?max(0.,equity*frac*lev/fill-n):max(0.,equity*frac*lev-n);
    double q=floor(min({freeRisk*(nextStage==1?.5:1.)/pu(fill),cap,maxqty-n})/step+1e-12)*step;
    bool crossed=side>0?(exitopen<=sl||exitopen>=tp):(exitopen>=sl||exitopen<=tp);
    if(q>=step&&!crossed&&b.t<expires){avg=(avg*n+q*fill)/(n+q);n+=q;commission+=q*(btc?fill:1.)*fee*model.scale;adds++;}
    nextStage++;pending=false;
   }
   double hi=side>0?b.h:b.h+spread(b.h),lo=side>0?b.l:b.l+spread(b.l);
   bool hs=side>0?lo<=sl:hi>=sl,ht=side>0?hi>=tp:lo<=tp;
   if(b.t>=expires){xprice=exitopen-side*slip(exitopen);why="EXPIRY";}
   else if(hs){xprice=(side>0?min(sl,exitopen):max(sl,exitopen))-side*slip(exitopen);why="SL";}
   else if(ht){xprice=(side>0?max(tp,exitopen):min(tp,exitopen))-side*slip(exitopen);why="TP";}
   // Avoid updating the equity peak with intrabar highs: ordering unknown.
   double worst=side>0?lo:hi;if(hs)worst=side>0?min(sl,exitopen):max(sl,exitopen);
   if(xprice>0)worst=side>0?min(worst,xprice):max(worst,xprice);
   double eqworst=balance+(btc?side*(worst-avg)*n:side*(worst-avg)*n/worst)-commission-financing-n*(btc?worst:1.)*fee*model.scale;
   double required=margin(n,worst);if(eqworst<=required*.5&&xprice==0){xprice=worst-side*slip(worst);why="MODEL_STOPOUT";r.liquidations++;}
   // Conservative drawdown bound: best executable excursion precedes the worst
   // when no stop is hit. When a stop is hit, STOP_FIRST suppresses later highs.
   double best=hs?exitopen:(side>0?min(hi,tp):max(lo,tp));
   double eqbest=balance+(btc?side*(best-avg)*n:side*(best-avg)*n/best)-commission-financing-n*(btc?best:1.)*fee*model.scale;
   mark(eqbest,b.t);mark(eqworst,b.t);
   if(xprice>0)break;
   double close=side>0?b.c:b.c+spread(b.c),eqclose=balance+(btc?side*(close-avg)*n:side*(close-avg)*n/close)-commission-financing-n*(btc?close:1.)*fee*model.scale;
   mark(eqclose,b.t+ (m1?1:widths[p.tf]));
   if(p.layers&&!model.noadd&&nextStage<=p.layers&&j>idx&&b.t-st<holds[p.hold]*widths[p.tf]/2){double level=first-side*dist*(nextStage==1?.25:.5);bool depth=side>0?b.c<=level:b.c+spread(b.c)>=level;if(depth)pending=true;}
   if(p.be&&!breakeven){double trigger=first+side*dist*(p.be==1?1.:2.);if(side>0?hi>=trigger:lo<=trigger){double proposed=first+side*(2*slip(first)+spread(first)+2*first*(btc?fee:0.)*model.scale);sl=side>0?max(sl,proposed):min(sl,proposed);breakeven=true;}}
  }
  if(xprice<=0){auto&b=v[exitidx];xprice=(side>0?b.c:b.c+spread(b.c))-side*slip(b.c);why="BOUNDARY_CLOSE";lasttime=b.t+(m1?1:widths[p.tf]);}
  gross=btc?side*(xprice-avg)*n:side*(xprice-avg)*n/xprice;outfee=n*(btc?xprice:1.)*fee*model.scale;
  double pnl=gross-commission-outfee-financing;balance+=pnl;r.maxerr=max(r.maxerr,abs(balance-initialBalance-pnl));
  r.trades++;r.adds+=adds;if(pnl>0){r.wins++;r.gain+=pnl;}else r.loss-=pnl;
  mark(balance,lasttime);bpeak=max(bpeak,balance);r.bdd=max(r.bdd,100*(1-balance/bpeak));busy=lasttime;
  if(ledger)ledger<<iso(st)<<","<<iso(at)<<","<<iso(lasttime)<<","<<side<<","<<n<<","<<avg<<","<<xprice<<","<<gross<<","<<commission<<","<<outfee<<","<<financing<<","<<pnl<<","<<balance<<","<<adds<<","<<why<<"\n";
  if(balance<step*(btc?minutes[min(s.mi,int(minutes.size())-1)].o:1.)/(lev*2)||balance<=0)break;
 }
 r.eq=balance;return r;
}
void params(ostream&o,const P&p){o<<p.id<<","<<widths[p.tf]<<","<<names[p.family]<<","<<looks[p.look]<<","<<p.threshold<<","<<p.trend<<","<<p.session<<","<<p.side<<","<<stops[p.stop]<<","<<tps[p.tp]<<","<<holds[p.hold]<<","<<risks[p.risk]<<","<<margins[p.margin]<<","<<p.layers<<","<<p.be;}
void result(ostream&o,const R&r){o<<r.eq<<","<<r.dd<<","<<r.bdd<<","<<(r.loss>0?r.gain/r.loss:0)<<","<<r.trades<<","<<r.wins<<","<<r.adds<<","<<r.skips<<","<<r.liquidations<<","<<r.maxerr;}
string ph="id,tf_minutes,family,lookback,threshold_index,trend_filter,session_utc,side,stop_atr,tp_R,hold_bars,risk,margin_fraction,add_stages,breakeven_R";
string rh="equity,floating_dd,balance_dd,pf,trades,wins,adds,skips,liquidations,reconciliation_error";
struct Row{P p;R full,train;};
uint64_t state=202610190602ULL;uint64_t rnd(){state+=0x9e3779b97f4a7c15ULL;auto z=state;z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;z=(z^(z>>27))*0x94d049bb133111ebULL;return z^(z>>31);}int pick(int n){return rnd()%n;}
string canonical(const P&p){ostringstream s;s<<p.tf<<","<<p.family<<","<<p.look<<","<<p.threshold<<","<<p.trend<<","<<p.session<<","<<p.side<<","<<p.stop<<","<<p.tp<<","<<p.hold<<","<<p.risk<<","<<p.margin<<","<<p.layers<<","<<p.be;return s.str();}
void fixtures(){
 auto check=[](bool x,const string&s){if(!x)throw runtime_error("FIXTURE_FAIL "+s);};
 check(min(99.,97.)==97.,"gap_stop_buy");check(max(101.,104.)==104.,"gap_stop_sell");
 check(floor(.0099/.01)*.01==0,"min_btc_step");check(floor(999./1000)*1000==0,"min_fx_units");
 double u=1000.;check(abs((151.-150.)*u/151.-6.622516556)<1e-8,"USDJPY_exit_conversion");
 check(abs(.1*(31000.-30000.)-100)<1e-10,"BTC_USD_PnL");
 ofstream f(outdir+"/FIXTURES.txt");f<<"PASS 6 arithmetic fixtures. End-to-end regression runs separately in audit_report.py. Not native platform parity.\n";
}
void engineFixtures(){
 btc=true;symbol="BTCUSD";int64_t t=parse("2019-01-01 00:00:00");P p{};p.stop=1;p.tp=0;p.hold=3;p.risk=7;p.margin=2;
 auto bars=[&](){minutes={{t,100,100.5,99.7,100},{t+1,100,102,99.8,101},{t+2,101,101.5,100.5,101},{t+3,101,101.5,100.5,101}};templates.clear();templates[key(p)]={{0,0,1,0,1.}};};
 auto run=[&](Model m=Model{}){return simulate(p,true,t,t+4,m);};
 auto ck=[](bool x,const char*s){if(!x)throw runtime_error(string("ENGINE_FIXTURE_FAIL ")+s);cout<<"PASS "<<s<<"\n";};
 bars();auto tp=run();ck(tp.trades==1&&tp.eq>100,"buy_ask_to_bid_takeprofit");
 bars();minutes[1].l=98;auto sl=run();ck(sl.trades==1&&sl.eq<100,"simultaneous_SL_TP_STOP_FIRST");
 minutes[1].o=97;minutes[1].l=96;auto gap=run();ck(gap.eq<sl.eq,"gap_stop_worse_open");
 bars();templates[key(p)][0].side=-1;minutes[1].h=102;minutes[1].l=98;auto sell=run();ck(sell.trades==1&&sell.eq<100,"sell_exit_ask_stop_first");
 bars();for(auto&b:minutes){b.o*=1000;b.h*=1000;b.l*=1000;b.c*=1000;}auto small=run({1.,2});ck(small.trades==0&&small.skips==1,"minimum_volume_margin_reject");
 bars();auto delay=run({1.,0,1});ck(delay.trades==1&&abs(delay.eq-tp.eq)>1e-6,"next_minute_delay_changes_fill");
 p.layers=2;p.risk=2;bars();minutes[1]={t+1,100,100,99.3,99.5};minutes[2]={t+2,99.5,100,99.3,99.8};minutes[3]={t+3,100,102,99.8,101};auto layered=run();auto noadds=run({1.,0,0,1});ck(layered.adds>0&&noadds.adds==0,"closed_depth_add_next_open");
 ck(layered.maxerr<1e-10&&tp.maxerr<1e-10,"cash_reconciliation");
 p.layers=0;p.risk=7;bars();templates[key(p)][0].mi=2;templates[key(p)][0].bar=2;minutes[2].h=102;auto bound=simulate(p,true,t,t+2);ck(bound.trades==0,"no_entries_beyond_end_boundary");
 cout<<"ENGINE_FIXTURES_PASS 9\n";
}
int main(int argc,char**argv){try{
 if(argc==2&&string(argv[1])=="--test"){engineFixtures();return 0;}
 if(argc<4){cerr<<"search input.csv symbol outdir [N]\n";return 2;}symbol=argv[2];btc=symbol=="BTCUSD";outdir=argv[3];int N=argc>4?stoi(argv[4]):1000000;load(argv[1]);for(int i=0;i<4;i++)agg[i]=aggregate(widths[i]);h4=agg[2];fixtures();
 const int64_t start=parse("2019-01-01 00:00:00"),split=parse("2023-01-01 00:00:00"),validend=parse("2025-01-01 00:00:00");
 vector<Row> topFull,topDD,topTrain;set<string> seen;
 auto keep=[](vector<Row>&v,Row row,auto score){v.push_back(row);sort(v.begin(),v.end(),[&](auto&a,auto&b){return score(a)>score(b);});if(v.size()>20)v.pop_back();};
 ofstream all(outdir+"/ALL_CONFIGURATIONS.csv");all<<setprecision(10)<<ph<<",full_";string hdr=rh;for(size_t pos=0;(pos=hdr.find(',',pos))!=string::npos;pos+=6)hdr.replace(pos,1,",full_");all<<hdr<<",train_equity,train_dd,train_trades\n";
 int achieved=0,achieved50=0,trainpass=0;
 for(int i=0;i<N;){P p{};p.id=i+1;p.tf=2+pick(2);p.family=pick(12);p.look=pick(4);p.threshold=pick(3);p.trend=pick(3);p.session=p.tf==3?0:pick(4);p.side=pick(3);p.stop=pick(6);p.tp=pick(8);p.hold=pick(4);p.risk=pick(8);p.margin=pick(3);p.layers=pick(3);p.be=pick(3);
  // Remove parameters not used by a family from the uniqueness claim.
  if(p.family==3||p.family==5||p.family==6||p.family==8||p.family==9||p.family==11)p.look=0;
  string k=canonical(p);if(!seen.insert(k).second)continue;i++;
  R f=simulate(p,false,start,endtime),tr=simulate(p,false,start,split);Row row{p,f,tr};
  params(all,p);all<<",";result(all,f);all<<","<<tr.eq<<","<<tr.dd<<","<<tr.trades<<"\n";
  if(f.trades>=30){keep(topFull,row,[](auto&x){return x.full.eq;});if(f.dd<50)keep(topDD,row,[](auto&x){return x.full.eq;});if(f.eq>=100000){achieved++;if(f.dd<50)achieved50++;}}
  if(tr.trades>=20&&tr.dd<50){keep(topTrain,row,[](auto&x){return x.train.eq;});trainpass++;}
  if(i%25000==0)cout<<"SCREEN "<<symbol<<" "<<i<<"/"<<N<<" target="<<achieved<<" target_dd50="<<achieved50<<" best="<<(topFull.empty()?0:topFull[0].full.eq)<<endl;
 }
 all.close();map<int,pair<Row,string>> selected;for(auto&r:topFull)selected[r.p.id]={r,"FULL_PERIOD_EXPLORATORY"};for(auto&r:topDD)selected[r.p.id]={r,"FULL_PERIOD_DD50_EXPLORATORY"};for(auto&r:topTrain){if(selected.count(r.p.id))selected[r.p.id].second+="+TRAIN_SELECTED";else selected[r.p.id]={r,"TRAIN_SELECTED"};}
 ofstream tests(outdir+"/M1_VALIDATION.csv");tests<<setprecision(12)<<"cohort,case,"<<ph<<","<<rh<<"\n";
 vector<pair<P,R>> m1rows;int seq=0;
 for(auto&[id,item]:selected){auto row=item.first;string cohort=item.second;P p=row.p;R base=simulate(p,true,start,endtime);m1rows.push_back({p,base});
  vector<tuple<string,Model,int64_t,int64_t>> cases={{"BASE",{},start,endtime},{"COST1_5",{1.5},start,endtime},{"COST2",{2.},start,endtime},{"DELAY_NEXT_M1",{1.,0,1},start,endtime},{"NO_ADDS",{1.,0,0,1},start,endtime},{"TRAIN_2019_2022",{},start,split},{"VALID_2023_2024",{},split,validend},{"TEST_2025_2026Q1",{},validend,endtime}};
  if(btc){cases.push_back({"LEVERAGE2",{1.,2},start,endtime});cases.push_back({"SPOT_FEE_PROXY",{4.,1},start,endtime});}
  for(auto&[name,model,a,z]:cases){R r=name=="BASE"?base:simulate(p,true,a,z,model);tests<<cohort<<","<<name<<",";params(tests,p);tests<<",";result(tests,r);tests<<"\n";}
  cout<<"M1_VALIDATE "<<++seq<<"/"<<selected.size()<<" id="<<id<<" eq="<<base.eq<<" dd="<<base.dd<<endl;
 }
 sort(m1rows.begin(),m1rows.end(),[](auto&a,auto&b){return a.second.eq>b.second.eq;});
 set<int> logs;for(int i=0;i<min(5,int(m1rows.size()));i++)logs.insert(m1rows[i].first.id);int ndd=0;for(auto&x:m1rows)if(x.second.dd<50&&ndd++<5)logs.insert(x.first.id);
 for(auto&x:m1rows)if(logs.count(x.first.id)){simulate(x.first,true,start,endtime,{},outdir+"/candidate_"+to_string(x.first.id));}
 ofstream summary(outdir+"/SUMMARY.json");summary<<setprecision(12)<<"{\"symbol\":\""<<symbol<<"\",\"unique_configurations\":"<<seen.size()<<",\"families\":12,\"first\":\""<<iso(minutes.front().t)<<"\",\"last\":\""<<iso(minutes.back().t)<<"\",\"m1_rows\":"<<minutes.size()<<",\"screen_target_count\":"<<achieved<<",\"screen_target_dd50_count\":"<<achieved50<<",\"M1_candidates\":"<<selected.size()<<",\"train_pass_count\":"<<trainpass<<",\"status\":\"EXPLORATORY_OHLC_NOT_TICK_OR_BROKER_VALIDATED\"}\n";
 cout<<"COMPLETE unique="<<seen.size()<<" symbol="<<symbol<<endl;
 }catch(exception&e){cerr<<e.what()<<endl;return 1;}}
