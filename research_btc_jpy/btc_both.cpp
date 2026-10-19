#include "shared_driver.hpp"
template<class T,size_t N>int ix(const T(&v)[N],double x){for(int i=0;i<int(N);i++)if(abs(v[i]-x)<1e-9)return i;throw runtime_error("PARAM_VALUE_NOT_FOUND "+to_string(x));}
vector<string> hdr;map<string,int>ci;
double val(const vector<string>&r,string k){return stod(r.at(ci.at(k)));}
F readF(const vector<string>&r){F f{};f.id=val(r,"seed_id");P&p=f.p;p.id=val(r,"id");p.tf=ix(widths,val(r,"tf_minutes"));string fam=r.at(ci.at("family"));p.family=find(names,names+12,fam)-names;p.look=ix(looks,val(r,"lookback"));p.threshold=val(r,"threshold_index");p.trend=val(r,"trend_filter");p.session=val(r,"session_utc");p.side=0;p.stop=ix(stops,val(r,"stop_atr"));p.tp=ix(tps,val(r,"tp_R"));p.hold=ix(holds,val(r,"hold_bars"));p.risk=ix(risks,val(r,"risk"));p.margin=ix(margins,val(r,"margin_fraction"));p.layers=val(r,"add_stages");p.be=val(r,"breakeven_R");f.vol=val(r,"vol_gate");f.rsi=val(r,"rsi_gate");f.week=val(r,"weekday_gate");f.loc=val(r,"close_location_gate");f.daily=val(r,"daily_trend_gate");return f;}
string ext="buy_baskets,sell_baskets,buy_net_pnl,sell_net_pnl";
void extra(ostream&o,const R&r){o<<r.buys<<","<<r.sells<<","<<r.buyPnl<<","<<r.sellPnl;}
void parity(){
 custom=false;shortRisk=shortMargin=-1;
 P p{};p.id=692365;p.tf=2;p.family=8;p.look=0;p.threshold=2;p.trend=1;p.session=1;p.side=1;p.stop=4;p.tp=6;p.hold=3;p.risk=ix(risks,.4);p.margin=ix(margins,.95);p.layers=2;p.be=2;
 auto r=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
 if(abs(r.eq-1005025.5238208736)>1e-5||abs(r.dd-67.92092400829017)>1e-8||r.trades!=63)throw runtime_error("OLD_BASELINE_PARITY_FAIL");
 p.risk=ix(risks,.21);p.layers=0;p.be=0;p.tp=ix(tps,12);
 r=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
 if(abs(r.eq-955554.2421913373)>1e-5||abs(r.dd-59.92601001623199)>1e-8||r.buys!=63||r.sells!=0)throw runtime_error("955K_PARITY_FAIL");
 F f{};f.p=p;activate(f);auto z=simulate(p,true,parse("2019-01-01 00:00:00"),endtime);
 if(r.eq!=z.eq||r.dd!=z.dd)throw runtime_error("GATE_ZERO_PARITY_FAIL");
 cout<<"PARITY_PASS original692365 and955k and zero-gates"<<endl;custom=false;
}
int main(int argc,char**argv){try{
 if(argc==2&&string(argv[1])=="--test"){engineFixtures();return 0;}
 if(argc<5)return 2;string mode=argv[1];outdir=argv[3];setup(argv[2]);parity();
 ifstream f(argv[4]);string line;getline(f,line);line.erase(remove(line.begin(),line.end(),char(13)),line.end());hdr=split(line);for(int k=0;k<int(hdr.size());k++)ci[hdr[k]]=k;
 ofstream out(outdir+"/RESULTS.csv");out<<setprecision(17)<<"case,"<<line<<","<<rh<<","<<ext<<"\n";
 int count=0,shard=argc>5?stoi(argv[5]):0;
 while(getline(f,line)){
  line.erase(remove(line.begin(),line.end(),char(13)),line.end());auto row=split(line);int id=val(row,"id");if(mode=="search"&&(id-1)%4!=shard)continue;
  auto def=readF(row);P p=def.p;activate(def);shortRisk=val(row,"short_risk");shortMargin=val(row,"short_margin");
  vector<pair<string,Model>> cases={{"BASE",{}}};
  if(mode=="audit")cases={{"BASE",{}},{"COST1_5",{1.5}},{"COST2",{2}},{"DELAY_NEXT_M1",{1.,0,1}},{"LEVERAGE2",{1.,2}},{"LEVERAGE5",{1.,5}}};
  for(auto&[name,m]:cases){
   string log=mode=="audit"?outdir+"/candidate_"+to_string(id)+"_"+name:"";
   auto r=simulate(p,true,parse("2019-01-01 00:00:00"),endtime,m,log);
   out<<name<<","<<line<<",";result(out,r);out<<",";extra(out,r);out<<"\n";
  }
  count++;if(count%1000==0)cout<<"PROGRESS "<<count<<" shard="<<shard<<endl;
  if(mode=="smoke"&&count>=2)break;
 }
 cout<<"COMPLETE "<<count<<" shard="<<shard<<endl;
}catch(exception&e){cerr<<e.what()<<endl;return 1;}}
