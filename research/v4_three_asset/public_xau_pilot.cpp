#define main v4_main_unused
#include "search.cpp"
#undef main
int main(int argc,char**argv){
 if(argc!=3)return 2;
 fs::path root=argv[1];int year=stoi(argv[2])-2019;if(year<0||year>6)return 2;
 assets[1].t=readbin<int64_t>(root/"data/1_times.i64");
 assets[1].b=readbin<Bar>(root/"data/1_m1.f64");
 if(assets[1].t.size()!=assets[1].b.size()||assets[1].t.empty())return 3;
 ofstream f(root/"results.csv");f<<setprecision(12);
 f<<"year,base,sl,tp,hold,trend,dir,seedrisk,growthrisk,daily,loss,win,cost,end,dd,entries,wins,gaps,goal125,goal250,goal1000\n";
 uint64_t n=0;
 for(int b=0;b<36;b++){
  auto cs=readbin<Candidate>(root/"data"/("base"+to_string(b)+"_symbol1.bin"));
  for(int sl:{1,2})for(int tp:{1,2,3})for(int hold:{2,3})for(int cost:{1,2}){
   vector<Event> events;
   for(auto &c:cs){if(c.symbol!=1||c.idx<0||size_t(c.idx)>=assets[1].t.size()||assets[1].t[c.idx]!=c.t)throw runtime_error("bad tape");auto e=outcome(c,sl,tp,hold,cost);if(e.risk>0)events.push_back(e);}
   for(int trend:{1,2})for(int dir=0;dir<3;dir++){
    vector<Event> ev;for(auto&e:events)if(match(e,{trend,0,2,dir}))ev.push_back(e);
    for(int sr:{1,2}){Config c{sr,2,1,3,2};auto a=wallet(ev,year,c);
     f<<year+2019<<','<<b<<','<<STOP[sl]<<','<<TP[tp]<<','<<HOLD[hold]<<','<<trend<<','<<dir<<','<<SR[sr]<<','<<GR[2]<<",2,60,5,"<<cost<<','<<a.cash<<','<<a.dd<<','<<a.n<<','<<a.wins<<','<<a.gaps<<','<<a.g125<<','<<a.g250<<','<<a.g1000<<'\n';n++;
    }
   }
  }
 }
 f.flush();if(!f||n!=10368)throw runtime_error("incomplete pilot");cout<<"PUBLIC_XAU_PILOT_COMPLETE year="<<year+2019<<" actual_wallet_cases="<<n<<" native_replays=0\n";
}
