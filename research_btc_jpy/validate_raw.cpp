#define main archived_search_main
#ifdef SESSION_VARIANT
#include "search_sessions_direct.cpp"
#else
#include "search_direct_m1.cpp"
#endif
#undef main
vector<string> parsecsv(const string&s){vector<string>v;stringstream ss(s);string z;while(getline(ss,z,','))v.push_back(z);return v;}
template<class T>int ix(const T*a,int n,double x){for(int i=0;i<n;i++)if(abs(double(a[i])-x)<1e-8)return i;throw runtime_error("GRID_VALUE_NOT_FOUND");}
int main(int argc,char**argv){try{
 if(argc<5)return 2;symbol=argv[2];btc=symbol=="BTCUSD";outdir=argv[4];load(argv[1]);for(int i=0;i<3;i++)agg[i]=aggregate(widths[i]);h4=aggregate(240);
#ifdef SESSION_VARIANT
 buildDays();
#endif
 ifstream f(argv[3]);string line;getline(f,line);auto h=parsecsv(line);map<string,int>cols;for(int i=0;i<int(h.size());i++)cols[h[i]]=i;
 ofstream o(outdir+"/RAW_TOP20_STRESS.csv");o<<setprecision(17)<<"case,"<<ph<<","<<rh<<"\n";int n=0;
 while(getline(f,line)){auto row=parsecsv(line);auto text=[&](const char*k){return row.at(cols.at(k));};auto val=[&](const char*k){return stod(text(k));};P p{};p.id=int(val("id"));p.tf=ix(widths,3,val("tf_minutes"));p.look=ix(looks,4,val("lookback"));p.threshold=int(val("threshold_index"));p.trend=int(val("trend_filter"));p.session=int(val("session_utc"));p.side=int(val("side"));p.stop=ix(stops,6,val("stop_atr"));p.tp=ix(tps,8,val("tp_R"));p.hold=ix(holds,4,val("hold_bars"));p.risk=ix(risks,8,val("risk"));p.margin=ix(margins,3,val("margin_fraction"));p.layers=int(val("add_stages"));p.be=int(val("breakeven_R"));p.family=-1;for(int k=0;k<12;k++)if(text("family")==names[k])p.family=k;if(p.family<0)throw runtime_error("FAMILY_NOT_FOUND");
 vector<pair<string,Model>> cs={{"BASE",{}},{"COST1_5",{1.5}},{"COST2",{2.}},{"DELAY_NEXT_M1",{1.,0,1}},{"NO_ADDS",{1.,0,0,1}}};if(btc)cs.push_back({"LEVERAGE2",{1.,2}});
 for(auto&[name,m]:cs){R r=simulate(p,true,parse("2019-01-01 00:00:00"),endtime,m,name=="BASE"?outdir+"/raw_"+to_string(p.id):"");if(name=="BASE"){double e=val("full_equity");if(abs(r.eq-e)>max(1e-6,abs(e)*1e-9)||r.trades!=int(val("full_trades")))throw runtime_error("FULL_UNIVERSE_RECONCILIATION_MISMATCH");}o<<name<<",";params(o,p);o<<",";result(o,r);o<<"\n";}
 for(auto seg:vector<tuple<string,int64_t,int64_t>>{{"TRAIN_2019_2022",parse("2019-01-01 00:00:00"),parse("2023-01-01 00:00:00")},{"VALID_2023_2024",parse("2023-01-01 00:00:00"),parse("2025-01-01 00:00:00")},{"TEST_2025_OCT2026",parse("2025-01-01 00:00:00"),endtime}}){auto [label,a,z]=seg;R r=simulate(p,true,a,z);o<<label<<",";params(o,p);o<<",";result(o,r);o<<"\n";}
 n++;
 }
 ofstream q(outdir+"/RAW_VALIDATION_PROOF.json");q<<"{\"parameters\":"<<n<<",\"all_baselines_reconcile\":true,\"selection\":\"Global full-period top20, DD50 top20 and train-selected top20 union; no minimum full trade-count filter\",\"model\":\"M1 OHLC not broker tick parity\"}\n";return 0;
 }catch(exception&e){cerr<<e.what()<<endl;return 1;}}
