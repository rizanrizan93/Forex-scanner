using System;using System.Linq;using System.Text.Json;using Rizan.Portfolio;using cAlgo.API;
int checks=0;void Check(bool ok,string name){checks++;if(!ok)throw new Exception(name);}
Host Make(double leverage){var h=new Host{EnableXau=false,EnableEur=false,EnableBtc=true,EnableTrading=true};h.Account.Balance=1000;h.Account.Equity=1000;h.Account.PreciseLeverage=200;var s=h.Symbols.GetSymbol("BTCUSD");s.Bid=10000;s.Ask=10005;s.Leverage=leverage;h.Server.TimeInUtc=new DateTime(2020,1,6,4,0,0,DateTimeKind.Utc);h.CreateEngines();h.Btc!.ReplayStart();return h;}
double previous=0;var rows=new System.Collections.Generic.List<object>();
foreach(double l in new[]{2d,5,10,200}){
 var h=Make(l);h.Btc!.Enter(new(h.Server.TimeInUtc,1,10,10006),h.Server.TimeInUtc);Check(h.Positions.Count==1,"BUY_OPENS_"+l);var p=h.Positions.Single();Check(p.VolumeInUnits>previous,"HIGHER_BROKER_LEVERAGE_INCREASES_ALLOWED_BTC_"+l);previous=p.VolumeInUnits;
 Check(h.ReservedMargin()==h.Account.Margin,"NO_FLOOR_OR_DOUBLE_RESERVATION_"+l);Check(h.OpenRisk()<=Math.Min(h.Account.Balance,h.Account.Equity)*.2075+1e-8,"RISK_BOUND_"+l);Check(h.Account.Margin<=Math.Min(h.Account.Balance,h.Account.Equity)*.5+1e-8,"SHARED_MARGIN_"+l);
 rows.Add(new{BrokerLeverage=l,AccountLeverage=200,Volume=p.VolumeInUnits,Margin=h.Account.Margin,Risk=h.OpenRisk()});
 var s=Make(l);s.Btc!.Enter(new(s.Server.TimeInUtc,-1,10,9999),s.Server.TimeInUtc);Check(s.Positions.Count==1,"SELL_OPENS_"+l);var sp=s.Positions.Single();Check(s.Account.Margin+sp.VolumeInUnits*9999*.0005<=1000*.30+1e-8,"SELL_PROFILE_MARGIN_STILL_30_PERCENT_"+l);
}
foreach(double l in new[]{0d,double.NaN}){var h=Make(l);h.Btc!.Enter(new(h.Server.TimeInUtc,1,10,10006),h.Server.TimeInUtc);Check(h.Requests==0,"INVALID_MARGIN_FAIL_CLOSED_"+l);}
var off=Make(200);off.EnableTrading=false;off.Btc!.Enter(new(off.Server.TimeInUtc,1,10,10006),off.Server.TimeInUtc);Check(off.Requests==0,"DEFAULT_OFF_SENDS_NOTHING");
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,LiveOrders=0,Rows=rows}));
sealed class Host:RizanPortfolio{}
