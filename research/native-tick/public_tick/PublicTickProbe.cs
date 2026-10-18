using System;
using System.Text.Json;
using cAlgo.API;
namespace cAlgo.Robots;
[Robot(TimeZone=TimeZones.UTC,AccessRights=AccessRights.None)]
public class PublicTickProbe:Robot
{
 long count,reversed;DateTime previous;string first="",last="";
 protected override void OnStart(){if(RunningMode==RunningMode.RealTime){Print("BACKTEST_ONLY_REFUSED");Stop();return;}Print("PUBLIC_PROBE_START "+JsonSerializer.Serialize(new{SymbolName,Mode=RunningMode.ToString(),Account.Balance,Account.PreciseLeverage,Symbol.Bid,Symbol.Ask,Time=Server.TimeInUtc}));}
 protected override void OnTick(){var now=Server.TimeInUtc;if(count>0&&now<previous)reversed++;previous=now;if(count++==0){first=now.ToString("O");Print("PUBLIC_FIRST_TICK "+JsonSerializer.Serialize(new{SymbolName,Symbol.Bid,Symbol.Ask,Time=now}));}last=now.ToString("O");}
 protected override void OnStop(){Print("PUBLIC_PROBE_RESULT "+JsonSerializer.Serialize(new{SymbolName,count,reversed,first,last,Account.Balance,Account.Equity,Positions=Positions.Count}));}
}
