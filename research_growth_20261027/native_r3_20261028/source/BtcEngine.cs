using System;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;
internal sealed partial class BtcEngine : EngineContext
{
    internal const string Prefix=FrozenR3.BtcPrefix;
    sealed partial class State {public int Schema{get;set;}=1;public string ContractHash{get;set;}=BtcSevenDayFeed.Contract;public long AccountNumber{get;set;} public string Symbol{get;set;}="BTCUSD";public long Revision{get;set;}public DateTime LastSignal{get;set;} public DateTime Expiry{get;set;} public bool BatchActive{get;set;} public int BatchRemaining{get;set;} public int BatchSent{get;set;} public int BatchSide{get;set;} public double BatchAtr{get;set;} public double BatchSignalReference{get;set;} public double BatchBalance{get;set;} public DateTime BatchDeadline{get;set;} public DateTime BatchNext{get;set;} public bool Sending{get;set;} public bool Fault{get;set;} public bool ExitPending{get;set;} public DateTime WeekendLockUntil{get;set;} public string ExitReason{get;set;}="";}
    State state=new();bool ready;DateTime nextSchedule,nextExitAttempt,nextCloseLog;DateTime? weekClose;bool marketOpen;string key="";
    internal BtcEngine(RizanPortfolio host):base(host,"BTCUSD"){}
    bool replay,restored;BtcStateLink? link;BtcSignal? prepared;readonly BtcSevenDayFeed feed=new();
    internal override bool RecoveryReady=>ready&&!state.Fault&&!state.ExitPending&&(replay||link!=null&&link.FeedReady&&link.Persisted(state.Revision)&&feed.Fresh(Server.TimeInUtc));
    internal bool ResearchFaulted=>state.Fault;internal bool ResearchExitPending=>state.ExitPending;
    internal bool ResearchBatchQueued=>state.BatchRemaining>0;
    internal override double PendingRisk=>ResearchBatchQueued?Math.Max(0,BatchReference*RP.C.BtcBatchRisk-BatchOpenRisk()):0;
    internal override double PendingMargin=>ResearchBatchQueued?Math.Max(0,BatchReference*RP.C.BtcBatchMargin-BatchMargin()):0;
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
    void Validate(State x){if(x.Schema!=1||x.ContractHash!=BtcSevenDayFeed.Contract||x.AccountNumber!=Account.Number||x.Symbol!="BTCUSD"||x.Revision<0)throw new Exception("BTC_STATE_IDENTITY");if(!replay)ValidateNativeState(x);}
    void Recover(JsonElement value){
        if(value.ValueKind!=JsonValueKind.Null){var remote=DecodeNativeState(value.GetRawText())??throw new Exception("BTC_NULL_STATE");Validate(remote);
            if(replay&&restored&&remote.Revision>state.Revision)throw new Exception("BTC_REMOTE_WRITER_AHEAD");
            if(remote.Revision==state.Revision&&JsonSerializer.Serialize(remote)!=JsonSerializer.Serialize(state))throw new Exception("BTC_STATE_REVISION_CONFLICT");
            if(remote.Revision>state.Revision)state=remote;
        }
        if(replay){if(state.Sending||Owned.Count()>1||Owned.Any(p=>p.StopLoss==null||p.TakeProfit==null)||Owned.Any()&&state.Expiry==default)state.Fault=true;}else ReconcileNativeBatch();
        if(state.Revision==0&&History.Any(p=>p.SymbolName==Instrument&&p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true))state.Fault=true;
        restored=true;ready=true;Save();Manage(Server.TimeInUtc);
    }
    public override void OnStart(){
        // Native R3 batch uses the same sizing core with durable per-order intents.
        key=FrozenR3.BtcStorageKey(Account.Number);state.AccountNumber=Account.Number;
        try{var saved=LocalStorage.GetString(key,LocalStorageScope.Instance);if(!string.IsNullOrEmpty(saved)){state=DecodeNativeState(saved)??throw new Exception("BTC_NULL_STATE");Validate(state);ready=true;}
            if(replay){ready=true;Save();Manage(Server.TimeInUtc);return;}
            link=new BtcStateLink(Host,Recover,root=>feed.Accept(root,Server.TimeInUtc));
            link.Changed(state.Revision,JsonSerializer.Serialize(state));link.Tick();
        }catch{state.Fault=true;Print("BTC_RECOVERY_BLOCK entry_blocked=True");Stop();}
    }
    // Explicit fake-broker replay entry point, never called by native OnStart.
    internal void ReplayStart(){key=FrozenR3.BtcStorageKey(Account.Number);state.AccountNumber=Account.Number;ready=true;replay=true;}
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
        if(owned.Length==0){CancelResearchQueue();if(state.ExitPending){state.ExitPending=false;state.ExitReason="";SaveExitIntent();}return;}
        if(weekend||now>=state.Expiry){CancelResearchQueue();if(!state.ExitPending){state.ExitPending=true;state.ExitReason=weekend?"WEEKEND_FLAT":"EXPIRY";SaveExitIntent();}}
        if(!state.ExitPending){ProcessResearchBatch(now);return;}if(now<nextExitAttempt)return;
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
            if((now-signal.At).TotalSeconds>5||link==null||link.Fatal){prepared=null;ClearNativeIntent();state.Sending=false;Save();}
            else if(link.Persisted(state.Revision)){
                try{if(ExecuteSignal(signal,now)){prepared=null;ClearNativeIntent();state.Sending=false;Save();}}catch{state.Fault=true;Save();Print("BTC_EXECUTION_UNCERTAIN entry_blocked=True");}}
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
        state.Expiry=s.At.AddHours(s.Side>0?RP.C.BtcBuyHours:RP.C.BtcSellHours);
        if(weekClose.HasValue)state.Expiry=new[]{state.Expiry,weekClose.Value.AddMinutes(-BtcWeekendPolicy.FlattenMinutes)}.Min();
        state.Sending=true;Save();prepared=s; // broker request waits for durable remote ACK
    }
    bool ExecuteSignal(BtcSignal s,DateTime now)
    {
        if(RP.C.BtcBatchOrders>1)ValidateBatchConfig();
        Manage(now);
        if(!RecoveryReady||s.At>now||(now-s.At).TotalSeconds>5||replay&&s.At<=state.LastSignal)return true;
        if(replay){state.LastSignal=s.At;Save();} // Busy signals are consumed, never replayed later.
        if(!Host.EnableTrading||Owned.Any()||!Host.PortfolioReady||!Host.NoForeignExposure()||!BtcWeekendPolicy.CanEnter(now,weekClose,marketOpen,state.WeekendLockUntil))return true;
        int side=s.Side;double quote=side>0?Symbol.Ask:Symbol.Bid,fill=quote+side*Symbol.Bid*.0001,dist=(side>0?RP.C.BtcBuyStop:RP.C.BtcSellStop)*s.Atr;
        if(!double.IsFinite(fill)||fill<=0||dist<=0||fill-side*dist<=0||side*(fill-s.Reference)>.5*s.Atr)return true;
        double reference=Math.Min(Account.Balance,Account.Equity),risk=(side>0?.23:.18)*RP.C.BtcRisk;
        double riskUnit=dist+.0011*fill;
        bool expand=RP.C.BtcBatchOrders>1&&reference*RP.C.BtcBatchRisk>=100*(dist+.0012*fill);
        state.BatchActive=expand;state.BatchRemaining=0;state.BatchSent=0;state.BatchSide=side;state.BatchAtr=s.Atr;state.BatchSignalReference=s.Reference;state.BatchBalance=reference;state.BatchDeadline=s.At.AddSeconds(RP.C.BtcBatchSeconds);
        double btc=Math.Min(100,reference*risk/riskUnit);
        // In USD-quoted BTC contracts QuantityToVolume converts lots, not BTC.
        // PipValue/PipSize converts price movement per native volume unit to USD.
        double valuePerUnit=Symbol.PipValue/Symbol.PipSize;
        if(!double.IsFinite(valuePerUnit)||valuePerUnit<=0)return true;
        btc=Math.Floor(btc/.01+1e-12)*.01;
        double units=Symbol.NormalizeVolumeInUnits(btc/valuePerUnit,RoundingMode.Down);
        if(units<Symbol.VolumeInUnitsMin||units*valuePerUnit<.01)return true;
        units=Host.CapBtc(this,units,dist,fill,side,valuePerUnit);
        if(expand)units=CapBatchMargin(units,side,reference);
        if(RP.C.SafetyFraction<1&&units>=Symbol.VolumeInUnitsMin)
            units=Math.Min(units,Math.Max(Symbol.VolumeInUnitsMin,Symbol.NormalizeVolumeInUnits(units*RP.C.SafetyFraction,RoundingMode.Down)));
        if(units<Symbol.VolumeInUnitsMin||units*valuePerUnit<.01)return true;
        units=Math.Min(units,Symbol.VolumeInUnitsMax);
        state.Expiry=s.At.AddHours(side>0?RP.C.BtcBuyHours:RP.C.BtcSellHours);
        if(weekClose.HasValue)state.Expiry=new[]{state.Expiry,weekClose.Value.AddMinutes(-BtcWeekendPolicy.FlattenMinutes)}.Min();
        if(!replay&&!EnsureNativeIntent(1,ref units,reference))return false;
        if(replay){state.Sending=true;Save();}
        var result=ExecuteMarketOrder(side>0?TradeType.Buy:TradeType.Sell,Instrument,units,Prefix+"|"+s.At.Ticks,dist/Symbol.PipSize,dist*(side>0?RP.C.BtcBuyTarget:RP.C.BtcSellTarget)/Symbol.PipSize,"BTC8500283");
        if(!result.IsSuccessful||result.Position==null){state.Fault=true;throw new Exception("BTC_ORDER_NOT_CONFIRMED");}
        if(result.Position!=null){var p=result.Position;if(!replay&&!NativeResultOwned(p)){state.Fault=true;Save();Print("R3_BTC_FOREIGN_RESULT_NO_CLOSE");return true;}
            if(p.StopLoss==null||p.TakeProfit==null||!Host.BtcFillWithinBudget(this,p,reference,dist,valuePerUnit)||expand&&!BatchWithinBudget()||!replay&&!NativeFillIdentityOk(p)){state.ExitPending=true;state.ExitReason="FILL_PROTECTION_OR_BUDGET";Save();var close=ClosePosition(p);if(!close.IsSuccessful)state.Fault=true;else{state.ExitPending=false;state.ExitReason="";}}}
        if(!replay){ClearNativeIntent();state.Sending=false;if(!expand)state.BatchSent=1;}
        if(replay){state.Sending=false;Save();}
        if(expand&&!state.Fault&&!state.ExitPending&&Owned.Any(p=>p.Id==result.Position!.Id)){state.BatchSent=1;state.BatchRemaining=RP.C.BtcBatchOrders-1;state.BatchNext=Server.TimeInUtc.AddSeconds(1);Save();}
        return true;
    }
    double BatchReference=>Math.Min(state.BatchBalance,Math.Min(Account.Balance,Account.Equity));
    double BatchOpenRisk(){double value=Symbol.PipValue/Symbol.PipSize;return Owned.Sum(p=>p.VolumeInUnits*value*Math.Max(0,(p.TradeType==TradeType.Buy?1:-1)*(p.EntryPrice-p.StopLoss!.Value))+Math.Max(p.VolumeInUnits*value*p.EntryPrice*.0012,2*Math.Abs(p.Commissions)+p.VolumeInUnits*value*p.EntryPrice*.0002));}
    double BatchMargin()=>Owned.Sum(p=>Symbol.GetEstimatedMargin(p.TradeType,p.VolumeInUnits));
    bool BatchWithinBudget()=>BatchReference>0&&BatchOpenRisk()<=BatchReference*RP.C.BtcBatchRisk+1e-8&&BatchMargin()<=BatchReference*RP.C.BtcBatchMargin+1e-8;
    void ValidateBatchConfig(){if(RP.C.BtcBatchOrders<2||RP.C.BtcBatchOrders>128||RP.C.BtcBatchSeconds<1||RP.C.BtcBatchSeconds>1800||!double.IsFinite(RP.C.BtcBatchRisk)||RP.C.BtcBatchRisk<=0||RP.C.BtcBatchRisk>.2075||!double.IsFinite(RP.C.BtcBatchMargin)||RP.C.BtcBatchMargin<=0||RP.C.BtcBatchMargin>.5||!double.IsFinite(RP.C.BtcBatchZone)||RP.C.BtcBatchZone<=0)throw new InvalidOperationException("INVALID_RESEARCH_BATCH_CONFIG");}
    void CancelResearchQueue(){if(state.BatchRemaining<=0)return;state.BatchRemaining=0;if(!replay&&state.NativePendingSequence>1){ClearNativeIntent();state.Sending=false;}Save();}
    double CapBatchMargin(double units,int side,double reference){long lo=0,hi=(long)Math.Floor(units/Symbol.VolumeInUnitsStep+1e-10);double cap=Math.Max(0,Math.Min(reference,Account.Equity)*RP.C.BtcBatchMargin-BatchMargin());while(lo<hi){long m=lo+(hi-lo+1)/2;double margin=Symbol.GetEstimatedMargin(side>0?TradeType.Buy:TradeType.Sell,m*Symbol.VolumeInUnitsStep);if(double.IsFinite(margin)&&margin>0&&margin<=cap)lo=m;else hi=m-1;}return lo*Symbol.VolumeInUnitsStep;}
    void ProcessResearchBatch(DateTime now){
        if(!ResearchBatchQueued)return;
        if(now>=state.BatchDeadline||state.Fault||!Owned.Any()||Owned.Count()<state.BatchSent||!BatchWithinBudget()){CancelResearchQueue();return;}
        if(now<state.BatchNext||!Host.EnableTrading||!marketOpen||state.ExitPending)return;
        if(!replay&&(link==null||!link.Healthy||link.Fatal||!feed.Fresh(now)||!link.Persisted(state.Revision)))return;
        if(!BtcWeekendPolicy.CanEnter(now,weekClose,marketOpen,state.WeekendLockUntil)){CancelResearchQueue();return;}
        int side=state.BatchSide;double quote=side>0?Symbol.Ask:Symbol.Bid,fill=quote+side*Symbol.Bid*.0001;
        if(Math.Abs(fill-state.BatchSignalReference)>RP.C.BtcBatchZone*state.BatchAtr)return;
        double dist=(side>0?RP.C.BtcBuyStop:RP.C.BtcSellStop)*state.BatchAtr,value=Symbol.PipValue/Symbol.PipSize;
        double available=Math.Max(0,BatchReference*RP.C.BtcBatchRisk-BatchOpenRisk());
        if(!double.IsFinite(fill)||fill<=0||dist<=0||fill-side*dist<=0||value<=0){CancelResearchQueue();return;}
        double units=Math.Min(100/value,available/(value*(dist+.0012*fill)));units=Symbol.NormalizeVolumeInUnits(units,RoundingMode.Down);
        units=Host.CapBtc(this,units,dist,fill,side,value);units=CapBatchMargin(units,side,BatchReference);
        if(RP.C.SafetyFraction<1&&units>=Symbol.VolumeInUnitsMin)units=Math.Min(units,Math.Max(Symbol.VolumeInUnitsMin,Symbol.NormalizeVolumeInUnits(units*RP.C.SafetyFraction,RoundingMode.Down)));
        units=Math.Min(units,Symbol.VolumeInUnitsMax);
        if(units<Symbol.VolumeInUnitsMin||units*value<.01){CancelResearchQueue();return;}
        double reference=BatchReference;if(!replay&&!EnsureNativeIntent(state.BatchSent+1,ref units,reference))return;if(replay){state.Sending=true;Save();}
        TradeResult result;
        try{result=ExecuteMarketOrder(side>0?TradeType.Buy:TradeType.Sell,Instrument,units,Prefix+"|"+state.LastSignal.Ticks+"|B"+(state.BatchSent+1),dist/Symbol.PipSize,dist*(side>0?RP.C.BtcBuyTarget:RP.C.BtcSellTarget)/Symbol.PipSize,"RESEARCH_BTC_BATCH");}
        catch{state.Fault=true;Save();throw;}
        if(!result.IsSuccessful||result.Position==null){state.Fault=true;Save();throw new InvalidOperationException("BTC_BATCH_ORDER_UNCONFIRMED");}
        var p=result.Position;if(!replay&&!NativeFillIdentityOk(p)){state.Fault=true;state.ExitPending=true;state.ExitReason="NATIVE_FILL_IDENTITY";Save();if(NativeResultOwned(p))ClosePosition(p);return;}state.BatchSent++;state.BatchRemaining--;state.BatchNext=Server.TimeInUtc.AddSeconds(1);state.Sending=false;if(!replay)ClearNativeIntent();Save();
        if(p.StopLoss==null||p.TakeProfit==null||!Host.BtcFillWithinBudget(this,p,reference,dist,value)||!BatchWithinBudget()){
            CancelResearchQueue();var close=ClosePosition(p);if(!close.IsSuccessful){state.Fault=true;state.ExitPending=true;state.ExitReason="BATCH_BUDGET_CLOSE_RETRY";Save();}
        }
    }

    public override void OnStop(){try{if(ready)Save();}finally{link?.Dispose();}}
}
