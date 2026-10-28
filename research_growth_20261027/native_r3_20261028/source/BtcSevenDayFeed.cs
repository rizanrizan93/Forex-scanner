using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using System.Security.Cryptography;
namespace Rizan.Portfolio;
// No broker bars or mixed spot/CFD series. The historical seed is pinned bytewise.
internal sealed class BtcSevenDayFeed
{
    internal const string Contract="RZ-7D130-BTC8500283-LFOLLOW-WEEKEND";
    internal const string SeedHash="e041102102e4ae2768e06f0261b4bfbfabc056ffa5decde21e161d8904179030";
    internal const long SeedEnd=1792108800; // 2026-10-16 00:00 UTC
    internal DateTime Through {get;private set;}
    internal Dictionary<DateTime,BtcSignal> Signals {get;private set;}=new();
    internal bool Fresh(DateTime now)=>Through==Hour(now);
    internal static DateTime Hour(DateTime t)=>new(t.Year,t.Month,t.Day,t.Hour,0,0,DateTimeKind.Utc);
    internal void Accept(JsonElement root,DateTime now)
    {
        if(root.GetProperty("contract").GetString()!=Contract||root.GetProperty("source").GetString()!="BITSTAMP_BTCUSD_M1")throw new Exception("FEED_CONTRACT");
        long through=root.GetProperty("through").GetInt64();
        if(through%3600!=0||DateTimeOffset.FromUnixTimeSeconds(through).UtcDateTime!=Hour(now))throw new Exception("FEED_STALE_OR_FUTURE");
        var bars=new List<BtcBar>();long last=-1;int seedRows=0;
        using var buffer=new MemoryStream();using var binary=new BinaryWriter(buffer);
        foreach(var row in root.GetProperty("bars").EnumerateArray())
        {
            if(row.GetArrayLength()!=6||bars.Count>=200000)throw new Exception("FEED_LENGTH");
            var v=row.EnumerateArray().ToArray();long at=v[0].GetInt64();double o=v[1].GetDouble(),h=v[2].GetDouble(),l=v[3].GetDouble(),c=v[4].GetDouble();int n=v[5].GetInt32();
            if(at%3600!=0||at<=last||at+3600>through||n<1||n>60||new[]{o,h,l,c}.Any(x=>!double.IsFinite(x)||x<=0)||h<Math.Max(o,c)||l>Math.Min(o,c)||l>h)throw new Exception("FEED_BAR_INVALID");
            if(at>=SeedEnd&&(at!=last+3600||n!=60))throw new Exception("FEED_EXTENSION_GAP");
            if(at<SeedEnd){binary.Write(at);binary.Write(o);binary.Write(h);binary.Write(l);binary.Write(c);binary.Write(n);seedRows++;}
            bars.Add(new(DateTimeOffset.FromUnixTimeSeconds(at).UtcDateTime,o,h,l,c,n));last=at;
        }
        if(bars.Count==0||new DateTimeOffset(bars[0].At).ToUnixTimeSeconds()!=1546300800||last+3600!=through||seedRows!=68280)throw new Exception("FEED_COVERAGE");
        if(Convert.ToHexString(SHA256.HashData(buffer.ToArray())).ToLowerInvariant()!=SeedHash)throw new Exception("FEED_SEED_HASH");
        var candidate=BtcCore.Signals(bars,BtcCore.Aggregate(bars,240));
        // Publish atomically only after every check passes.
        Signals=candidate;Through=DateTimeOffset.FromUnixTimeSeconds(through).UtcDateTime;
    }
}
