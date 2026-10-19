#include "shared_driver.hpp"
#include <unordered_set>
struct C{int id,tf,family,entry,regime,stop,tp,hold,exit;};
vector<C> configs;
map<int,vector<S>> csigs;
map<int,map<int,double>> canchors,crefs;
int findrisk(double x){for(int i=0;i<int(sizeof(risks)/sizeof(double));i++)if(abs(risks[i]-x)<1e-9)return i;throw runtime_error("RISK");}
P param(C c,double risk=.05,double margin=.75){P p{};p.tf=c.tf;p.family=c.family;p.look=(c.family==3||c.family==5||c.family==6||c.family==8||c.family==9||c.family==11)?0:1;p.threshold=1;p.stop=3;p.tp=c.tp;p.hold=c.hold;p.risk=findrisk(risk);p.margin=margin==.5?0:1;p.be=c.exit==1?1:0;return p;}
void geometry(){int id=0;for(int tf:{1,2})for(int f:{0,1,2,3,4,5,6,7,8,9,10,11})for(int en=0;en<3;en++)for(int rg=0;rg<3;rg++)for(int sl=0;sl<2;sl++)for(int tp:{0,1,3})for(int h:{1,2})for(int ex=0;ex<3;ex++)configs.push_back({++id,tf,f,en,rg,sl,tp,h,ex});}
void build(C c){if(csigs.count(c.id))return;P p=param(c);const auto& raw=rawSignals(p);const auto&v=agg[c.tf];vector<S> s;map<int,double> anchors,refs;
 for(auto a:raw){int sig=a.bar-1,last=sig;
  if(c.entry){last=sig+1;if(last+1>=int(v.size())||v[last].t!=v[sig].t+widths[c.tf]||v[last].n<widths[c.tf]*.8)continue;auto&x=v[last];auto&z=v[sig];double mid=(z.h+z.l)/2;
   bool ok=c.entry==1?(a.side>0?x.c>z.h:x.c<z.l):(a.side>0?x.l<=mid&&x.c>mid&&x.c>x.o:x.h>=mid&&x.c<mid&&x.c<x.o);if(!ok)continue;
  }
  auto&x=v[last];int next=last+1;if(next>=int(v.size())||v[next].t!=x.t+widths[c.tf]||minutes[v[next].mi].t!=v[next].t)continue;int64_t at=v[next].t;
  auto it=upper_bound(h4.begin(),h4.end(),at-240,[](int64_t t,const B&b){return t<b.t;});if(it==h4.begin())continue;int hidx=int(it-h4.begin())-1;auto&hb=h4[hidx];int tr=hb.c>hb.e80&&hb.e20>hb.e80?1:hb.c<hb.e80&&hb.e20<hb.e80?-1:0;
  auto di=upper_bound(dailyBars.begin(),dailyBars.end(),at-1440,[](int64_t t,const B&b){return t<b.t;});if(di==dailyBars.begin())continue;auto&db=*(di-1);int dt=db.c>db.e80&&db.e20>db.e80?1:db.c<db.e80&&db.e20<db.e80?-1:0;
  double travel=0;if(hidx<12)continue;for(int k=hidx-11;k<=hidx;k++)travel+=abs(h4[k].c-h4[k-1].c);double er=abs(hb.c-h4[hidx-12].c)/max(travel,1e-12);
  bool allowed=c.regime==0?tr==a.side:c.regime==1?dt==a.side&&tr!=-a.side:((c.family==0||c.family==4||c.family==5||c.family==9||c.family==10)?er<.35&&tr==0:er>=.35&&tr==a.side);
  if(!allowed||x.atr<=0||abs(x.c-x.o)>2.5*x.atr||(a.side>0?x.rsi>75:x.rsi<25))continue;
  double ratio=x.atr/max(v[max(0,last-20)].atr,1e-12);if(ratio<.6||ratio>1.8)continue;
  S z{next,v[next].mi,a.side,0,x.atr};int key=z.side>0?z.mi:-z.mi-1;
  refs[key]=x.c;if(c.stop){double ext=a.side>0?min(v[sig].l,x.l):max(v[sig].h,x.h);anchors[key]=ext+(a.side<0?ext*.0005:0)-a.side*.15*x.atr;}
  s.push_back(z);
 }
 csigs[c.id]=move(s);canchors[c.id]=move(anchors);crefs[c.id]=move(refs);
}
void activatePair(C a,C b,double risk,double weight,double margin){build(a);build(b);active.clear();stopAnchors.clear();entryRefs.clear();for(auto&s:csigs[a.id])if(s.side>0){active.push_back(s);int k=s.mi;if(canchors[a.id].count(k))stopAnchors[k]=canchors[a.id].at(k);entryRefs[k]=crefs[a.id].at(k);}for(auto&s:csigs[b.id])if(s.side<0){active.push_back(s);int k=-s.mi-1;if(canchors[b.id].count(k))stopAnchors[k]=canchors[b.id].at(k);entryRefs[k]=crefs[b.id].at(k);}
 sort(active.begin(),active.end(),[](const S&a,const S&b){if(a.mi!=b.mi)return a.mi<b.mi;return a.side>b.side;});
 // If simultaneous opposing signals occur, discard BOTH rather than favor BUY.
 vector<S> clean;for(size_t i=0;i<active.size();){size_t j=i+1;while(j<active.size()&&active[j].mi==active[i].mi)j++;if(j-i==1)clean.push_back(active[i]);i=j;}active=move(clean);
 custom=true;directional=true;longP=param(a,risk,margin);shortP=param(b,risk,margin);longExit=a.exit;shortExit=b.exit;shortRisk=risk*weight;shortMargin=margin;
}
string fields(C c){ostringstream o;o<<c.id<<","<<widths[c.tf]<<","<<names[c.family]<<","<<c.entry<<","<<c.regime<<","<<c.stop<<","<<tps[c.tp]<<","<<holds[c.hold]<<","<<c.exit;return o.str();}
void row(ostream&o,R r){result(o,r);o<<","<<r.buys<<","<<r.sells<<","<<r.buyPnl<<","<<r.sellPnl;for(int y:r.yearcounts)o<<","<<y;}
string stats=rh+",buys,sells,buy_pnl,sell_pnl,y2019,y2020,y2021,y2022,y2023,y2024,y2025,y2026";
int main(int argc,char**argv){try{string mode=argv[1];setup(argv[2]);outdir=argv[3];geometry();int64_t start=parse("2019-01-01 00:00:00"),cut=parse("2023-01-01 00:00:00"),end=parse("2025-01-01 00:00:00");
 if(mode=="screen"){
  int shard=stoi(argv[4]);ofstream o(outdir+"/SCREEN.csv");o<<setprecision(17)<<"profile,tf_minutes,family,entry,regime,stop_mode,tp_R,hold_bars,exit_mode,side,period,capital,"<<stats<<"\n";int n=0;
  for(C c:configs){if((c.id-1)%4!=shard)continue;build(c);for(int side:{1,-1}){
   activatePair(c,c,.05,1,.75);active.erase(remove_if(active.begin(),active.end(),[&](S s){return s.side!=side;}),active.end());
   for(int period=0;period<2;period++){initialCapital=10000;auto r=simulate(longP,true,period?cut:start,period?end:cut);o<<fields(c)<<","<<side<<","<<(period?"VALID":"TRAIN")<<",10000,";row(o,r);o<<"\n";}
  }if(++n%100==0)cout<<"SCREEN "<<n<<endl;if(argc>5&&n>=stoi(argv[5]))break;
  }cout<<"SCREEN_COMPLETE "<<n<<endl;
 }else if(mode=="pair"){
  ifstream f(argv[4]);string line;getline(f,line);ofstream o(outdir+"/PAIRS.csv");o<<setprecision(17)<<"id,buy_profile,sell_profile,risk,sell_weight,margin,period,capital,"<<stats<<"\n";int n=0;
  while(getline(f,line)){auto r=split(line);int id=stoi(r[0]),a=stoi(r[1]),b=stoi(r[2]);double risk=stod(r[3]),w=stod(r[4]),m=stod(r[5]);activatePair(configs.at(a-1),configs.at(b-1),risk,w,m);
   for(int period=0;period<2;period++){initialCapital=period?10000:100;auto z=simulate(longP,true,period?cut:start,period?end:cut);o<<id<<","<<a<<","<<b<<","<<risk<<","<<w<<","<<m<<","<<(period?"VALID":"TRAIN")<<","<<initialCapital<<",";row(o,z);o<<"\n";}
   if(++n%100==0)cout<<"PAIR "<<n<<endl;
  }cout<<"PAIR_COMPLETE "<<n<<endl;
 }else if(mode=="audit"){
  ifstream f(argv[4]);string line;getline(f,line);ofstream o(outdir+"/AUDIT.csv");o<<setprecision(17)<<"id,buy_profile,sell_profile,risk,sell_weight,margin,case,"<<stats<<"\n";
  while(getline(f,line)){auto r=split(line);int id=stoi(r[0]),a=stoi(r[1]),b=stoi(r[2]);double risk=stod(r[3]),w=stod(r[4]),m=stod(r[5]);activatePair(configs.at(a-1),configs.at(b-1),risk,w,m);
   for(auto spec:vector<pair<string,Model>>{{"BASE",{}},{"COST1_5",{1.5}},{"COST2",{2}},{"DELAY_NEXT_M1",{1,0,1}},{"LEVERAGE2",{1,2}},{"LEVERAGE5",{1,5}}}){
    auto z=simulate(longP,true,start,endtime,spec.second,outdir+"/candidate_"+to_string(id)+"_"+spec.first);o<<id<<","<<a<<","<<b<<","<<risk<<","<<w<<","<<m<<","<<spec.first<<",";row(o,z);o<<"\n";
   }
  }
 }else if(mode=="catalog"){
  ofstream o(outdir+"/CATALOG.csv");o<<"profile,tf_minutes,family,entry,regime,stop_mode,tp_R,hold_bars,exit_mode\n";for(C c:configs)o<<fields(c)<<"\n";cout<<"CATALOG "<<configs.size()<<endl;
 }else throw runtime_error("MODE");
}catch(exception&e){cerr<<e.what()<<endl;return 1;}}
