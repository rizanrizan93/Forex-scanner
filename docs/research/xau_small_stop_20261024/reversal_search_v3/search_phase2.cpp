#include <bits/stdc++.h>
using namespace std;
struct Tree{int n;bool mx;vector<double>a;Tree(const vector<double>&v,bool m):mx(m){n=1;while(n<(int)v.size())n*=2;a.assign(2*n,m?-1e100:1e100);copy(v.begin(),v.end(),a.begin()+n);for(int i=n-1;i;i--)a[i]=m?max(a[2*i],a[2*i+1]):min(a[2*i],a[2*i+1]);}int hit(int l,int r,double x,int p=1,int a0=0,int b=-1)const{if(b<0)b=n;if(r<=a0||b<=l||(mx?a[p]<x:a[p]>x))return -1;if(b-a0==1)return a0;int c=(a0+b)/2,j=hit(l,r,x,2*p,a0,c);return j<0?hit(l,r,x,2*p+1,c,b):j;}};
struct Zone{int id,f,i,side,h1,h4;long long ts;double lo,hi,atr,slope,eff,dist,strength,compression;};
struct Trade{int zi,en,ex,reason;double e,sl,tp,r,age,risk;unsigned mask;};
struct Stats{int n=0,w=0,tp=0;double pos=0,neg=0,sum=0,risk=0,eq=1,peak=1,dd=0;void add(const Trade&v){n++;w+=v.r>0;tp+=v.reason==2;sum+=v.r;risk+=v.risk;if(v.r>0)pos+=v.r;else neg-=v.r;eq*=max(.00001,1+.005*v.r);peak=max(peak,eq);dd=max(dd,1-eq/peak);}double pf()const{return neg>0?pos/neg:0;}};
template<class T>void readvec(ifstream&f,vector<T>&v,int n){v.resize(n);f.read((char*)v.data(),n*sizeof(T));}
int main(int argc,char**argv){string dir="reversal_search_v2";ifstream f(dir+"/prices.bin",ios::binary);long long nn;f.read((char*)&nn,8);int n=nn;vector<long long>tt;vector<double>op,hi,lo,cl,sp,datr;vector<unsigned char>valid;vector<unsigned>masks;readvec(f,tt,n);readvec(f,op,n);readvec(f,hi,n);readvec(f,lo,n);readvec(f,cl,n);readvec(f,sp,n);readvec(f,valid,n);
 auto idx=[&](long long x){return int(lower_bound(tt.begin(),tt.end(),x)-tt.begin());};vector<int>yr(n),hr(n),nextgap(n,n);for(int i=n-1;i>=0;i--){time_t ts=tt[i];tm*tv=gmtime(&ts);yr[i]=tv->tm_year+1900;hr[i]=tv->tm_hour;if(i<n-1)nextgap[i]=(tt[i+1]-tt[i]>72*3600?i+1:nextgap[i+1]);}
 ifstream zf(dir+"/zones.csv");string line;getline(zf,line);vector<Zone>zones;int nf=0;while(getline(zf,line)){replace(line.begin(),line.end(),',',' ');istringstream s(line);Zone z;s>>z.id>>z.f>>z.i>>z.ts>>z.side>>z.lo>>z.hi>>z.atr>>z.h1>>z.h4>>z.slope>>z.eff>>z.dist>>z.strength>>z.compression;if(!s.fail()){zones.push_back(z);nf=max(nf,z.f+1);}}
 ifstream mf(dir+"/../reversal_search_v3/masks_phase2.bin",ios::binary),df(dir+"/daily_atr.bin",ios::binary);readvec(mf,masks,zones.size());readvec(df,datr,zones.size());if(!mf||!df)return 2;
 vector<vector<int>>families(nf);for(int i=0;i<(int)zones.size();i++)families[zones[i].f].push_back(i);
 bool replay=argc>1&&string(argv[1])=="replay";vector<double>cfg;if(replay){for(int i=2;i<argc;i++)cfg.push_back(atof(argv[i]));if(cfg.size()!=10){cerr<<"replay family frac buffer target profile ttl session cost hold direction\n";return 3;}}
 ofstream out(dir+(replay?"/../reversal_search_v3/phase2_replay_ledger.csv":"/../reversal_search_v3/phase2_search_results.csv"));out<<setprecision(10);
 if(replay)out<<"zone_id,family,created_i,entry_i,exit_i,side,entry,sl,tp,net_R,reason,year,age_hours,risk\n";
 else{out<<"family,frac,buffer,target,profile,ttl,session,cost,hold,direction";for(string p:{"train","review","q1","all"})out<<','<<p<<"_n,"<<p<<"_win,"<<p<<"_tp,"<<p<<"_pos,"<<p<<"_neg,"<<p<<"_R,"<<p<<"_risk,"<<p<<"_dd";out<<",censored";for(int y=2019;y<=2026;y++)out<<",n"<<y<<",r"<<y;out<<'\n';}
 long long count=0;Tree bh(hi,true),bl(lo,false);
 for(int cost:{1,2}){if(replay&&cost!=(int)cfg[7])continue;vector<double>ah(n),al(n);for(int i=0;i<n;i++){ah[i]=hi[i]+cost*sp[i];al[i]=lo[i]+cost*sp[i];}Tree askh(ah,true),askl(al,false);
 for(int fam=0;fam<nf;fam++){if(replay&&fam!=(int)cfg[0])continue;
 for(double frac:{0.,.5,.8,1.}){if(replay&&abs(frac-cfg[1])>1e-8)continue;
 struct Fill{int zi,en;double e,age;};vector<Fill>fills;
 for(int zi:families[fam]){auto&z=zones[zi];double e=z.side==1?z.hi-frac*(z.hi-z.lo):z.lo+frac*(z.hi-z.lo);if((z.side==1&&e>=op[z.i]+cost*sp[z.i])||(z.side==-1&&e<=op[z.i]))continue;int end=idx(z.ts+24*3600);int en=(z.side==1?askl:bh).hit(z.i,end,e);if(en<0||en>=n||!valid[en]||nextgap[z.i]<=en)continue;fills.push_back({zi,en,e,double(tt[en]-z.ts)/3600});}
 sort(fills.begin(),fills.end(),[](auto&a,auto&b){return a.en==b.en?a.zi<b.zi:a.en<b.en;});
 for(double buffer:{-.2,-.3,-.4,-.5,-.6,-.8})for(double target:{25.})for(int hold:{72,240}){
 if(replay&&(abs(buffer-cfg[2])>1e-8||abs(target-cfg[3])>1e-8||hold!=(int)cfg[8]))continue;
 vector<Trade>tr;tr.reserve(fills.size());
 for(auto&v:fills){auto&z=zones[v.zi];double sl=v.e-z.side*target*abs(buffer),risk=z.side*(v.e-sl);if(z.side*(sl-(z.side==1?z.lo:z.hi))>-.05*z.atr)continue;if(risk<max(.25*z.atr,3*(cost*sp[z.i]+.17*cost))||risk>2*target)continue;double tp=v.e+z.side*target;long long deadline=tt[v.en]+(long long)hold*3600;int end=min(n-1,idx(deadline));int si=(z.side==1?bl:askh).hit(v.en,end+1,sl),ti=(z.side==1?bh:askl).hit(v.en+1,end+1,tp);int ex=end,reason=3;double price;
 if(si>=0&&(ti<0||si<=ti)){ex=si;reason=1;price=z.side==1?min(sl,op[ex]):max(sl,op[ex]+cost*sp[ex]);}else if(ti>=0){ex=ti;reason=2;price=tp;}else price=op[ex]+(z.side==-1?cost*sp[ex]:0);
 if(nextgap[v.en]<=ex){ex=nextgap[v.en];reason=4;}else if(reason==3&&tt[end]<deadline)reason=4;
 double r=reason==4?0:(z.side*(price-v.e)-.17*cost-.1*double(tt[ex]-tt[v.en])/86400)/risk;
 unsigned mask=masks[v.zi];if(!isfinite(datr[v.zi])||datr[v.zi]<target)mask&=~(1u<<16);if(!isfinite(datr[v.zi])||datr[v.zi]<.5*target)mask&=~((1u<<17)|(1u<<18));tr.push_back({v.zi,v.en,ex,reason,v.e,sl,tp,r,v.age,risk,mask});
 }
 for(int p=19;p<32;p++)for(int ttl:{4,24})for(int sess:{0,3})for(int direction:{1,-1}){if(replay&&(p!=(int)cfg[4]||ttl!=(int)cfg[5]||sess!=(int)cfg[6]||direction!=(int)cfg[9]))continue;Stats train,review,q1,all,annual[8];int busy=-1,cens=0;
 for(auto&v:tr){if((direction&&zones[v.zi].side!=direction)||!(v.mask&(1u<<p))||v.age>ttl||(sess==3&&(hr[v.en]<7||hr[v.en]>=17))||v.en<=busy)continue;busy=v.ex;if(v.reason==4){cens++;continue;}
 if(replay){auto&z=zones[v.zi];out<<z.id<<','<<fam<<','<<z.i<<','<<v.en<<','<<v.ex<<','<<z.side<<','<<v.e<<','<<v.sl<<','<<v.tp<<','<<v.r<<','<<v.reason<<','<<yr[v.en]<<','<<v.age<<','<<v.risk<<'\n';continue;}
 all.add(v);if(tt[v.en]<=1672531200LL-(long long)hold*3600)train.add(v);else if(tt[v.en]>=1672531200LL&&tt[v.en]<=1767225600LL-(long long)hold*3600)review.add(v);if(yr[v.en]==2026)q1.add(v);int y=yr[v.en]-2019;if(y>=0&&y<8)annual[y].add(v);
 }
 if(!replay){out<<fam<<','<<frac<<','<<buffer<<','<<target<<','<<p<<','<<ttl<<','<<sess<<','<<cost<<','<<hold<<','<<direction;for(auto&st:{train,review,q1,all})out<<','<<st.n<<','<<st.w<<','<<st.tp<<','<<st.pos<<','<<st.neg<<','<<st.sum<<','<<st.risk<<','<<st.dd*100;out<<','<<cens;for(auto&st:annual)out<<','<<st.n<<','<<st.sum;out<<'\n';count++;}
 }
 }
 }
 cerr<<"cost="<<cost<<" family="<<fam<<" configs="<<count<<'\n';
 }
 }
 cerr<<"finished configs="<<count<<'\n';
}
