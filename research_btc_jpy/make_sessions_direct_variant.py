from pathlib import Path
root=Path(__file__).resolve().parent
s=(root/'search_sessions.cpp').read_text()
s=s.replace('load(argv[1]);for(int i=0;i<3;i++)','int shard=argc>5?stoi(argv[5]):0, nshards=argc>6?stoi(argv[6]):1;int evaluated=0;load(argv[1]);for(int i=0;i<3;i++)')
s=s.replace('R f=simulate(p,false,start,endtime),tr=simulate(p,false,start,split);','if((i-1)%nshards!=shard)continue;\n  evaluated++;\n  R f=simulate(p,true,start,endtime),tr=simulate(p,true,start,split);')
s=s.replace('if(i%25000==0)', 'if(evaluated%10000==0)')
s=s.replace('"SCREEN "<<symbol<<" "<<i<<"/"<<N','"DIRECT_M1 "<<symbol<<" evaluated="<<evaluated<<" stream="<<i<<"/"<<N')
s=s.replace('<<seen.size()<<",\\\"families\\\":12','<<evaluated<<",\\\"configuration_stream_size\\\":"<<seen.size()<<",\\\"shard\\\":"<<shard<<",\\\"families\\\":12')
s=s.replace('"COMPLETE unique="<<seen.size()<<" symbol="','"COMPLETE_DIRECT_M1 evaluated="<<evaluated<<" stream_unique="<<seen.size()<<" symbol="')
(root/'search_sessions_direct.cpp').write_text(s)
print('direct variant written')
