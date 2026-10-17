using System;
using System.Collections.Generic;
using System.Text.Json;
using cAlgo.API;
namespace cAlgo.Robots;
[Robot(TimeZone=TimeZones.UTC, AccessRights=AccessRights.None)]
public class NativeTickProbe : Robot
{
    readonly Dictionary<string,long> counts = new();
    readonly Dictionary<string,DateTime> previous = new();
    readonly Dictionary<string,string> first = new(), last = new();
    long reversed, futureBars;
    protected override void OnStart()
    {
        if (RunningMode == RunningMode.RealTime) { Print("BACKTEST_ONLY_REFUSED"); Stop(); return; }
        foreach(var name in new[]{"XAUUSD","EURUSD"})
        {
            counts[name]=0;
            var s=Symbols.GetSymbol(name);
            s.Tick += e => Observe(name);
            var bars=MarketData.GetBars(TimeFrame.Minute,name);
            Print("PROBE_CONTEXT "+JsonSerializer.Serialize(new {Symbol=name, LotSize=s.LotSize, MinUnits=s.VolumeInUnitsMin, EstimateBuy001=s.GetEstimatedMargin(TradeType.Buy,s.QuantityToVolumeInUnits(0.01)), Bars=bars.Count, Latest=bars.Count>0?bars.OpenTimes.LastValue.ToString("O"):"none", Now=Server.Time.ToString("O")}));
            if(bars.Count>0 && bars.OpenTimes.LastValue>Server.Time) futureBars++;
        }
        Print("PROBE_ACCOUNT "+JsonSerializer.Serialize(new{Mode=RunningMode.ToString(),Balance=Account.Balance,Leverage=Account.PreciseLeverage,Currency=Account.Asset.Name}));
    }
    void Observe(string name)
    {
        var t=Server.Time;
        if(previous.TryGetValue(name,out var p) && t<p) reversed++;
        previous[name]=t;
        if(counts[name]++==0)first[name]=t.ToString("O");
        last[name]=t.ToString("O");
    }
    protected override void OnStop()
    {
        Print("PROBE_RESULT "+JsonSerializer.Serialize(new{Counts=counts,First=first,Last=last,Reversed=reversed,FutureBars=futureBars,Balance=Account.Balance,Equity=Account.Equity,Positions=Positions.Count}));
    }
}
