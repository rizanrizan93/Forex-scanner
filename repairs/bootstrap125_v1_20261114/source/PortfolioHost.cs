using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using cAlgo.API.Internals;

namespace Rizan.Portfolio;

internal abstract class EngineContext
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
    protected bool IsCloudRuntime=>Host.IsCloudRuntime;
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
    protected override Xau.FrozenContract Contract=>RP.X(Xau.FrozenContract.Xau) with {ReferenceLeverage=200};
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


