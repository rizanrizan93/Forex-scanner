using System;
namespace Rizan.Portfolio;
// Frozen risk-control policy, based on the broker's advertised UTC session schedule.
internal static class BtcWeekendPolicy
{
    internal const int NoEntryMinutes=60;
    internal const int FlattenMinutes=30;
    internal static DateTime Monday(DateTime now)=>now.Date.AddDays(-(((int)now.DayOfWeek+6)%7));
    internal static bool Weekend(DateTime now)=>now.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday;
    internal static DateTime? LastClose(DateTime now,Func<DateTime,bool> isOpen)
    {
        var monday=Monday(now);var saturday=monday.AddDays(5);
        // Search a published timetable, never future OHLC. Minute resolution matches
        // the research clock; the close buffer is thirty minutes, not one tick.
        for(var t=saturday.AddMinutes(-1);t>=monday;t=t.AddMinutes(-1))
            if(isOpen(t))return t.AddMinutes(1);
        return null;
    }
    internal static bool CanEnter(DateTime now,DateTime? close,bool opened,DateTime lockUntil)=>
        !Weekend(now)&&opened&&close.HasValue&&now<close.Value.AddMinutes(-NoEntryMinutes)&&now<close.Value&&now>=lockUntil;
    internal static bool MustFlatten(DateTime now,DateTime? close)=>
        Weekend(now)||!close.HasValue||now>=close.Value.AddMinutes(-FlattenMinutes);
}
