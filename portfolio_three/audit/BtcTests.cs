using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
int checks=0;void Check(bool pass,string message){checks++;if(!pass)throw new Exception(message);}
var rows=File.ReadLines(args[0]).Skip(1).Select(line=>{var a=line.Split(',');return new BtcBar(DateTime.Parse(a[0],CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal),double.Parse(a[1],CultureInfo.InvariantCulture),double.Parse(a[2],CultureInfo.InvariantCulture),double.Parse(a[3],CultureInfo.InvariantCulture),double.Parse(a[4],CultureInfo.InvariantCulture));}).ToList();
var hourly=BtcCore.Aggregate(rows,60);var four=BtcCore.Aggregate(rows,240);var signals=BtcCore.Signals(hourly,four);
var reference=File.ReadLines(args[1]).Skip(1).Select(s=>s.Split(',')).ToList();Check(reference.Count==signals.Count,"SIGNAL_COUNT_"+signals.Count+"_"+reference.Count);
foreach(var r in reference){var at=DateTime.Parse(r[0],CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal);Check(signals.TryGetValue(at,out var s)&&s.Side==int.Parse(r[1])&&Math.Abs(s.Atr-double.Parse(r[2],CultureInfo.InvariantCulture))<1e-8&&Math.Abs(s.Reference-double.Parse(r[3],CultureInfo.InvariantCulture))<1e-8,"CPP_SIGNAL_PARITY_"+at);}
foreach(var at in signals.Keys.Where((t,i)=>i%15==0)){
 var cut=BtcCore.Signals(hourly.Where(b=>b.At.AddHours(1)<=at).ToList(),four.Where(b=>b.At.AddHours(4)<=at).ToList());Check(cut.ContainsKey(at)&&cut[at]==signals[at],"CLOSED_BAR_CAUSALITY");}
var host=new TestHost{EnableXau=false,EnableEur=false,EnableBtc=true,EnableTrading=true};host.Account.Balance=100000;host.Account.Equity=100000;host.CreateEngines();host.Btc!.ReplayStart();var sym=host.Symbols.GetSymbol("BTCUSD");sym.Bid=10000;sym.Ask=10005;sym.Leverage=10;var now=new DateTime(2020,1,1,4,0,0,DateTimeKind.Utc);host.Server.TimeInUtc=now;
Check(host.NoForeignExposure()&&host.PortfolioReady,"BTC_READY");host.Btc.Enter(new(now,1,200,10000),now);Check(host.Positions.Count==1,"BTC_REAL_ORDER");Check(host.OpenRisk()<=Math.Min(host.Account.Balance,host.Account.Equity)*.2075+1e-8,"SHARED_RISK_BOUND");Check(host.Account.Margin<=Math.Min(host.Account.Balance,host.Account.Equity)*.5+1e-8,"SHARED_MARGIN_BOUND");
int requests=host.Requests;host.Btc.Enter(new(now.AddHours(1),-1,100,10000),now.AddHours(1));Check(host.Requests==requests,"BUSY_SIGNAL_CONSUMED");host.Btc.Manage(now.AddHours(129));Check(host.Positions.Count==0&&host.History.Count==1,"EXPIRY_CLOSE_AND_HISTORY");host.Btc.Enter(new(now.AddHours(1),-1,100,10000),now.AddHours(1));Check(host.Requests==requests,"NO_BUSY_SIGNAL_REPLAY");
host.Positions.Add(new(){SymbolName="XAUUSD",Label="FOREIGN",StopLoss=1});host.Btc.Enter(new(now.AddHours(130),-1,100,10000),now.AddHours(130));Check(host.Requests==requests,"FOREIGN_EXPOSURE_BLOCKS_BTC");
var uncertain=new TestHost{EnableXau=false,EnableEur=false,EnableBtc=true};uncertain.CreateEngines();uncertain.LocalStorage.SetString("RIZAN BTC 8500283 V1 "+uncertain.Account.Number,"{\"Schema\":1,\"Sending\":true}",LocalStorageScope.Instance);uncertain.Btc!.OnStart();Check(!uncertain.Btc.RecoveryReady,"UNCERTAIN_SEND_FAILS_CLOSED");
var firstBuy=signals.Values.Where(s=>s.Side==1).OrderBy(s=>s.At).First();var live=new TestHost{EnableXau=false,EnableEur=false,EnableBtc=true,EnableTrading=true};live.CreateEngines();live.Btc!.OnStart();live.Server.TimeInUtc=firstBuy.At;
Bars MakeBars(List<BtcBar> input,int width){var bars=new Bars();foreach(var b in input.Where(b=>b.At.AddMinutes(width)<=firstBuy.At)){bars.OpenTimes.Add(b.At);bars.OpenPrices.Add(b.Open);bars.HighPrices.Add(b.High);bars.LowPrices.Add(b.Low);bars.ClosePrices.Add(b.Close);}bars.OpenTimes.Add(firstBuy.At);bars.OpenPrices.Add(1);bars.HighPrices.Add(1e9);bars.LowPrices.Add(.01);bars.ClosePrices.Add(1e8);return bars;}
var hh=MakeBars(hourly,60);var qq=MakeBars(four,240);live.MarketData.Provider=(tf,symbol)=>tf==TimeFrame.Hour?hh:qq;var open=rows.First(r=>r.At==firstBuy.At).Open;live.Symbols.GetSymbol("BTCUSD").Bid=open;live.Symbols.GetSymbol("BTCUSD").Ask=open*1.0005;live.Symbols.GetSymbol("BTCUSD").Leverage=10;live.Btc.OnTimer();
Check(live.Btc.RecoveryReady,"NATIVE_BAR_ADAPTER_READY");Check(live.Positions.Count==1&&live.Positions[0].TradeType==TradeType.Buy,"NATIVE_TIMER_ENTRY_FROM_CLOSED_BARS");Check(live.Positions[0].TakeProfit>live.Positions[0].EntryPrice,"NATIVE_TP_DIRECTION");
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,Signals=signals.Count,CppParity=true,Symbols=new[]{"XAUUSD","EURUSD","BTCUSD"}}));
sealed class TestHost:RizanPortfolio{}
