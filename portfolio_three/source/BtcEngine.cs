using System;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;
internal sealed class BtcEngine : EngineContext
{
    internal const string Prefix="RZBTC8500283";
    sealed class State {public int Schema{get;set;}=1;public DateTime LastSignal{get;set;} public DateTime Expiry{get;set;} public bool Sending{get;set;} public bool Fault{get;set;}}
    State state=new();bool ready;string key="";DateTime nextRead;Dictionary<DateTime,BtcSignal> signals=new();
    internal BtcEngine(RizanPortfolio host):base(host,"BTCUSD"){}
    internal override bool RecoveryReady=>ready&&!state.Fault;
    internal override double PendingRisk=>0;
    internal override double PendingMargin=>0;
    internal override string PendingOrderLabel=>"";
    internal override void SetParameters(){}
    IEnumerable<Position> Owned=>Positions.Where(p=>p.SymbolName==Instrument&&p.Label.StartsWith(Prefix+"|",StringComparison.Ordinal));
    void Save(){LocalStorage.SetString(key,JsonSerializer.Serialize(state),LocalStorageScope.Instance);LocalStorage.Flush(LocalStorageScope.Instance);}
    public override void OnStart()
    {
        key="RIZAN BTC 8500283 V1 "+Account.Number;
        try{var saved=LocalStorage.GetString(key,LocalStorageScope.Instance);if(!string.IsNullOrEmpty(saved))state=JsonSerializer.Deserialize<State>(saved)??throw new Exception("BTC_NULL_STATE");
            if(state.Schema!=1||state.Sending||Owned.Count()>1||Owned.Any(p=>p.StopLoss==null||p.TakeProfit==null)||Owned.Any()&&state.Expiry==default)throw new Exception("BTC_RECOVERY_REQUIRES_RECONCILIATION");
            ready=true;Save();}
        catch(Exception ex){state.Fault=true;Print("BTC_RECOVERY_BLOCK {0}",ex.Message);Stop();}
    }
    // Used by the source replay with the same entry and portfolio gate as the cBot.
    internal void ReplayStart(){key="RIZAN BTC 8500283 V1 "+Account.Number;ready=true;}
    public override void OnTick()=>Manage(Server.TimeInUtc);
    internal void Manage(DateTime now){foreach(var p in Owned.ToArray())if(now>=state.Expiry){var r=ClosePosition(p);if(!r.IsSuccessful){state.Fault=true;Save();}}}
    public override void OnTimer()
    {
        var now=Server.TimeInUtc;Manage(now);if(!RecoveryReady||now<nextRead)return;
        nextRead=new DateTime(now.Year,now.Month,now.Day,now.Hour,0,0,DateTimeKind.Utc).AddHours(1);
        try{
            var seed=new DateTime(2019,1,1,0,0,0,DateTimeKind.Utc);
            List<BtcBar> Read(TimeFrame tf,int width){var bars=MarketData.GetBars(tf,Instrument);
                while(bars.Count>0&&bars.OpenTimes[0]>seed&&bars.LoadMoreHistory()>0){}
                if(bars.Count==0||(bars.OpenTimes[0]>seed&&bars.Count<1000))throw new Exception("BTC_HISTORY_WARMUP_UNAVAILABLE");
                Print("BTC_HISTORY_SEED tf={0} first={1} bars={2}",width,bars.OpenTimes[0],bars.Count);
                var closed=new List<BtcBar>();for(int i=0;i<bars.Count;i++)if(bars.OpenTimes[i]>=seed&&bars.OpenTimes[i].AddMinutes(width)<=now)closed.Add(new(bars.OpenTimes[i],bars.OpenPrices[i],bars.HighPrices[i],bars.LowPrices[i],bars.ClosePrices[i],width));return closed;}
            signals=BtcCore.Signals(Read(TimeFrame.Hour,60),Read(TimeFrame.Hour4,240));
            var at=new DateTime(now.Year,now.Month,now.Day,now.Hour,0,0,DateTimeKind.Utc);
            if((now-at).TotalSeconds<=5&&signals.TryGetValue(at,out var s))Enter(s,now);
        }catch(Exception ex){state.Fault=true;Save();Print("BTC_ENGINE_ERROR {0}",ex.Message);}
    }
    internal void Enter(BtcSignal s,DateTime now)
    {
        if(!RecoveryReady||s.At>now||(now-s.At).TotalSeconds>5||s.At<=state.LastSignal)return;
        state.LastSignal=s.At;Save(); // Busy signals are consumed, never replayed later.
        if(!Host.EnableTrading||Owned.Any()||!Host.PortfolioReady||!Host.NoForeignExposure())return;
        int side=s.Side;double quote=side>0?Symbol.Ask:Symbol.Bid,fill=quote+side*Symbol.Bid*.0001,dist=(side>0?2:1.5)*s.Atr;
        if(!double.IsFinite(fill)||fill<=0||dist<=0||fill-side*dist<=0||side*(fill-s.Reference)>.5*s.Atr)return;
        double reference=Math.Min(Account.Balance,Account.Equity),risk=side>0?.23:.18,margin=side>0?.95:.30;
        double riskUnit=dist+.0011*fill;
        double btc=Math.Min(100,Math.Min(reference*risk/riskUnit,reference*margin/(fill*(.1+.0005))));
        // In USD-quoted BTC contracts QuantityToVolume converts lots, not BTC.
        // PipValue/PipSize converts price movement per native volume unit to USD.
        double valuePerUnit=Symbol.PipValue/Symbol.PipSize;
        if(!double.IsFinite(valuePerUnit)||valuePerUnit<=0)return;
        btc=Math.Floor(btc/.01+1e-12)*.01;
        double units=Symbol.NormalizeVolumeInUnits(btc/valuePerUnit,RoundingMode.Down);
        if(units<Symbol.VolumeInUnitsMin||units*valuePerUnit<.01)return;
        units=Host.CapBtc(this,units,dist,fill,side,valuePerUnit);
        if(units<Symbol.VolumeInUnitsMin||units*valuePerUnit<.01)return;
        units=Math.Min(units,Symbol.VolumeInUnitsMax);
        state.Expiry=s.At.AddHours(side>0?128:8);state.Sending=true;Save();
        var result=ExecuteMarketOrder(side>0?TradeType.Buy:TradeType.Sell,Instrument,units,Prefix+"|"+s.At.Ticks,dist/Symbol.PipSize,dist*(side>0?12:2)/Symbol.PipSize,"BTC8500283");
        if(result.IsSuccessful&&result.Position!=null){var p=result.Position;
            if(p.StopLoss==null||p.TakeProfit==null||!Host.BtcFillWithinBudget(this,p,reference,dist,valuePerUnit)){var close=ClosePosition(p);if(!close.IsSuccessful)state.Fault=true;}}
        state.Sending=false;Save();
    }
    public override void OnStop(){if(ready)Save();}
}
