using System;
using System.Collections.Generic;
using cAlgo.API.Internals;
namespace cAlgo.API {
[AttributeUsage(AttributeTargets.Property)] public class ParameterAttribute:Attribute {public ParameterAttribute(string name){} public object DefaultValue{get;set;} public string Group{get;set;}=""; public int MinValue{get;set;} public int MaxValue{get;set;} }
public enum AccountType {Hedged} public enum TradeType {Buy,Sell} public enum RoundingMode {Down} public enum ProtectionType {Absolute} public enum LocalStorageScope {Instance}
public class Asset {public string Name{get;set;}="USD";}
public class Account {public AccountType AccountType{get;set;}=AccountType.Hedged;public Asset Asset{get;}=new();public double Equity{get;set;}=100;public double Balance{get;set;}=100;public double Margin{get;set;} public double FreeMargin=>Equity-Margin; public long Number{get;set;}=1237903;public bool IsLive{get;set;} public double PreciseLeverage{get;set;}=200;}
public class Position {public string SymbolName{get;set;}="XAUUSD";public string Label{get;set;}="";public string Comment{get;set;}="";public int Id{get;set;} public double VolumeInUnits{get;set;} public double EntryPrice{get;set;} public TradeType TradeType{get;set;} public double? StopLoss{get;set;} public double? TakeProfit{get;set;} public double Commissions{get;set;} }
public class HistoricalTrade {public string SymbolName{get;set;}="XAUUSD";public string Label{get;set;}="";public long PositionId{get;set;} public double EntryPrice{get;set;} public double VolumeInUnits{get;set;} public TradeType TradeType{get;set;} public double Commissions{get;set;} }
public class TradeResult {public bool IsSuccessful{get;set;}=true;public Position? Position{get;set;} public string Error{get;set;}="TEST";}
public class Clock {public DateTime TimeInUtc{get;set;}=new DateTime(2020,1,1,12,0,0,DateTimeKind.Utc);}
public class TimerObject {public void Start(TimeSpan t){} }
public class Store {public Dictionary<string,string> Values=new();public string? GetString(string k,LocalStorageScope s)=>Values.GetValueOrDefault(k);public void SetString(string k,string v,LocalStorageScope s){Values[k]=v;}public void Flush(LocalStorageScope s){} }
public class TimeFrame {public static TimeFrame Minute{get;}=new();}
public class Bars {public List<DateTime> OpenTimes{get;}=new();public List<double> OpenPrices{get;}=new();public List<double> HighPrices{get;}=new();public List<double> LowPrices{get;}=new();public List<double> ClosePrices{get;}=new();public int Count=>OpenTimes.Count; public int LoadMoreHistory()=>0;}
public class MarketDataObject {public Bars GetBars(TimeFrame t,string s)=>new();}
public class TextEvent {public string Text{get;set;}="";}
public class WebSocketClient:IDisposable {
 public static int Active,Maximum,Created;public bool Open,Disposed;public static bool FailSend,FailDispose;
 public event Action<TextEvent>? TextReceived;public event Action<object>? Disconnected;
 public WebSocketClient(){Created++;}
 public void Connect(Uri u){if(Open || Active!=0)throw new Exception("There is already an active WebSocket instance");Open=true;Active++;Maximum=Math.Max(Maximum,Active);}
 public List<string> Sent{get;}=new();public void Send(string s){if(FailSend)throw new Exception("SEND_FAILED");Sent.Add(s);}
 public void Emit(string text)=>TextReceived?.Invoke(new(){Text=text});
 public void Drop(){if(Open){Open=false;Active--;}Disconnected?.Invoke(new());}
 public void Dispose(){if(FailDispose)throw new Exception("DISPOSE_FAILED");if(Disposed)return;Disposed=true;if(Open){Open=false;Active--;}Disconnected?.Invoke(new());}
}
public abstract class Robot {
 public Account Account{get;}=new();public Symbol Symbol{get;}=new();public string SymbolName{get;set;}="XAUUSD";public List<Position> Positions{get;}=new();public List<HistoricalTrade> History{get;}=new();public List<object> PendingOrders{get;}=new();public Clock Server{get;}=new();public Store LocalStorage{get;}=new();public TimerObject Timer{get;}=new();public MarketDataObject MarketData{get;}=new();public int Requests,Closes;public bool Reject,FailProtection,FailClose;public double ExtraSlip,ExtraFee;public double ReturnVolumeFactor=1;public double LastVolume;
 protected virtual void OnStart(){}protected virtual void OnTimer(){}protected virtual void OnStop(){}public void Stop(){}public void Print(string s,params object[] o){}public void BeginInvokeOnMainThread(Action a)=>a();
 protected TradeResult ExecuteMarketOrder(TradeType side,string symbol,double volume,string label,double sl,double tp,string comment){Requests++;LastVolume=volume;if(Reject)return new(){IsSuccessful=false};double quote=side==TradeType.Buy?Symbol.Ask:Symbol.Bid;int sign=side==TradeType.Buy?1:-1;double entry=quote+sign*ExtraSlip;double actualVolume=volume*ReturnVolumeFactor;var p=new Position{Id=Requests,Label=label,VolumeInUnits=actualVolume,TradeType=side,EntryPrice=entry,StopLoss=entry-sign*sl*Symbol.PipSize,TakeProfit=entry+sign*tp*Symbol.PipSize,Comment=comment,Commissions=-(actualVolume*.03+ExtraFee)};Positions.Add(p);Account.Balance-=actualVolume*.03+ExtraFee;Account.Equity-=actualVolume*(Symbol.Ask-Symbol.Bid+ExtraSlip)+actualVolume*.03+ExtraFee;Account.Margin+=Symbol.GetEstimatedMargin(side,actualVolume);return new(){Position=p};}
 protected TradeResult ModifyPosition(Position p,double sl,double tp,ProtectionType t){if(FailProtection)return new(){IsSuccessful=false};p.StopLoss=sl;p.TakeProfit=tp;return new(){Position=p};}
 protected TradeResult ClosePosition(Position p){Closes++;if(FailClose)return new(){IsSuccessful=false};Positions.Remove(p);History.Add(new(){Label=p.Label,PositionId=p.Id,EntryPrice=p.EntryPrice,VolumeInUnits=p.VolumeInUnits,TradeType=p.TradeType,Commissions=p.Commissions});Account.Margin-=Symbol.GetEstimatedMargin(p.TradeType,p.VolumeInUnits);return new(){Position=p};}
}
}
namespace cAlgo.API.Internals {
public class Symbol {public double Ask{get;set;}=1.10001;public double Bid{get;set;}=1.1;public double TickSize=>.00001;public double PipSize=>.0001;public double VolumeInUnitsMin{get;set;}=1000;public double VolumeInUnitsMax{get;set;}=2000000;public double VolumeInUnitsStep{get;set;}=1000;public double Leverage{get;set;}=200;public double QuantityToVolumeInUnits(double lots)=>lots*100000;public double VolumeInUnitsToQuantity(double volume)=>volume/100000;public double NormalizeVolumeInUnits(double v,cAlgo.API.RoundingMode m)=>Math.Floor(v/VolumeInUnitsStep)*VolumeInUnitsStep;public double GetEstimatedMargin(cAlgo.API.TradeType t,double v)=>v*Ask/Leverage; }
}
