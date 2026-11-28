using System;using cAlgo.API;
namespace Rizan.Portfolio;
public static class ResearchAccounting {
 public static DateTime FundingStart(Position p)=>p.Label.Split('|').Length>2?p.EntryTime:new DateTime(long.Parse(p.Label.Split('|')[1]),DateTimeKind.Utc);
}
