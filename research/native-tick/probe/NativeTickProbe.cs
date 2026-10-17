using System;
using System.Collections.Generic;
using System.Text.Json;
using cAlgo.API;
namespace cAlgo.Robots;
[Robot(TimeZone=TimeZones.UTC, AccessRights=AccessRights.None)]
public class NativeTickProbe : Robot
{
    [Parameter("Fee probe in backtest only",DefaultValue=false)]
    public bool FeeProbe {get;set;}
    bool nativeAllowed,feeOpened,feeClosed;
    DateTime feeAt;
    readonly Dictionary<string,long> counts = new();
    readonly Dictionary<string,DateTime> previous = new();
    readonly Dictionary<string,string> first = new(), last = new();
    readonly Dictionary<string,double> minSpread=new(),maxSpread=new();
    long reversed, futureBars;
    protected override void OnStart()
    {
        if (RunningMode == RunningMode.RealTime) { Print("BACKTEST_ONLY_REFUSED"); Stop(); return; }
        nativeAllowed=true;if(FeeProbe)Timer.Start(TimeSpan.FromSeconds(1));
        foreach(var name in new[]{"XAUUSD","EURUSD"})
        {
            counts[name]=0;minSpread[name]=double.PositiveInfinity;maxSpread[name]=0;
            var s=Symbols.GetSymbol(name);
            s.Tick += e => Observe(name);
            var bars=MarketData.GetBars(TimeFrame.Minute,name);
            Print("PROBE_CONTEXT "+JsonSerializer.Serialize(new {Symbol=name,Bid=s.Bid,Ask=s.Ask,Spread=s.Ask-s.Bid, LotSize=s.LotSize, MinUnits=s.VolumeInUnitsMin, EstimateBuy001=s.GetEstimatedMargin(TradeType.Buy,s.QuantityToVolumeInUnits(0.01)), Bars=bars.Count, Latest=bars.Count>0?bars.OpenTimes.LastValue.ToString("O"):"none", Now=Server.Time.ToString("O")}));
            if(bars.Count>0 && bars.OpenTimes.LastValue>Server.Time) futureBars++;
        }
        Print("PROBE_ACCOUNT "+JsonSerializer.Serialize(new{Mode=RunningMode.ToString(),Balance=Account.Balance,Leverage=Account.PreciseLeverage,Currency=Account.Asset.Name}));
    }
    void Observe(string name)
    {
        var t=Server.Time;
        var symbol=Symbols.GetSymbol(name);var spread=symbol.Ask-symbol.Bid;minSpread[name]=Math.Min(minSpread[name],spread);maxSpread[name]=Math.Max(maxSpread[name],spread);
        if(previous.TryGetValue(name,out var p) && t<p) reversed++;
        previous[name]=t;
        if(counts[name]++==0)first[name]=t.ToString("O");
        last[name]=t.ToString("O");
    }
    protected override void OnTimer()
    {
        if(!nativeAllowed || RunningMode==RunningMode.RealTime || !FeeProbe)return;
        if(!feeOpened)
        {
            feeOpened=true;feeAt=Server.Time;
            foreach(var name in new[]{"XAUUSD","EURUSD"})
            {
                var s=Symbols.GetSymbol(name);
                var r=ExecuteMarketOrder(TradeType.Buy,name,s.QuantityToVolumeInUnits(.01),"NATIVE FEE PROBE");
                Print("PROBE_FILL "+JsonSerializer.Serialize(new{Symbol=name,Success=r.IsSuccessful,Error=r.Error?.ToString(),Commission=r.Position?.Commissions,Entry=r.Position?.EntryPrice}));
            }
        }
        else if(!feeClosed && (Server.Time-feeAt).TotalSeconds>=60)
        {
            feeClosed=true;
            foreach(var p in Positions)if(p.Label=="NATIVE FEE PROBE")ClosePosition(p);
            foreach(var h in History)Print("PROBE_FEE "+JsonSerializer.Serialize(new{Symbol=h.SymbolName,Commission=h.Commissions,Net=h.NetProfit,Gross=h.GrossProfit,Units=h.VolumeInUnits}));
        }
    }
    protected override void OnStop()
    {
        Print("PROBE_RESULT "+JsonSerializer.Serialize(new{Counts=counts,MinSpread=minSpread,MaxSpread=maxSpread,First=first,Last=last,Reversed=reversed,FutureBars=futureBars,Balance=Account.Balance,Equity=Account.Equity,Positions=Positions.Count}));
    }
}
