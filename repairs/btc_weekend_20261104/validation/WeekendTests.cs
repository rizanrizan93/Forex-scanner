using System;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Portfolio;
using F=System.Reflection.BindingFlags;

bool legacy=args.Contains("--legacy"); int checks=0;
void Check(bool value,string name){checks++;if(!value)throw new Exception(name);}
DateTime U(string s)=>DateTime.Parse(s,null,System.Globalization.DateTimeStyles.AdjustToUniversal|System.Globalization.DateTimeStyles.AssumeUniversal);
object Field(object o,string name)=>o.GetType().GetField(name,F.Instance|F.NonPublic)!.GetValue(o)!;
void Set(object o,string name,object value)=>o.GetType().GetField(name,F.Instance|F.NonPublic)!.SetValue(o,value);
DateTime Lock(BtcEngine b)=>(DateTime)Field(b,"state").GetType().GetProperty("WeekendLockUntil")!.GetValue(Field(b,"state"))!;
void SetLock(BtcEngine b,DateTime value)=>Field(b,"state").GetType().GetProperty("WeekendLockUntil")!.SetValue(Field(b,"state"),value);
RizanPortfolio Make(DateTime now,bool replay=true){var h=new RizanPortfolio{EnableTrading=false,EnableXau=false,EnableEur=false,EnableBtc=true,BtcBridgeUrl="wss://test.invalid:25345",BtcBridgeToken=new string('x',32)};h.Server.TimeInUtc=now;h.CreateEngines();if(replay)h.Btc!.ReplayStart();return h;}
void At(RizanPortfolio h,DateTime now){h.Server.TimeInUtc=now;h.Btc!.Manage(now);Check(h.Requests==0,"NO_TEST_ORDERS");}
bool Eligible(RizanPortfolio h,DateTime now)=>BtcWeekendPolicy.CanEnter(now,(DateTime?)Field(h.Btc!,"weekClose"),(bool)Field(h.Btc!,"marketOpen"),Lock(h.Btc!));
var mon=U("2026-11-02T00:00:00Z");
// Exact user regression including a close across the DST change.
{
 var h=Make(mon);Set(h.Btc!,"weekClose",U("2026-10-30T20:59:00Z"));Set(h.Btc!,"nextSchedule",mon.AddMinutes(3));SetLock(h.Btc!,mon);
 At(h,mon);var result=Lock(h.Btc!);
 Check(result==(legacy?mon.AddDays(7):mon),"MONDAY_STALE_CACHE_LOCK");
 Check(Eligible(h,mon)==!legacy,"MONDAY_ELIGIBILITY");
 Console.WriteLine(JsonSerializer.Serialize(new{Case="ExactMondayStale",Legacy=legacy,PriorLock=mon,ResultingLock=result,Eligible=Eligible(h,mon)}));
 // Repeated Manage calls never advance the fixed lock or issue requests.
 for(int i=1;i<4;i++)At(h,mon.AddSeconds(i));
 Check(Lock(h.Btc!)==result,"IDEMPOTENT_MANAGE");
}
// Normal Friday buffers, weekend protection, and Monday reopening.
{
 var h=Make(U("2026-10-30T20:59:59Z"));At(h,h.Server.TimeInUtc);Check(Eligible(h,h.Server.TimeInUtc),"FRIDAY_BEFORE_NO_ENTRY");
 At(h,U("2026-10-30T21:00:00Z"));Check(!Eligible(h,h.Server.TimeInUtc),"FRIDAY_60_MIN_NO_ENTRY");Check(Lock(h.Btc!)==default,"NO_PREMATURE_LOCK");
 At(h,U("2026-10-30T21:30:00Z"));Check(Lock(h.Btc!)==mon,"FRIDAY_30_MIN_LOCK");
 foreach(string s in new[]{"2026-10-31T00:00:00Z","2026-11-01T23:58:00Z"}){At(h,U(s));Check(!Eligible(h,h.Server.TimeInUtc),"WEEKEND_BLOCK");}
 At(h,mon);Check(Lock(h.Btc!)==(legacy?mon.AddDays(7):mon),"RUNNING_WEEK_CHANGE");
 Check(Eligible(h,mon)==!legacy,"RUNNING_MONDAY_REOPEN");
}
// Fresh cache, startup/recovery without inherited schedule cache, and closed Monday market.
foreach(string s in new[]{"2026-10-31T12:00:00Z","2026-11-01T12:00:00Z","2026-11-02T00:00:00Z","2026-11-04T12:00:00Z"}){
 var now=U(s);var h=Make(now);SetLock(h.Btc!,mon);At(h,now);
 Check(Eligible(h,now)==!BtcWeekendPolicy.Weekend(now),"RESTART_FRESH_SCHEDULE");
 // Exercise the actual native checkpoint decode/reconcile/Recover callback on reconnect.
 string json=JsonSerializer.Serialize(Field(h.Btc!,"state"));var n=Make(now,false);
 n.LocalStorage.Values[FrozenR3.BtcStorageKey(n.Account.Number)]=json;n.Btc!.OnStart();
 var link=(BtcStateLink)Field(n.Btc!,"link");link.Receive("{\"type\":\"ready\",\"revision\":0,\"state\":"+json+"}");
 Check(!n.Btc.ResearchFaulted,"NATIVE_RECONNECT_CHECKPOINT_VALID");Check(Eligible(n,now)==!BtcWeekendPolicy.Weekend(now),"NATIVE_RECONNECT_ELIGIBILITY");Check(n.Requests==0,"RECOVERY_NO_ORDER");
}
{
 var h=Make(mon);h.Symbols.GetSymbol("BTCUSD").MarketHours.Calendar=t=>t.DayOfWeek!=DayOfWeek.Saturday&&t.DayOfWeek!=DayOfWeek.Sunday&&(t.DayOfWeek!=DayOfWeek.Monday||t.Hour>=1)&&(t.DayOfWeek!=DayOfWeek.Friday||t.Hour<22);
 At(h,mon);Check(!Eligible(h,mon),"MONDAY_NOT_BEFORE_BROKER_OPEN");At(h,mon.AddHours(1));Check(Eligible(h,mon.AddHours(1)),"MONDAY_BROKER_REOPEN");
}
// Source fix deliberately does not silently migrate a future poisoned checkpoint.
{
 var wed=mon.AddDays(2);var h=Make(wed);SetLock(h.Btc!,mon.AddDays(7));At(h,wed);
 Check(Lock(h.Btc!)==mon.AddDays(7)&&!Eligible(h,wed),"POISONED_STATE_REQUIRES_APPROVED_CORRECTION");
}
// Schedule exceptions remain fail closed, with no invented weekly lock.
{
 var h=Make(mon);h.Symbols.GetSymbol("BTCUSD").MarketHours.Calendar=_=>throw new Exception("OFFLINE");At(h,mon);
 Check(!Eligible(h,mon)&&Lock(h.Btc!)==default,"SCHEDULE_ERROR_FAIL_CLOSED");
}
// Calendar-year and ISO-year boundaries: no year arithmetic or local/broker wall time.
foreach(string s in new[]{"2027-01-04T00:00:00Z","2029-01-01T00:00:00Z","2026-12-28T00:00:00Z"}){
 var at=U(s);var h=Make(at);Set(h.Btc!,"weekClose",at.AddDays(-3).AddHours(22));Set(h.Btc!,"nextSchedule",at.AddMinutes(3));SetLock(h.Btc!,at);At(h,at);
 Check(Lock(h.Btc!)==(legacy?at.AddDays(7):at),"YEAR_BOUNDARY_STALE");Check(Eligible(h,at)==!legacy,"YEAR_BOUNDARY_ELIGIBILITY");
}
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,Legacy=legacy,FakeBrokerOnly=true,RealOrders=0}));
