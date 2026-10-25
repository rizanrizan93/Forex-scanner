using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using Rizan.Indicators;
using X=Rizan.Portfolio.Xau;

namespace cAlgo;

[Indicator(IsOverlay=true,TimeZone=TimeZones.UTC,AccessRights=AccessRights.None)]
public class RizanXauCbotIndicator : Indicator
{
    [Parameter("Warmup M1 bars",DefaultValue=16000,MinValue=12000,MaxValue=100000)]
    public int WarmupBars {get;set;}
    [Parameter("Track fresh technical scenario",DefaultValue=false)]
    public bool TrackScenario {get;set;}
    [Parameter("Manual trail activate (R)",DefaultValue=1.0,MinValue=0.0,MaxValue=10.0)]
    public double ActivationR {get;set;}
    [Parameter("Manual trail distance (R)",DefaultValue=1.0,MinValue=.1,MaxValue=10.0)]
    public double DistanceR {get;set;}
    [Output("BUY next-close threshold",LineColor="LimeGreen",LineStyle=LineStyle.Dots)]
    public IndicatorDataSeries BuyLine {get;set;}=null!;
    [Output("SELL confirmation estimate",LineColor="Tomato",LineStyle=LineStyle.Dots)]
    public IndicatorDataSeries SellLine {get;set;}=null!;
    [Output("Manual trailing scenario",LineColor="Gold",Thickness=2)]
    public IndicatorDataSeries TrailLine {get;set;}=null!;
    cAlgo.API.Bars m1=null!;
    Dictionary<DateTime,XauIndicatorFrame> frames=new();
    List<X.Candle> closed=new();
    XauIndicatorFrame? latest;
    DateTime lastMinute,lastScenario;
    ManualTrailing? scenario;
    bool validSymbol;

    protected override void Initialize()
    {
        validSymbol=SymbolName.ToUpperInvariant().Contains("XAU") && TimeFrame==cAlgo.API.TimeFrame.Minute5;
        if(!validSymbol){Message("Pasang pada XAUUSD timeframe M5.");return;}
        m1=MarketData.GetBars(cAlgo.API.TimeFrame.Minute,SymbolName);
        for(int n=0;n<60 && m1.Count<WarmupBars;n++)if(m1.LoadMoreHistory()==0)break;
        Refresh();Timer.Start(TimeSpan.FromSeconds(1));
    }
    void Message(string text) => Chart.DrawStaticText("rizan-cbot-indicator",text,
        VerticalAlignment.Top,HorizontalAlignment.Left,Color.White);
    void Refresh()
    {
        if(!validSymbol)return;
        var now=DateTime.SpecifyKind(Server.TimeInUtc,DateTimeKind.Utc);
        var minute=X.FrozenCore.Floor(now,1);
        if(minute!=lastMinute)
        {
            lastMinute=minute;closed=new();
            for(int i=0;i<m1.Count;i++)
            {
                var at=DateTime.SpecifyKind(m1.OpenTimes[i],DateTimeKind.Utc);
                if(at.AddMinutes(1)>now)break;
                closed.Add(new(at,m1.OpenPrices[i],m1.HighPrices[i],m1.LowPrices[i],m1.ClosePrices[i]));
            }
            var all=XauIndicatorCore.Build(closed,now);
            frames=all.ToDictionary(f=>f.AtUtc);latest=all.LastOrDefault();
            // Refresh the new current chart slot from information known at its opening.
            if(Bars.Count>0)Paint(Bars.Count-1);
        }
        bool fresh=closed.Count>0 && (now-closed[^1].End(1)).TotalSeconds<=90;
        if(latest==null || !latest.Warm){Message("WARMUP: perlu 200 candle H1 tertutup. Tidak ada entry.");return;}
        string state=!fresh ? "DATA TERLAMBAT" : !XauIndicatorCore.Session(now) ? "DI LUAR SESI 19:00–00:00 WIB" :
            latest.BuyPriorEligible && latest.H1Bias==1 && latest.M15Bias==1 ? "ABA-ABA BUY; tunggu close M5" :
            latest.SellTriggerEstimate!=null && latest.H1Bias==-1 && latest.M15Bias==-1 ? "ABA-ABA SELL; tunggu close M5" : "MENUNGGU POLA";
        bool current=fresh && latest.SignalSide!=0 && now>=latest.AtUtc && (now-latest.AtUtc).TotalSeconds<60;
        if(current)state=(latest.SignalSide==1 ? "BUY" : "SELL")+" TEKNIS TERKONFIRMASI (bukan order)";
        string levels="";
        if(current)
        {
            var plan=XauIndicatorCore.Reference(latest,Symbol.Bid,Symbol.Ask);
            levels=$"\nAcuan {plan.Entry:F2} | SL awal {plan.Stop:F2} | TP asli {plan.Target:F2}";
            if(TrackScenario && latest.AtUtc>lastScenario && (scenario==null || scenario.Stopped))
            {
                // Start ONLY from a signal actually observed during its live window.
                lastScenario=latest.AtUtc;
                scenario=new(latest.SignalSide,plan.Entry,plan.Stop,now,Symbol.Ask-Symbol.Bid,ActivationR,DistanceR);
            }
        }
        if(scenario!=null && fresh)
        {
            foreach(var b in closed)scenario.Step(b);
            levels+=$"\nTRAIL SIMULASI {scenario.Stop:F2} | "+(scenario.CoverageGap ? "HISTORY TERPUTUS" : scenario.Stopped ? "STOP TERAMATI" : scenario.Active ? "AKTIF" : "BELUM AKTIF");
            if(Bars.Count>0 && !scenario.Stopped && !scenario.CoverageGap)TrailLine[Bars.Count-1]=scenario.Stop;
        }
        if(!fresh && Bars.Count>0){BuyLine[Bars.Count-1]=double.NaN;SellLine[Bars.Count-1]=double.NaN;TrailLine[Bars.Count-1]=double.NaN;}
        Message("RIZAN · indikator entry cBot XAU V1.3.0\n"+state+
            $"\nBias H1 {latest.H1Bias:+0;-0;0} | M15 {latest.M15Bias:+0;-0;0}"+levels+
            "\nMacro, news, exposure dan readiness cBot belum diperiksa di chart."+
            "\nPanah = teknis historis; trailing hanya skenario, tidak mengubah SL broker.");
    }
    void Paint(int index)
    {
        BuyLine[index]=double.NaN;SellLine[index]=double.NaN;TrailLine[index]=double.NaN;
        var at=DateTime.SpecifyKind(Bars.OpenTimes[index],DateTimeKind.Utc);
        if(!frames.TryGetValue(at,out var f) || !f.Warm)return;
        BuyLine[index]=f.BuyTriggerNext;
        SellLine[index]=f.SellTriggerEstimate ?? double.NaN;
        if(f.SignalSide!=0)Chart.DrawIcon("rizan-technical-"+at.Ticks,
            f.SignalSide==1 ? ChartIconType.UpArrow : ChartIconType.DownArrow,
            at,f.SignalSide==1 ? f.Low : f.High,f.SignalSide==1 ? Color.LimeGreen : Color.Tomato);
    }
    public override void Calculate(int index)
    {
        if(!validSymbol)return;
        Paint(index);
        if(index==Bars.Count-1)Refresh();
    }
    protected override void OnTimer(){Refresh();}
}
