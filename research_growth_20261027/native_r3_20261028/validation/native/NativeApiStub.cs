using System;using System.Linq;
using System.Collections.Generic;
using cAlgo.API.Internals;
namespace cAlgo.API {
[AttributeUsage(AttributeTargets.Property)] public class ParameterAttribute:Attribute {public ParameterAttribute(string name){} public object DefaultValue{get;set;} public string Group{get;set;}="";public bool IsValueVisibleInTitle{get;set;}=true; public double MinValue{get;set;} public double MaxValue{get;set;} }
public enum TradeType {Buy,Sell} public enum RoundingMode {Down} public enum ProtectionType {Absolute} public enum LocalStorageScope {Instance}
public class Asset {public string Name{get;set;}="USD";}
public class Account {public AccountType AccountType{get;set;}=AccountType.Hedged;public Asset Asset{get;}=new();public double Equity{get;set;}=100;public double Balance{get;set;}=100;public double Margin{get;set;} public double FreeMargin=>Equity-Margin; public long Number{get;set;}=1237903;public bool IsLive{get;set;} public double PreciseLeverage{get;set;}=200;}
public class Position {public DateTime EntryTime{get;set;} public string SymbolName{get;set;}="XAUUSD";public string Label{get;set;}="";public string Comment{get;set;}="";public int Id{get;set;} public double VolumeInUnits{get;set;} public double EntryPrice{get;set;} public TradeType TradeType{get;set;} public double? StopLoss{get;set;} public double? TakeProfit{get;set;} public double Commissions{get;set;} public double Swap{get;set;} public double NetProfit{get;set;} }
public class HistoricalTrade {public DateTime EntryTime{get;set;} public double GrossProfit{get;set;} public double ExitCommission{get;set;} public double ExitPrice{get;set;} public DateTime ClosingTime{get;set;} public string Comment{get;set;}="";public string SymbolName{get;set;}="XAUUSD";public string Label{get;set;}="";public long PositionId{get;set;} public double EntryPrice{get;set;} public double VolumeInUnits{get;set;} public TradeType TradeType{get;set;} public double Commissions{get;set;} public double Swap{get;set;} public double NetProfit{get;set;} }
public class TradeResult {public bool IsSuccessful{get;set;}=true;public Position? Position{get;set;} public string Error{get;set;}="TEST";}
public class Clock {public DateTime TimeInUtc{get;set;}=new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc);}
public class TimerObject {public void Start(TimeSpan t){} }
public class Store {public bool FailWrite,FailFlush,CorruptRead;public Dictionary<string,string> Values{get;}=new();public string? GetString(string k,LocalStorageScope s)=>CorruptRead?"corrupt":Values.GetValueOrDefault(k);public void SetString(string k,string v,LocalStorageScope s){if(FailWrite)throw new InvalidOperationException("WRITE_FAILURE");if(k.Length>50||k.Trim()!=k||k.Any(c=>!(c>='a'&&c<='z'||c>='A'&&c<='Z'||c>='0'&&c<='9'||c==' ')))throw new ArgumentException("INVALID_STORAGE_KEY");Values[k]=v;}public void Flush(LocalStorageScope s){if(FailFlush)throw new InvalidOperationException("FLUSH_FAILURE");} }
public class TimeFrame {public static TimeFrame Minute{get;}=new();public static TimeFrame Hour{get;}=new();public static TimeFrame Hour4{get;}=new();}
public class Bars {public List<DateTime> OpenTimes{get;}=new();public List<double> OpenPrices{get;}=new();public List<double> HighPrices{get;}=new();public List<double> LowPrices{get;}=new();public List<double> ClosePrices{get;}=new();public int Count=>OpenTimes.Count; public int LoadMoreHistory()=>0;}
public class MarketDataObject {public Func<TimeFrame,string,Bars>? Provider;public Bars GetBars(TimeFrame t,string s)=>Provider?.Invoke(t,s)??new();}
public class TextEvent {public string Text{get;set;}="";}
public class WebSocketClient:IDisposable {public event Action<TextEvent>? TextReceived;public event Action<object>? Disconnected;public void Connect(Uri u){} public List<string> Sent{get;}=new();public void Send(string s){Sent.Add(s);}public void Emit(string text)=>TextReceived?.Invoke(new(){Text=text});public void Drop()=>Disconnected?.Invoke(new());public void Dispose(){} }
public abstract class Robot {
 public IAccount Account{get;}=new();public SymbolsCollection Symbols{get;}=new();public Symbol Symbol=>Symbols.GetSymbol(SymbolName);public string SymbolName{get;set;}="XAUUSD";public List<Position> Positions{get;}=new();public List<HistoricalTrade> History{get;}=new();public List<object> PendingOrders{get;}=new();public IServer Server{get;}=new();public LocalStorage LocalStorage{get;}=new();public TimerObject Timer{get;}=new();public MarketData MarketData{get;}=new();public Action? BeforeMarketFill;public int Requests,Closes;public bool Reject,FailProtection,FailClose;public double ExtraSlip=.05,ExtraFee;public double FeeFactor=1;public double ReturnVolumeFactor=1;public double LastVolume;
 protected virtual void OnStart(){}protected virtual void OnTick(){}protected virtual void OnTimer(){}protected virtual void OnStop(){}public bool Stopped;public void Stop(){Stopped=true;}public void Print(string s,params object[] o){}public void BeginInvokeOnMainThread(Action a)=>a();

 protected TradeResult ExecuteMarketOrder(TradeType side,string symbol,double volume,string label,double sl,double tp,string comment){
  Requests++;BeforeMarketFill?.Invoke();LastVolume=volume;var sym=Symbols.GetSymbol(symbol);double slip=(symbol=="BTCUSD"?sym.Bid*.0001:symbol=="XAUUSD"?.05:.00001)*FeeFactor,feeUnit=(symbol=="BTCUSD"?((side==TradeType.Buy?sym.Ask:sym.Bid)+ (side==TradeType.Buy?1:-1)*slip)*.0005:symbol=="XAUUSD"?.03:.00003)*FeeFactor;
  if(Reject)return new(){IsSuccessful=false};double quote=side==TradeType.Buy?sym.Ask:sym.Bid;int sign=side==TradeType.Buy?1:-1;double entry=quote+sign*slip;double actualVolume=volume*ReturnVolumeFactor;
  if(sym.GetEstimatedMargin(side,volume)+actualVolume*feeUnit>Account.FreeMargin)return new(){IsSuccessful=false,Error="BROKER_MARGIN"};
  var pos=new Position{EntryTime=Server.TimeInUtc,Id=Requests,SymbolName=symbol,Label=label,VolumeInUnits=actualVolume,TradeType=side,EntryPrice=entry,StopLoss=entry-sign*sl*sym.PipSize,TakeProfit=entry+sign*tp*sym.PipSize,Comment=comment,Commissions=-actualVolume*feeUnit};
  Positions.Add(pos);Account.Balance-=actualVolume*feeUnit;Mark();return new(){Position=pos};
 }
 protected TradeResult ModifyPosition(Position p,double sl,double tp,ProtectionType t){if(FailProtection)return new(){IsSuccessful=false};p.StopLoss=sl;p.TakeProfit=tp;return new(){Position=p};}
 public TradeResult ClosePosition(Position p){Closes++;if(FailClose)return new(){IsSuccessful=false};var sym=Symbols.GetSymbol(p.SymbolName);double slip=(p.SymbolName=="BTCUSD"?sym.Bid*.0001:p.SymbolName=="XAUUSD"?.05:.00001)*FeeFactor,feeUnit=(p.SymbolName=="BTCUSD"?((p.TradeType==TradeType.Buy?sym.Bid:sym.Ask)-(p.TradeType==TradeType.Buy?1:-1)*slip)*.0005:p.SymbolName=="XAUUSD"?.03:.00003)*FeeFactor;
  int sign=p.TradeType==TradeType.Buy?1:-1;double exit=(sign==1?sym.Bid:sym.Ask)-sign*slip;double pnl=sign*p.VolumeInUnits*(exit-p.EntryPrice)-p.VolumeInUnits*feeUnit;
  Account.Balance+=pnl;Positions.Remove(p);History.Add(new(){EntryTime=p.EntryTime,GrossProfit=sign*p.VolumeInUnits*(exit-p.EntryPrice),ExitCommission=-p.VolumeInUnits*feeUnit,ExitPrice=exit,ClosingTime=Server.TimeInUtc,SymbolName=p.SymbolName,Label=p.Label,PositionId=p.Id,EntryPrice=p.EntryPrice,VolumeInUnits=p.VolumeInUnits,TradeType=p.TradeType,Commissions=p.Commissions,Comment=p.Comment,NetProfit=pnl+p.Commissions+p.Swap,Swap=p.Swap});Mark();return new(){Position=p};
 }
 public void Mark(){Account.Equity=Account.Balance+Positions.Sum(p=>{var sym=Symbols.GetSymbol(p.SymbolName);return (p.TradeType==TradeType.Buy?1:-1)*p.VolumeInUnits*((p.TradeType==TradeType.Buy?sym.Bid:sym.Ask)-p.EntryPrice);});Account.Margin=Positions.Sum(p=>Symbols.GetSymbol(p.SymbolName).GetEstimatedMargin(p.TradeType,p.VolumeInUnits));}

}
}

namespace cAlgo.API.Internals {
public enum AccountType {Hedged}
public class IAccount:cAlgo.API.Account {}
public class IServer:cAlgo.API.Clock {}
public class MarketData:cAlgo.API.MarketDataObject {}
public class SymbolsCollection {readonly Dictionary<string,Symbol> items=new();public Symbol GetSymbol(string name){if(!items.TryGetValue(name,out var s))items[name]=s=new Symbol{Name=name};return s;}}
public class MarketHours {public Func<DateTime,bool> Calendar=t=>t.DayOfWeek!=DayOfWeek.Saturday&&t.DayOfWeek!=DayOfWeek.Sunday&&(t.DayOfWeek!=DayOfWeek.Friday||t.TimeOfDay<TimeSpan.FromHours(22));public bool IsOpened(DateTime t)=>Calendar(t);}
public class Symbol {public MarketHours MarketHours{get;}=new();public string Name{get;set;}="XAUUSD";public double Ask{get;set;}=1.10001;public double Bid{get;set;}=1.1;public double PipValue=>PipSize;public double TickSize=>Name=="BTCUSD"?.01:Name=="XAUUSD"?.01:.00001;public double PipSize=>Name=="BTCUSD"?.01:Name=="XAUUSD"?.01:.0001;public double VolumeInUnitsMin=>Name=="BTCUSD"?.01:Name=="XAUUSD"?1:1000;public double VolumeInUnitsMax=>Name=="BTCUSD"?100:Name=="XAUUSD"?2000:2000000;public double VolumeInUnitsStep=>VolumeInUnitsMin;public double Leverage{get;set;}=200;
public double QuantityToVolumeInUnits(double lots)=>lots*(Name=="XAUUSD"?100:100000);public double VolumeInUnitsToQuantity(double volume)=>volume/(Name=="XAUUSD"?100:100000);public double NormalizeVolumeInUnits(double v,cAlgo.API.RoundingMode m)=>Math.Floor(v/VolumeInUnitsStep)*VolumeInUnitsStep;public double GetEstimatedMargin(cAlgo.API.TradeType t,double v)=>v*Ask/Leverage;public event Action<cAlgo.API.SymbolTickEventArgs>? Tick;public void Emit()=>Tick?.Invoke(new());}
}
namespace cAlgo.API {
public class LocalStorage:Store {}
public class SymbolTickEventArgs {}
public class RobotAttribute:Attribute{public string TimeZone{get;set;}="UTC";public AccessRights AccessRights{get;set;}}
public enum AccessRights{None}
public static class TimeZones {public const string UTC="UTC";}
}
