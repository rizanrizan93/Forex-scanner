// Only parameters selected before the April–October extension may be provided.
// Reconcile March results before running any extension scenario.
#define main research_original_main
#ifdef SESSION_VARIANT
#include "search_sessions_direct.cpp"
#else
#include "search_direct_m1.cpp"
#endif
#undef main
vector<string> csvrow(const string&s){vector<string>v;stringstream ss(s);string a;while(getline(ss,a,','))v.push_back(a);return v;}
template<class T>int indexof(const T*a,int n,double x){for(int i=0;i<n;i++)if(abs(double(a[i])-x)<1e-8)return i;throw runtime_error("PARAMETER_VALUE_NOT_IN_FROZEN_GRID");}
int main(int argc,char**argv){try{
 if(argc<5)return 2;symbol=argv[2];btc=symbol=="BTCUSD";load(argv[1]);outdir=argv[4];for(int i=0;i<3;i++)agg[i]=aggregate(widths[i]);h4=aggregate(240);
#ifdef SESSION_VARIANT
 buildDays();
#endif
 ifstream f(argv[3]);string line;getline(f,line);auto h=csvrow(line);map<string,int>cols;for(int i=0;i<int(h.size());i++)cols[h[i]]=i;
 ofstream resultcsv(outdir+"/LOCKED_EXTENSION_RESULTS.csv");resultcsv<<setprecision(12)<<"case,"<<ph<<","<<rh<<"\n";
 int64_t begin=parse("2019-01-01 00:00:00"),march=parse("2026-04-01 00:00:00"),finish=parse("2026-10-16 00:00:00");int count=0;
 while(getline(f,line)){auto row=csvrow(line);auto str=[&](const char*k){return row.at(cols.at(k));};auto val=[&](const char*k){return stod(str(k));};P p{};p.id=int(val("id"));p.tf=indexof(widths,3,val("tf_minutes"));p.look=indexof(looks,4,val("lookback"));p.threshold=int(val("threshold_index"));p.trend=int(val("trend_filter"));p.session=int(val("session_utc"));p.side=int(val("side"));p.stop=indexof(stops,6,val("stop_atr"));p.tp=indexof(tps,8,val("tp_R"));p.hold=indexof(holds,4,val("hold_bars"));p.risk=indexof(risks,8,val("risk"));p.margin=indexof(margins,3,val("margin_fraction"));p.layers=int(val("add_stages"));p.be=int(val("breakeven_R"));p.family=-1;for(int k=0;k<12;k++)if(str("family")==names[k])p.family=k;if(p.family<0)throw runtime_error("FAMILY_NOT_FOUND");
  R check=simulate(p,true,begin,march);double expected=val("march_equity");if(abs(check.eq-expected)>max(1e-6,abs(expected)*1e-9)||check.trades!=int(val("march_trades")))throw runtime_error("MARCH_PREFIX_MISMATCH id="+to_string(p.id));
  resultcsv<<"MARCH_RECONCILED,";params(resultcsv,p);resultcsv<<",";result(resultcsv,check);resultcsv<<"\n";
  vector<pair<string,Model>> cases={{"EXTENDED_BASE",{}},{"EXTENDED_COST1_5",{1.5}},{"EXTENDED_COST2",{2.}},{"EXTENDED_DELAY_NEXT_M1",{1.,0,1}},{"EXTENDED_NO_ADDS",{1.,0,0,1}}};if(btc)cases.push_back({"EXTENDED_LEVERAGE2",{1.,2}});
  for(auto&[name,m]:cases){string log=name=="EXTENDED_BASE"?outdir+"/candidate_"+to_string(p.id)+"_extended":"";R r=simulate(p,true,begin,finish,m,log);resultcsv<<name<<",";params(resultcsv,p);resultcsv<<",";result(resultcsv,r);resultcsv<<"\n";}
  count++;cout<<"LOCKED_EXTENSION_COMPLETE "<<symbol<<" id="<<p.id<<endl;
 }
 ofstream proof(outdir+"/LOCKED_PARAMETER_PROOF.json");proof<<"{\"symbol\":\""<<symbol<<"\",\"selected_before_extension\":true,\"parameters\":"<<count<<",\"all_March_results_reconciled\":true,\"extension_end_UTC\":\"2026-10-15 23:59:00\",\"capital_reset_during_extension\":false,\"selection_on_extension_results\":false}\n";return 0;
 }catch(exception&e){cerr<<e.what()<<endl;return 1;}}
