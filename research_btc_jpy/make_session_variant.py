from pathlib import Path
root=Path(__file__).resolve().parent
s=(root/'search.cpp').read_text()
s=s.replace('widths[]={15,60,240}','widths[]={5,15,60}').replace('h4=agg[2]','h4=aggregate(240);buildDays()').replace('state=202610190601ULL','state=202610190603ULL')
s=s.replace('"sweep_reclaim","structure_break","break_retest","trend_pullback","channel_reversion","rsi_reversal","inside_break","compression_break","displacement_follow","engulf_reversal","range_expansion_fade","ema_cross"','"asia_range_break","asia_sweep_reclaim","previous_day_break","previous_day_sweep","previous_day_mid_reclaim","tokyo_open_break","london_open_break","newyork_open_break","asia_falsebreak_reversal","daily_trend_pullback","london_compression_expansion","previous_day_range_expansion"')
insert='''
struct D {double hi=-1e90,lo=1e90,o=0,c=0,ph=0,pl=0,pc=0,po=0;array<double,16> rh,rl;array<int,16> n{};D(){rh.fill(-1e90);rl.fill(1e90);}};
map<int64_t,D> days;
const int rangeStart[]={0,0,0,0,0,0,0,0,420,480,540,600,720,780,840,900};
const int rangeEnd[]={180,240,360,480,30,60,90,120,480,540,600,660,780,840,900,960};
void buildDays(){
 for(auto&b:minutes){int64_t day=b.t/1440;int m=b.t%1440;auto&d=days[day];if(d.o==0)d.o=b.o;d.hi=max(d.hi,b.h);d.lo=min(d.lo,b.l);d.c=b.c;
  for(int k=0;k<16;k++)if(m>=rangeStart[k]&&m<rangeEnd[k]){d.rh[k]=max(d.rh[k],b.h);d.rl[k]=min(d.rl[k],b.l);d.n[k]++;}}
 D prev;bool first=true;for(auto&[t,d]:days){if(!first){d.ph=prev.hi;d.pl=prev.lo;d.pc=prev.c;d.po=prev.o;}prev=d;first=false;}
}
'''
s=s.replace('int key(const P&p)',insert+'\nint key(const P&p)')
a=s.index('  switch(p.family){');z=s.index('\n  if(side)ss.push_back',a)
replacement='''  auto di=days.find(avail/1440);if(di==days.end())continue;const D&d=di->second;int minute=avail%1440;
  const int ri=p.family==5?4+p.look:p.family==6?8+p.look:p.family==7?12+p.look:p.look;
  bool rangeReady=minute>=rangeEnd[ri]&&d.n[ri]>=(rangeEnd[ri]-rangeStart[ri])*.8;
  double ah=d.rh[ri],al=d.rl[ri],pd=d.ph-d.pl,mid=(d.ph+d.pl)/2.;
  bool previous=d.pl>0&&pd>0;
  switch(p.family){
   case 0:if(rangeReady&&minute<rangeEnd[ri]+480)side=a.c>ah+pad&&prev.c<=ah+pad?1:a.c<al-pad&&prev.c>=al-pad?-1:0;break;
   case 1:if(rangeReady&&minute<rangeEnd[ri]+600)side=a.l<al-pad&&a.c>al&&body>thresh?1:a.h>ah+pad&&a.c<ah&&body<-thresh?-1:0;break;
   case 2:if(previous){double pad2=pad+pd*.02*p.look;side=a.c>d.ph+pad2&&prev.c<=d.ph+pad2?1:a.c<d.pl-pad2&&prev.c>=d.pl-pad2?-1:0;}break;
   case 3:if(previous){double pad2=pad+pd*.02*p.look;side=a.l<d.pl-pad2&&a.c>d.pl&&body>thresh?1:a.h>d.ph+pad2&&a.c<d.ph&&body<-thresh?-1:0;}break;
   case 4:if(previous){double pad2=pad+pd*.025*p.look;side=prev.c<mid-pad2&&a.c>mid+pad2&&body>thresh?1:prev.c>mid+pad2&&a.c<mid-pad2&&body<-thresh?-1:0;}break;
   case 5:case 6:case 7:if(rangeReady&&minute<rangeEnd[ri]+240)side=a.c>ah+pad&&prev.c<=ah+pad?1:a.c<al-pad&&prev.c>=al-pad?-1:0;break;
   case 8:if(rangeReady&&minute<rangeEnd[ri]+360)side=prev.c<al-pad&&a.c>al&&body>thresh?1:prev.c>ah+pad&&a.c<ah&&body<-thresh?-1:0;break;
   case 9:if(previous){double level=mid+(d.pc>d.po?1.:-1.)*pd*.05*p.look;side=d.pc>d.po&&a.l<level-pad&&a.c>level&&body>thresh?1:d.pc<d.po&&a.h>level+pad&&a.c<level&&body<-thresh?-1:0;}break;
   case 10:if(previous&&rangeReady&&minute>=420&&minute<900&&ah-al<pd*(.4+.1*p.look))side=a.c>ah+pad&&prev.c<=ah+pad&&body>thresh?1:a.c<al-pad&&prev.c>=al-pad&&body<-thresh?-1:0;break;
   case 11:if(previous){double dist=pd*(.25+.25*p.look)+pad;side=prev.c<=d.pc+dist&&a.c>d.pc+dist?1:prev.c>=d.pc-dist&&a.c<d.pc-dist?-1:0;}break;
  }'''
s=s[:a]+replacement+s[z:]
s=s.replace('if(p.family==3||p.family==5||p.family==6||p.family==8||p.family==9||p.family==11)p.look=0;','// Every session-family look parameter affects its range or threshold.')
# Generic rolling lookback extrema are not used in this variant.
s=s.replace('double hi=-1e90,lo=1e90;for(int j=i-look;j<i;j++){hi=max(hi,v[j].h);lo=min(lo,v[j].l);}','')
(root/'search_sessions.cpp').write_text(s)
print('session variant written')
