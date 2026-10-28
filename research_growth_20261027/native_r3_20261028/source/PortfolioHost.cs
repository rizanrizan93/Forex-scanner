using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using cAlgo.API.Internals;

namespace Rizan.Portfolio;

// One cTrader Robot owns the account, timer and order API. Strategy contexts do not
// create or simulate a second broker account.
public abstract class RizanPortfolio : Robot
{
    [Parameter("Kirim order", DefaultValue=false, Group="Eksekusi")]
    public bool EnableTrading { get; set; }
    [Parameter("Nomor akun penuh", DefaultValue="", Group="Eksekusi")]
    public string ExpectedAccount { get; set; } = "";
    [Parameter("XAU aktif", DefaultValue=true, Group="Strategi")]
    public bool EnableXau { get; set; } = true;
    [Parameter("EUR aktif", DefaultValue=true, Group="Strategi")]
    public bool EnableEur { get; set; } = true;
    [Parameter("Batas risiko terbuka gabungan %", DefaultValue=20.75, MinValue=20.75, MaxValue=20.75, Group="Portofolio")]
    public double PortfolioRiskPercent { get; set; } = 20.75;
    [Parameter("Bridge WSS :25345", DefaultValue="", Group="Pemulihan dan data")]
    public string BridgeUrl { get; set; } = "";
    [Parameter("Token bridge", DefaultValue="", IsValueVisibleInTitle=false, Group="Pemulihan dan data")]
    public string BridgeToken { get; set; } = "";
    [Parameter("BTC 7D WSS :25345", DefaultValue="", Group="Pemulihan dan data")]
    public string BtcBridgeUrl {get;set;}="";
    [Parameter("Token BTC 7D", DefaultValue="", IsValueVisibleInTitle=false, Group="Pemulihan dan data")]
    public string BtcBridgeToken {get;set;}="";
    internal XauEngine? Xau { get; private set; }
    [Parameter("BTC aktif", DefaultValue=true, Group="Strategi")]
    public bool EnableBtc {get;set;}=true;
    internal BtcEngine? Btc {get;private set;}
    internal EurEngine? Eur { get; private set; }
    internal IEnumerable<EngineContext> Engines => new EngineContext?[]{Eur,Xau,Btc}.OfType<EngineContext>();
    internal bool PortfolioReady => !_shuttingDown && Engines.Any() && Engines.All(e=>e.RecoveryReady) && (Xau==null||Xau.BridgeEntryHealthy) && (Eur==null||Eur.BridgeEntryHealthy);
    public long PortfolioBudgetBlocks { get; private set; }
#if REPLAY
    // Isolated-source parity controls only; absent from the native cBot build.
    internal bool BypassSharedChecks;
#endif
    private DateTime _nextTelemetry;
    private bool _running;
    private bool _shuttingDown;

    internal void CreateEngines()
    {
        if(EnableXau)Xau=new XauEngine(this);
        if(EnableEur)Eur=new EurEngine(this);
        if(EnableBtc)Btc=new BtcEngine(this);
        foreach(var e in Engines)e.SetParameters();
    }
    protected override void OnStart()
    {
        ExpectedAccount=ExpectedAccount.Trim();
#if !REPLAY
        if(!FrozenR3.Matches()||!EnableXau||!EnableEur||!EnableBtc){Print("R3_FROZEN_PROFILE_MISMATCH all_three_instruments_required=True");Stop();return;}
        foreach(var name in new[]{"XAUUSD","EURUSD","BTCUSD"}){
            var symbol=Symbols.GetSymbol(name);
            if(symbol==null){Print("R3_BROKER_SYMBOL_MISSING symbol={0}",name);Stop();return;}
            if(!double.IsFinite(symbol.PipSize)||symbol.PipSize<=0||!double.IsFinite(symbol.PipValue)||symbol.PipValue<=0||symbol.VolumeInUnitsStep<=0){Print("R3_BROKER_CONTRACT_INVALID symbol={0}",name);Stop();return;}
        }
        Print("R3_FROZEN_PROFILE id={0} config_sha256={1} account={2} trading={3}",FrozenR3.ProfileId,FrozenR3.ConfigSha256,Account.Number,EnableTrading);
#endif
        if(!double.IsFinite(PortfolioRiskPercent)||Math.Abs(PortfolioRiskPercent-20.75)>1e-9||!EnableXau&&!EnableEur&&!EnableBtc)
        {Print("PORTFOLIO_CONFIG_INVALID");Stop();return;}
        if(EnableTrading&&(ExpectedAccount!=Account.Number.ToString()||(!BtcStateLink.ValidUrl(BridgeUrl)||BridgeToken.Length<32)||EnableBtc&&(!BtcStateLink.ValidUrl(BtcBridgeUrl)||BtcBridgeToken.Length<32)))
        {Print("PORTFOLIO_FULL_ACCOUNT_AND_BRIDGE_REQUIRED");Stop();return;}
        if(Account.AccountType!=AccountType.Hedged||Account.Asset.Name!="USD")
        {Print("PORTFOLIO_USD_HEDGED_ACCOUNT_REQUIRED");Stop();return;}
        var settings=JsonSerializer.Serialize(new{Schema=1,Release="7D130",BtcFeed=BtcSevenDayFeed.Contract,Account=Account.Number,Risk=PortfolioRiskPercent,Margin=.5,XAU=EnableXau,EUR=EnableEur,BTC=EnableBtc});
        var key=FrozenR3.PortfolioStorageKey(Account.Number);
        var saved=LocalStorage.GetString(key,LocalStorageScope.Instance);
        if(!string.IsNullOrEmpty(saved)&&saved!=settings){Print("PORTFOLIO_SETTINGS_CHECKPOINT_MISMATCH");Stop();return;}
        LocalStorage.SetString(key,settings,LocalStorageScope.Instance);LocalStorage.Flush(LocalStorageScope.Instance);
        CreateEngines();
        try { foreach(var e in Engines)e.OnStart(); }
        catch(Exception ex){Print("PORTFOLIO_ENGINE_START_ERROR {0}",ex.Message);StopEngines();Stop();return;}
        if(Engines.Any(e=>e.Stopped)){StopEngines();Print("PORTFOLIO_ENGINE_START_FAILED");Stop();return;}
        if(Xau!=null)Symbols.GetSymbol("XAUUSD").Tick+=XauTick;
        if(Eur!=null)Symbols.GetSymbol("EURUSD").Tick+=EurTick;
        if(Btc!=null)Symbols.GetSymbol("BTCUSD").Tick+=BtcTick;
        _running=true;Timer.Start(TimeSpan.FromSeconds(1));
        Print("RIZAN_PORTFOLIO_START version=1.3.0-frozen-7day-weekend XAU=RC1_1.3.0 EUR=F0245_1.2.1 BTC=8500283 account={0} risk_cap={1}% margin_cap=50%",Account.Number,PortfolioRiskPercent);
    }
    private void XauTick(SymbolTickEventArgs e){if(_running)Xau?.OnTick();}
    private void BtcTick(SymbolTickEventArgs e){if(_running)Btc?.OnTick();}
    private void EurTick(SymbolTickEventArgs e){if(_running)Eur?.OnTick();}
    protected override void OnTimer()
    {
#if !REPLAY
        try {
#endif
        if(!_running)return;
        Btc?.Manage(Server.TimeInUtc); // Friday safety runs before strategy/bridge work.
        // Stable EUR -> XAU order; no winner is selected using future prices.
        foreach(var e in Engines)if(!e.Stopped)e.OnTimer();
        if(Server.TimeInUtc>=_nextTelemetry){_nextTelemetry=Server.TimeInUtc.AddMinutes(1);Print("RIZAN_PORTFOLIO ready={0} balance={1} equity={2} margin={3} open_risk={4} pending_risk={5} budget_blocks={6}",PortfolioReady,Account.Balance,Account.Equity,Account.Margin,OpenRisk(),Engines.Sum(e=>e.PendingRisk),PortfolioBudgetBlocks);}
#if !REPLAY
        }catch(Exception ex){Btc?.NativeRuntimeFault(ex);Print("R3_PORTFOLIO_TIMER_BLOCK type={0}",ex.GetType().Name);}
#endif
    }
    protected override void OnStop()
    {
        _shuttingDown=true;
        _running=false;
        if(Xau!=null)Symbols.GetSymbol("XAUUSD").Tick-=XauTick;
        if(Eur!=null)Symbols.GetSymbol("EURUSD").Tick-=EurTick;
        if(Btc!=null)Symbols.GetSymbol("BTCUSD").Tick-=BtcTick;
        StopEngines();
    }
    private void StopEngines()
    {
        _shuttingDown=true;
        foreach(var e in Engines)e.MarkStopped();
        foreach(var e in Engines)try{e.OnStop();}catch(Exception ex){Print("PORTFOLIO_ENGINE_STOP_ERROR {0} {1}",e.Instrument,ex.Message);}
    }
    internal bool NoForeignExposure() => !PendingOrders.Any() && Positions.All(p=>
        EnableXau&&p.SymbolName=="XAUUSD"&&p.Label?.StartsWith(FrozenR3.XauPrefix+"|",StringComparison.Ordinal)==true ||
        EnableEur&&p.SymbolName=="EURUSD"&&p.Label?.StartsWith(FrozenR3.EurPrefix+"|",StringComparison.Ordinal)==true ||
        EnableBtc&&p.SymbolName=="BTCUSD"&&p.Label?.StartsWith(BtcEngine.Prefix+"|",StringComparison.Ordinal)==true);
    internal double OpenRisk()
    {
        double risk=0;
        foreach(var p in Positions){if(p.StopLoss==null)return double.PositiveInfinity;
            double sign=p.TradeType==TradeType.Buy?1:-1;
            double reserve=p.SymbolName=="BTCUSD"?p.EntryPrice*.0012:p.SymbolName=="XAUUSD"?.16:.00004;
            double value=Symbols.GetSymbol(p.SymbolName).PipValue/Symbols.GetSymbol(p.SymbolName).PipSize;
            risk+=p.VolumeInUnits*value*(Math.Max(0,sign*(p.EntryPrice-p.StopLoss.Value))+reserve);
        }
        return risk;
    }
    internal int CapQuantity(EngineContext caller,int requested,double perChildRisk,double childUnits,int side,double quote,double spread)
    {
#if REPLAY
        if(BypassSharedChecks)return requested;
#endif
        if(requested<=0||!PortfolioReady||!NoForeignExposure()||!double.IsFinite(perChildRisk)||perChildRisk<=0)return 0;
        double otherRisk=Engines.Where(e=>e!=caller).Sum(e=>e.PendingRisk);
        double otherMargin=Engines.Where(e=>e!=caller).Sum(e=>e.PendingMargin);
        double openRisk=OpenRisk();var symbol=Symbols.GetSymbol(caller.Instrument);
        double fee=caller.Instrument=="XAUUSD"?.06:.03;
        double slip=caller.Instrument=="XAUUSD"?.10:.00001;
        int lo=0,hi=requested;
        while(lo<hi){int q=lo+(hi-lo+1)/2;
            double cost=q*(childUnits*(spread+slip)+fee),reference=Math.Min(Account.Balance,Account.Equity-cost);
            double margin=symbol.GetEstimatedMargin(side==1?TradeType.Buy:TradeType.Sell,q*childUnits);
            if(reference>0&&openRisk+otherRisk+q*perChildRisk<=reference*PortfolioRiskPercent/100+1e-8&&ReservedMargin()+otherMargin+margin<=reference*.5+1e-8&&Account.FreeMargin>=otherMargin+margin+cost)lo=q;else hi=q-1;
        }
        if(lo<requested)PortfolioBudgetBlocks++;
        return lo;
    }
    
    internal double ResearchBtcMargin(Position p)=>Symbols.GetSymbol("BTCUSD").GetEstimatedMargin(p.TradeType,p.VolumeInUnits);
    internal double ReservedMargin()=>Account.Margin;
    internal double CapBtc(EngineContext caller,double units,double distance,double price,int side,double value)
    {
        if(!PortfolioReady||!NoForeignExposure())return 0;
        var sym=Symbols.GetSymbol("BTCUSD");double reference=Math.Min(Account.Balance,Account.Equity);
        double pendingRisk=Engines.Where(e=>e!=caller).Sum(e=>e.PendingRisk),pendingMargin=Engines.Where(e=>e!=caller).Sum(e=>e.PendingMargin);
        double riskAvailable=Math.Max(0,reference*PortfolioRiskPercent/100-OpenRisk()-pendingRisk);
        double marginAvailable=Math.Max(0,reference*.5-ReservedMargin()-pendingMargin);
        units=Math.Min(units,riskAvailable/(value*(distance+price*.0012)));
        // Follow broker-estimated symbol margin, as XAU/EUR do. No fixed BTC leverage floor.
        long lo=0,hi=(long)Math.Floor(units/sym.VolumeInUnitsStep);
        double costUnit=value*(sym.Ask-sym.Bid+price*.0006);
        while(lo<hi){long mid=lo+(hi-lo+1)/2;double q=mid*sym.VolumeInUnitsStep;
            double after=reference-q*costUnit;
            double margin=sym.GetEstimatedMargin(side>0?TradeType.Buy:TradeType.Sell,q);
            if(double.IsFinite(margin)&&margin>0&&after>0&&OpenRisk()+pendingRisk+q*value*(distance+price*.0012)<=after*PortfolioRiskPercent/100&&margin<=marginAvailable&&margin+q*value*price*.0005<=reference*(side>0?.95:.30)&&ReservedMargin()+pendingMargin+margin<=after*.5&&margin+q*value*price*.0005<=Account.FreeMargin-pendingMargin)lo=mid;else hi=mid-1;
        }
        units=lo*sym.VolumeInUnitsStep;
        return Math.Max(0,units);
    }
    internal bool BtcFillWithinBudget(EngineContext caller,Position p,double reference,double distance,double value)=>
        p.StopLoss!=null&&p.TakeProfit!=null&&OpenRisk()+Engines.Where(e=>e!=caller).Sum(e=>e.PendingRisk)<=Math.Min(reference,Math.Min(Account.Balance,Account.Equity))*PortfolioRiskPercent/100+1e-8&&ReservedMargin()+Engines.Where(e=>e!=caller).Sum(e=>e.PendingMargin)<=Math.Min(reference,Math.Min(Account.Balance,Account.Equity))*.5+1e-8;

    internal TradeResult Send(TradeType side,string symbol,double units,string label,double sl,double tp,string comment){if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");return ExecuteMarketOrder(side,symbol,units,label,sl,tp,comment);}
    internal TradeResult Protect(Position p,double sl,double tp,ProtectionType type){if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");return ModifyPosition(p,sl,tp,type);}
    internal TradeResult Close(Position p){if(!EnableTrading)throw new InvalidOperationException("TRADING_DISABLED");return ClosePosition(p);}
    internal void Dispatch(Action action)=>BeginInvokeOnMainThread(action);
    internal void Log(string format,params object[] values)=>Print(format,values);
}

public abstract class EngineContext
{
    internal readonly RizanPortfolio Host;
    internal string Instrument { get; }
    internal bool Stopped { get; private set; }
    protected EngineContext(RizanPortfolio host,string instrument){Host=host;Instrument=instrument;}
    protected IAccount Account=>Host.Account;
    protected Symbol Symbol=>Host.Symbols.GetSymbol(Instrument);
    protected string SymbolName=>Instrument;
    protected IEnumerable<Position> Positions=>Host.Positions;
    protected IEnumerable<HistoricalTrade> History=>Host.History;
    protected IEnumerable<object> PendingOrders=>Host.PendingOrders.Cast<object>();
    protected IServer Server=>Host.Server;
    protected MarketData MarketData=>Host.MarketData;
    protected LocalStorage LocalStorage=>Host.LocalStorage;
    protected void Print(string format,params object[] values)=>Host.Log(format,values);
    protected void BeginInvokeOnMainThread(Action action)=>Host.Dispatch(action);
    protected void Stop()=>Stopped=true;
    internal void MarkStopped()=>Stopped=true;
    protected TradeResult ExecuteMarketOrder(TradeType side,string symbol,double units,string label,double sl,double tp,string comment)=>Host.Send(side,symbol,units,label,sl,tp,comment);
    protected TradeResult ModifyPosition(Position p,double sl,double tp,ProtectionType type)=>Host.Protect(p,sl,tp,type);
    protected TradeResult ClosePosition(Position p)=>Host.Close(p);
    public virtual void OnStart(){}
    public virtual void OnTick(){}
    public virtual void OnTimer(){}
    public virtual void OnStop(){}
    internal abstract bool RecoveryReady { get; }
    internal abstract double PendingRisk { get; }
    internal abstract double PendingMargin { get; }
    internal abstract string PendingOrderLabel { get; }
    internal abstract void SetParameters();
}

internal sealed class XauEngine : Xau.RizanRobot
{
    internal XauEngine(RizanPortfolio host):base(host,"XAUUSD"){}
    protected override Xau.FrozenContract Contract=>RP.X(Xau.FrozenContract.Xau);
    protected override string Prefix=>FrozenR3.XauPrefix;
    protected override string LoginSuffix=>Host.ExpectedAccount.Length>=4?Host.ExpectedAccount[^4..]:Host.ExpectedAccount;
    internal override void SetParameters(){EnableTrading=Host.EnableTrading;ExpectedAccount=Host.ExpectedAccount;BridgeUrl=Host.BridgeUrl;BridgeToken=Host.BridgeToken;ChildrenPerSecond=1;}
}
internal sealed class EurEngine : Eur.RizanRobot
{
    internal EurEngine(RizanPortfolio host):base(host,"EURUSD"){}
    protected override Eur.FrozenContract Contract=>Eur.F0245Policy.Contract;
    protected override string Prefix=>FrozenR3.EurPrefix;
    protected override string LoginSuffix=>Host.ExpectedAccount.Length>=4?Host.ExpectedAccount[^4..]:Host.ExpectedAccount;
    internal override void SetParameters(){EnableTrading=Host.EnableTrading;ExpectedAccount=Host.ExpectedAccount;BridgeUrl=Host.BridgeUrl;BridgeToken=Host.BridgeToken;}
}
