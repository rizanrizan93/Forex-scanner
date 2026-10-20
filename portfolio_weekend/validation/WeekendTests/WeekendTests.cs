using System;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
int checks=0;void Check(bool value,string why){checks++;if(!value)throw new Exception(why);}
var fri=new DateTime(2026,10,16,0,0,0,DateTimeKind.Utc);var mon=fri.AddDays(3);
bool Regular(DateTime t)=>t.DayOfWeek!=DayOfWeek.Saturday&&t.DayOfWeek!=DayOfWeek.Sunday&&(t.DayOfWeek!=DayOfWeek.Friday||t.Hour<22);
Check(BtcWeekendPolicy.LastClose(fri,Regular)==fri.AddHours(22),"BROKER_FRIDAY_CLOSE");
Check(BtcWeekendPolicy.LastClose(fri,t=>Regular(t)&&(t.DayOfWeek!=DayOfWeek.Friday||t.Hour<21))==fri.AddHours(21),"DST_CLOSE_SHIFT");
Check(BtcWeekendPolicy.LastClose(fri,t=>Regular(t)&&t.DayOfWeek!=DayOfWeek.Friday)==fri.Date.AddDays(-1).AddDays(1),"FRIDAY_HOLIDAY_THURSDAY_FINAL_SESSION");
Check(BtcWeekendPolicy.LastClose(fri,t=>false)==null,"UNKNOWN_SCHEDULE_NO_INVENTED_CLOSE");
var close=fri.AddHours(22);
Check(BtcWeekendPolicy.CanEnter(close.AddMinutes(-61),close,true,default),"BEFORE_ENTRY_CUTOFF");
Check(!BtcWeekendPolicy.CanEnter(close.AddMinutes(-60),close,true,default),"EXACT_ENTRY_CUTOFF");
Check(!BtcWeekendPolicy.MustFlatten(close.AddMinutes(-31),close),"BEFORE_FLAT_CUTOFF");
Check(BtcWeekendPolicy.MustFlatten(close.AddMinutes(-30),close),"EXACT_FLAT_CUTOFF");
Check(!BtcWeekendPolicy.CanEnter(fri.AddDays(1),close,true,default),"SATURDAY_ALWAYS_BLOCKED");
Check(!BtcWeekendPolicy.CanEnter(fri.AddDays(2),close,true,default),"SUNDAY_ALWAYS_BLOCKED");
var h=HostAt(fri.AddHours(20));Enter(h,fri.AddHours(20),1);Check(h.Positions.Count==1,"FRIDAY_EARLY_ENTRY_EXECUTES");
h.Positions.Add(new(){SymbolName="XAUUSD",Label="MANUAL_XAU",VolumeInUnits=1,EntryPrice=100,StopLoss=90,TakeProfit=120});
h.Server.TimeInUtc=close.AddMinutes(-31);h.Btc!.Manage(h.Server.TimeInUtc);Check(h.Positions.Count(p=>p.SymbolName=="BTCUSD")==1,"POSITION_REMAINS_BEFORE_BUFFER");
h.Server.TimeInUtc=close.AddMinutes(-30);h.FailClose=true;h.Btc.Manage(h.Server.TimeInUtc);Check(h.Positions.Any(p=>p.SymbolName=="BTCUSD")&&!h.Btc.RecoveryReady,"REJECT_NOT_FALSE_FLAT_AND_NEW_ENTRY_BLOCKED");
var key="RIZAN BTC 8500283 V1 "+h.Account.Number;
Check(h.LocalStorage.Values[key].Contains("\"ExitPending\":true"),"PERSIST_CLOSE_INTENT_BEFORE_RETRY");
h.FailClose=false;h.Server.TimeInUtc=h.Server.TimeInUtc.AddSeconds(1);h.Btc.Manage(h.Server.TimeInUtc);Check(!h.Positions.Any(p=>p.SymbolName=="BTCUSD"),"RETRY_CLOSE_SUCCEEDS");Check(h.Positions.Any(p=>p.SymbolName=="XAUUSD"),"OTHER_SYMBOL_NOT_CLOSED");
h.Positions.RemoveAll(p=>p.SymbolName=="XAUUSD");var requests=h.Requests;Enter(h,close.AddMinutes(-29),-1);Check(h.Requests==requests,"NO_REENTRY_AFTER_FLATTEN");
Enter(h,fri.AddDays(1).AddHours(10),1);Check(h.Requests==requests,"SATURDAY_NO_ORDER");Enter(h,fri.AddDays(2).AddHours(10),-1);Check(h.Requests==requests,"SUNDAY_NO_ORDER");
Enter(h,mon.AddHours(4),1);Check(h.Positions.Count==1,"MONDAY_NEW_SIGNAL_ALLOWED");
// A restart with a durable close intent keeps retrying without a new signal.
var prior=HostAt(fri.AddHours(20));Enter(prior,fri.AddHours(20),-1);prior.FailClose=true;prior.Server.TimeInUtc=close.AddMinutes(-30);prior.Btc!.Manage(prior.Server.TimeInUtc);
var recovered=HostAt(close.AddMinutes(-29));foreach(var p in prior.Positions)recovered.Positions.Add(p);foreach(var kv in prior.LocalStorage.Values)recovered.LocalStorage.Values[kv.Key]=kv.Value;recovered.Btc!.OnStart();
Check(recovered.Positions.Count==0,"RESTART_RETRIES_PENDING_CLOSE");
var closed=HostAt(fri.AddHours(20));Enter(closed,fri.AddHours(20),1);closed.Server.TimeInUtc=fri.AddDays(1).AddHours(1);closed.Btc!.Manage(closed.Server.TimeInUtc);
Check(closed.Positions.Count==1&&!closed.Btc.RecoveryReady,"CLOSED_MARKET_CANNOT_FAKE_FLAT");closed.Server.TimeInUtc=mon;closed.Btc.Manage(mon);Check(closed.Positions.Count==0,"MISSED_CUTOFF_CLOSES_FIRST_REOPEN");
var offline=HostAt(fri.AddHours(20));Enter(offline,fri.AddHours(20),1);offline.EnableTrading=false;offline.Server.TimeInUtc=close.AddMinutes(-30);offline.Btc!.Manage(offline.Server.TimeInUtc);Check(offline.Positions.Count==1,"ORDER_OFF_RESPECTED");
var holiday=HostAt(fri.AddDays(-1).AddHours(20));holiday.Symbols.GetSymbol("BTCUSD").MarketHours.Calendar=t=>Regular(t)&&t.DayOfWeek!=DayOfWeek.Friday;holiday.Btc!.InvalidateSchedule();Enter(holiday,fri.AddDays(-1).AddHours(20),1);holiday.Server.TimeInUtc=fri.AddMinutes(-30);holiday.Btc.Manage(holiday.Server.TimeInUtc);Check(holiday.Positions.Count==0,"HOLIDAY_FLAT_BEFORE_THURSDAY_CLOSE");
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,EntryBufferMinutes=60,FlattenBufferMinutes=30,LiveOrders=0,FridayFlat=true,SaturdaySundayEntries=0,Retry=true,RestartRecovery=true}));
TestHost HostAt(DateTime at){var host=new TestHost{EnableTrading=true,EnableXau=false,EnableEur=false,EnableBtc=true};host.Account.Balance=host.Account.Equity=100000;host.Server.TimeInUtc=at;host.CreateEngines();host.Btc!.ReplayStart();var sym=host.Symbols.GetSymbol("BTCUSD");sym.Bid=10000;sym.Ask=10005;sym.Leverage=10;return host;}
void Enter(TestHost host,DateTime at,int side){host.Server.TimeInUtc=at;host.Btc!.Enter(new(at,side,200,10000),at);}
sealed class TestHost:RizanPortfolio{}
