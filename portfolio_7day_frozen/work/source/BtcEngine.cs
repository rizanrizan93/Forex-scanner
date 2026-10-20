using System;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;
internal sealed class BtcEngine : EngineContext
{
    internal const string Prefix="RZBTC8500283";
    sealed class State {public int Schema{get;set;}=1;public string ContractHash{get;set;}=BtcSevenDayFeed.Contract;public long AccountNumber{get;set;} public string Symbol{get;set;}="BTCUSD";public long Revision{get;set;}public DateTime LastSignal{get;set;} public DateTime Expiry{get;set;} public bool Sending{get;set;} public bool Fault{get;set;} public bool ExitPending{get;set;} public DateTime WeekendLockUntil{get;set;} public string ExitReason{get;set;}="";}
    State state=new();bool ready;DateTime nextSchedule,nextExitAttempt,nextCloseLog;DateTime? weekClose;bool marketOpen;string key="";
    internal BtcEngine(RizanPortfolio host):base(host,"BTCUSD"){}
    bool replay,restored;BtcStateLink? link;BtcSignal? prepared;readonly BtcSevenDayFeed feed=new();
    internal override bool RecoveryReady=>ready&&!state.Fault&&!state.ExitPending&&(replay||link!=null&&link.FeedReady&&link.Persisted(state.Revision)&&feed.Fresh(Server.TimeInUtc));
    internal override double PendingRisk=>0;
    internal override double PendingMargin=>0;
    internal override string PendingOrderLabel=>"";
    internal override void SetParameters(){}
    IEnumerable<Position> Owned=>Positions.Where(p=>p.SymbolName==Instrument&&p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true);
    void Save(){
        state.AccountNumber=Account.Number;state.Revision++;
        string value=JsonSerializer.Serialize(state);
        try{LocalStorage.SetString(key,value,LocalStorageScope.Instance);LocalStorage.Flush(LocalStorageScope.Instance);
            if(LocalStorage.GetString(key,LocalStorageScope.Instance)!=value)throw new Exception("BTC_LOCAL_READBACK");
            link?.Changed(state.Revision,value);}
        catch{state.Fault=true;Print("BTC_LOCAL_CHECKPOINT_FAILED entry_blocked=True");throw;}
    }
    void Validate(State x){if(x.Schema!=1||x.ContractHash!=BtcSevenDayFeed.Contract||x.AccountNumber!=Account.Number||x.Symbol!="BTCUSD"||x.Revision<0)throw new Exception("BTC_STATE_IDENTITY");}
    void Recover(JsonElement value){
        if(value.ValueKind!=JsonValueKind.Null){var remote=JsonSerializer.Deserialize<State>(value.GetRawText())??throw new Exception("BTC_NULL_STATE");Validate(remote);
            if(restored&&remote.Revision>state.Revision)throw new Exception("BTC_REMOTE_WRITER_AHEAD");
            if(remote.Revision==state.Revision&&JsonSerializer.Serialize(remote)!=JsonSerializer.Serialize(state))throw new Exception("BTC_STATE_REVISION_CONFLICT");
            if(remote.Revision>state.Revision)state=remote;
        }
        if(state.Sending||Owned.Count()>1||Owned.Any(p=>p.StopLoss==null||p.TakeProfit==null)||Owned.Any()&&state.Expiry==default)state.Fault=true;
        if(state.Revision==0&&History.Any(p=>p.SymbolName==Instrument&&p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true))state.Fault=true;
        restored=true;ready=true;Save();Manage(Server.TimeInUtc);
    }
    public override void OnStart(){
        key="RIZAN BTC 7D130 "+Account.Number;state.AccountNumber=Account.Number;
        try{var saved=LocalStorage.GetString(key,LocalStorageScope.Instance);if(!string.IsNullOrEmpty(saved)){state=JsonSerializer.Deserialize<State>(saved)??throw new Exception("BTC_NULL_STATE");Validate(state);ready=true;if(state.Sending)state.Fault=true;}
            if(replay){ready=true;Save();Manage(Server.TimeInUtc);return;}
            link=new BtcStateLink(Host,Recover,root=>feed.Accept(root,Server.TimeInUtc));
            link.Changed(state.Revision,JsonSerializer.Serialize(state));link.Tick();
        }catch{state.Fault=true;Print("BTC_RECOVERY_BLOCK entry_blocked=True");Stop();}
    }
    // Explicit fake-broker replay entry point, never called by native OnStart.
    internal void ReplayStart(){key="RIZAN BTC 7D130 "+Account.Number;state.AccountNumber=Account.Number;ready=true;replay=true;}
    public override void OnTick()=>Manage(Server.TimeInUtc);
    internal void InvalidateSchedule()=>nextSchedule=default;
    void RefreshSchedule(DateTime now)
    {
        try{
            marketOpen=Symbol.MarketHours.IsOpened(now);
            if(now>=nextSchedule){weekClose=BtcWeekendPolicy.LastClose(now,t=>Symbol.MarketHours.IsOpened(t));nextSchedule=now.AddMinutes(5);}
        }catch(Exception ex){marketOpen=false;weekClose=null;nextSchedule=now.AddSeconds(5);Print("BTC_SCHEDULE_UNAVAILABLE {0}",ex.Message);}
    }
    void SaveExitIntent(){try{Save();}catch(Exception ex){state.Fault=true;Print("BTC_EXIT_PERSIST_FAILED {0}",ex.Message);}}
    internal void Manage(DateTime now)
    {
        if(!ready)return;
        RefreshSchedule(now);
        var owned=Owned.ToArray();
        bool weekend=BtcWeekendPolicy.MustFlatten(now,weekClose);
        if(weekend&&(BtcWeekendPolicy.Weekend(now)||weekClose.HasValue)&&state.WeekendLockUntil<=now){state.WeekendLockUntil=BtcWeekendPolicy.Monday(now).AddDays(7);SaveExitIntent();}
        if(owned.Length==0){if(state.ExitPending){state.ExitPending=false;state.ExitReason="";SaveExitIntent();}return;}
        if(weekend||now>=state.Expiry){if(!state.ExitPending){state.ExitPending=true;state.ExitReason=weekend?"WEEKEND_FLAT":"EXPIRY";SaveExitIntent();}}
        if(!state.ExitPending||now<nextExitAttempt)return;
        nextExitAttempt=now.AddSeconds(1);
        // Default OFF is respected for closes too. A running, enabled bot and an
        // available broker are required; do not report a closed position on rejection.
        if(!Host.EnableTrading||!marketOpen){if(now>=nextCloseLog){nextCloseLog=now.AddSeconds(30);Print("BTC_EXIT_WAIT reason={0} enabled={1} market_open={2} remaining={3}",state.ExitReason,Host.EnableTrading,marketOpen,owned.Length);}return;}
        foreach(var p in owned){try{var r=ClosePosition(p);if(!r.IsSuccessful&&now>=nextCloseLog){nextCloseLog=now.AddSeconds(10);Print("BTC_CLOSE_RETRY id={0} reason={1} error={2}",p.Id,state.ExitReason,r.Error?.ToString()??"UNKNOWN");}}
            catch(Exception ex){if(now>=nextCloseLog){nextCloseLog=now.AddSeconds(10);Print("BTC_CLOSE_RETRY id={0} reason={1} error={2}",p.Id,state.ExitReason,ex.Message);}}}
        if(!Owned.Any()){Print("BTC_FLAT_CONFIRMED reason={0} at={1}",state.ExitReason,now);state.ExitPending=false;state.ExitReason="";SaveExitIntent();}
    }
    public override void OnTimer(){
        var now=Server.TimeInUtc;Manage(now);if(replay)return;
        link?.Tick();
        if(prepared!=null){var signal=prepared;
            if((now-signal.At).TotalSeconds>5||link==null||link.Fatal){prepared=null;state.Sending=false;Save();}
            else if(link.Persisted(state.Revision)){prepared=null;
                try{ExecuteSignal(signal,now);state.Sending=false;Save();}catch{state.Fault=true;Save();Print("BTC_EXECUTION_UNCERTAIN entry_blocked=True");}}
        }
        if(!RecoveryReady)return;
        var at=BtcSevenDayFeed.Hour(now);
        if((now-at).TotalSeconds<=5&&feed.Signals.TryGetValue(at,out var s))Enter(s,now);
    }
    internal void Enter(BtcSignal s,DateTime now){
        if(replay){ExecuteSignal(s,now);return;}
        Manage(now);
        if(!RecoveryReady||prepared!=null||s.At>now||(now-s.At).TotalSeconds>5||s.At<=state.LastSignal)return;
        state.LastSignal=s.At; // consume even when busy/OFF; never catch up a missed signal
        if(!Host.EnableTrading||Owned.Any()||!Host.PortfolioReady||!Host.NoForeignExposure()||!BtcWeekendPolicy.CanEnter(now,weekClose,marketOpen,state.WeekendLockUntil)){Save();return;}
        state.Expiry=s.At.AddHours(s.Side>0?128:8);
        if(weekClose.HasValue)state.Expiry=new[]{state.Expiry,weekClose.Value.AddMinutes(-BtcWeekendPolicy.FlattenMinutes)}.Min();
        state.Sending=true;Save();prepared=s; // broker request waits for durable remote ACK
    }
    void ExecuteSignal(BtcSignal s,DateTime now)
    {
        Manage(now);
        if(!RecoveryReady||s.At>now||(now-s.At).TotalSeconds>5||replay&&s.At<=state.LastSignal)return;
        if(replay){state.LastSignal=s.At;Save();} // Busy signals are consumed, never replayed later.
        if(!Host.EnableTrading||Owned.Any()||!Host.PortfolioReady||!Host.NoForeignExposure()||!BtcWeekendPolicy.CanEnter(now,weekClose,marketOpen,state.WeekendLockUntil))return;
        int side=s.Side;double quote=side>0?Symbol.Ask:Symbol.Bid,fill=quote+side*Symbol.Bid*.0001,dist=(side>0?2:1.5)*s.Atr;
        if(!double.IsFinite(fill)||fill<=0||dist<=0||fill-side*dist<=0||side*(fill-s.Reference)>.5*s.Atr)return;
        double reference=Math.Min(Account.Balance,Account.Equity),risk=side>0?.23:.18;
        double riskUnit=dist+.0011*fill;
        double btc=Math.Min(100,reference*risk/riskUnit);
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
        state.Expiry=s.At.AddHours(side>0?128:8);
        if(weekClose.HasValue)state.Expiry=new[]{state.Expiry,weekClose.Value.AddMinutes(-BtcWeekendPolicy.FlattenMinutes)}.Min();
        if(replay){state.Sending=true;Save();}
        var result=ExecuteMarketOrder(side>0?TradeType.Buy:TradeType.Sell,Instrument,units,Prefix+"|"+s.At.Ticks,dist/Symbol.PipSize,dist*(side>0?12:2)/Symbol.PipSize,"BTC8500283");
        if(!result.IsSuccessful||result.Position==null){state.Fault=true;throw new Exception("BTC_ORDER_NOT_CONFIRMED");}
        if(result.Position!=null){var p=result.Position;
            if(p.StopLoss==null||p.TakeProfit==null||!Host.BtcFillWithinBudget(this,p,reference,dist,valuePerUnit)){state.ExitPending=true;state.ExitReason="FILL_PROTECTION_OR_BUDGET";Save();var close=ClosePosition(p);if(!close.IsSuccessful)state.Fault=true;else{state.ExitPending=false;state.ExitReason="";}}}
        if(replay){state.Sending=false;Save();}
    }
    public override void OnStop(){try{if(ready)Save();}finally{link?.Dispose();}}
}
