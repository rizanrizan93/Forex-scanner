using System;
using System.Collections.Generic;
namespace Rizan.Portfolio;
internal static class ReplaySizing {
 internal static int StartHour=>int.Parse(Environment.GetEnvironmentVariable("XAU_START_UTC")??"12");
 static bool Enabled=>Environment.GetEnvironmentVariable("ADAPTIVE_GUARD")=="1";
 static double balance,peak,lastDd; static string symbol="";static DateTime at;
 static readonly List<object> decisions=new();static int settlements;
 internal static void Reset(){balance=peak=100;settlements=0;decisions.Clear();}
 internal static void Settle(double pnl){balance+=pnl;if(balance<=0||!double.IsFinite(balance))throw new Exception("INVALID_SETTLED_BALANCE");peak=Math.Max(peak,balance);settlements++;}
 internal static double Factor(string sym,DateTime now){symbol=sym;at=now;lastDd=100*Math.Max(0,peak-balance)/peak;return Enabled?(sym=="XAUUSD"&&lastDd>30?.9:1.05):1;}
 internal static double Cap(double risk,double factor,double hard){double effective=Math.Min(risk*factor,hard);decisions.Add(new{At=at,Symbol=symbol,SettledBalance=balance,Peak=peak,DD=lastDd,RequestedFactor=factor,EffectiveFactor=effective/risk,ClippingReason=effective<risk*factor-1e-12?"FROZEN_INSTRUMENT_RISK_CAP":"NONE"});return effective;}
 internal static object Audit()=>new{Enabled,StartUtc=StartHour,EndUtc=17,DDDefinition="completed_basket_realized_pnl_only",InitialCash=100,SettledBalance=balance,Settlements=settlements,Decisions=decisions};
}
