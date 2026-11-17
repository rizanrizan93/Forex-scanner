using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using Rizan.ManualR3;

namespace cAlgo;
[Indicator(IsOverlay=true,TimeZone=TimeZones.UTC,AccessRights=AccessRights.None)]
public class RizanManualRangeReclaimR3 : Indicator
{
    [Parameter("Warmup M1 bars",DefaultValue=12000,MinValue=5000,MaxValue=50000)]
    public int WarmupBars {get;set;}
    [Output("Keltner bawah M15",LineColor="SteelBlue")]
    public IndicatorDataSeries Lower {get;set;}=null!;
    [Output("Keltner atas M15",LineColor="SteelBlue")]
    public IndicatorDataSeries Upper {get;set;}=null!;
    cAlgo.API.Bars m1=null!;ManualR3Core? core;DateTime lastMinute,lastQuote,lastNewsTry;
    DateTime calendarAt;List<News>? news;bool valid,fetching;string lastAlert="";
    const string NewsUrl="https://rizan-bridge.duckdns.org:25345/bootstrap125/manual-r3-news.json";
    static DateTime Utc(DateTime t)=>DateTime.SpecifyKind(t,DateTimeKind.Utc);
    void Message(string text)=>Chart.DrawStaticText("r3-panel",text,VerticalAlignment.Top,HorizontalAlignment.Left,Color.White);
    protected override void Initialize()
    {
        valid=SymbolName.ToUpperInvariant().Contains("XAUUSD")&&TimeFrame==cAlgo.API.TimeFrame.Minute;
        if(!valid){Message("R3: pasang pada chart XAUUSD M1.");return;}
        m1=MarketData.GetBars(cAlgo.API.TimeFrame.Minute,SymbolName);
        for(int i=0;i<60&&m1.Count<WarmupBars;i++)if(m1.LoadMoreHistory()==0)break;
        Symbol.Tick += _ => lastQuote=Utc(Server.TimeInUtc);
        Refresh();Timer.Start(TimeSpan.FromSeconds(1));
    }
    void FetchCalendar(DateTime now)
    {
        if(fetching||(now-lastNewsTry).TotalSeconds<30)return;fetching=true;lastNewsTry=now;
        Http.GetAsync(NewsUrl+"?slot="+(new DateTimeOffset(now).ToUnixTimeSeconds()/30),response=>BeginInvokeOnMainThread(()=>{
            fetching=false;
            try{
                if(!response.IsSuccessful)throw new Exception();using var doc=JsonDocument.Parse(response.Body);var root=doc.RootElement;
                if(root.GetProperty("contract").GetString()!="RIZAN_MANUAL_R3_CALENDAR_V1"||root.GetProperty("execution_authority").GetBoolean())throw new Exception();
                var at=DateTime.Parse(root.GetProperty("observed_at").GetString()!).ToUniversalTime();
                if((Utc(Server.TimeInUtc)-at).TotalSeconds>600||at>Utc(Server.TimeInUtc).AddSeconds(5))throw new Exception();
                var list=new List<News>();foreach(var row in root.GetProperty("events").EnumerateArray()){
                    string kind=row.GetProperty("event").GetString()!;if(!new[]{"CPI","PPI","NFP","FOMC"}.Contains(kind))throw new Exception();
                    list.Add(new(kind,DateTime.Parse(row.GetProperty("at").GetString()!).ToUniversalTime()));
                }news=list;calendarAt=at;
            }catch{news=null;}
        }));
    }
    void Refresh()
    {
        if(!valid)return;var now=Utc(Server.TimeInUtc);var minute=ManualR3Core.Floor(now,1);
        if(core==null||minute!=lastMinute){
            lastMinute=minute;var input=new List<Candle>();
            for(int i=Math.Max(0,m1.Count-WarmupBars-1);i<m1.Count;i++){
                var t=Utc(m1.OpenTimes[i]);if(t.AddMinutes(1)>now)break;
                input.Add(new(t,m1.OpenPrices[i],m1.HighPrices[i],m1.LowPrices[i],m1.ClosePrices[i]));
            }
            var plan=core?.FrozenPlan;core=new(input,now);core.RestorePlan(plan);
            foreach(var s in core.Signals)Chart.DrawIcon("r3-technical-"+s.TouchAt.Ticks+"-"+s.Side,
                s.Side==1?ChartIconType.UpArrow:ChartIconType.DownArrow,s.At,s.Level,Color.Gray);
            for(int i=Math.Max(0,Bars.Count-500);i<Bars.Count;i++)Paint(i);
        }
        FetchCalendar(now);var calendar=news!=null&&(now-calendarAt).TotalSeconds<=600?news:null;
        var snapshot=core!.Evaluate(now,Symbol.Bid,Symbol.Ask,lastQuote,calendar);
        if(snapshot.State=="WAIT_DATA"){
            if(Bars.Count>0){Lower[Bars.Count-1]=double.NaN;Upper[Bars.Count-1]=double.NaN;}
            Chart.RemoveObject("r3-active-level");Chart.RemoveObject("r3-sl");Chart.RemoveObject("r3-tp");
            Message("RIZAN Manual R3 · MENUNGGU DATA\nRiwayat M1/H1 belum cukup atau candle terakhir terlambat.");return;
        }
        string levels=$"\nZona BUY {snapshot.Lower:F2} | zona SELL {snapshot.Upper:F2}";
        if(snapshot.Plan!=null){var p=snapshot.Plan;levels+=$"\nEntry acuan {p.Entry:F2} | SL {p.Stop:F2} | TP {p.Target:F2}";
            Chart.DrawHorizontalLine("r3-active-level",snapshot.Signal!.Level,Color.SteelBlue,1,LineStyle.Dots);
            Chart.DrawHorizontalLine("r3-sl",p.Stop,Color.Tomato,1,LineStyle.Dots);Chart.DrawHorizontalLine("r3-tp",p.Target,Color.LimeGreen,1,LineStyle.Dots);
            if(lastAlert!=p.Id){lastAlert=p.Id;Print("R3 {0}: pemicu manual baru, berlaku 60 detik",p.Side==1?"BUY":"SELL");}
        }else{Chart.RemoveObject("r3-active-level");Chart.RemoveObject("r3-sl");Chart.RemoveObject("r3-tp");}
        Message("RIZAN Manual Range Reclaim R3 · EKSPERIMENTAL\n"+snapshot.State+
            $"\nBias H1 {snapshot.Bias:+0;-0;0} | ADX14 H1 {snapshot.Adx:F1}"+levels+
            "\nSenin–Rabu 14–00 WIB | entry 60 detik, maksimal 1 ATR M5 dari garis"+
            (calendar==null?"\nKalender belum segar; pemicu entry ditahan.":"\nKalender news terverifikasi; tetap cek posisi dan risiko manual.")+
            "\nPanah abu-abu: teknis historis, kalender masa lalu belum diperiksa. Tidak membuka order.");
    }
    void Paint(int index){Lower[index]=double.NaN;Upper[index]=double.NaN;if(core==null)return;var f=core.Values(Utc(Bars.OpenTimes[index]));Lower[index]=f.Lower;Upper[index]=f.Upper;}
    public override void Calculate(int index){if(!valid)return;Paint(index);if(index==Bars.Count-1)Refresh();}
    protected override void OnTimer()=>Refresh();
}
