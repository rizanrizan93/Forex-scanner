// BUY050 READ-ONLY shadow evaluator. Signal engines are linked directly to the
// immutable native BUY050 C# source tree in Buy050Shadow.csproj.
// Never import cTrader order APIs. Never claim an executed/approved LIVE order.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using X = Rizan.Portfolio.Xau;
using E = Rizan.Portfolio.Eur;
using Rizan.Portfolio;

if (args.Length != 2) throw new ArgumentException("USAGE: input.json output.json");

using var inputDoc = JsonDocument.Parse(File.ReadAllText(args[0]));
var input = inputDoc.RootElement;
var market = input.GetProperty("market");
var native = input.GetProperty("native");
var now = DateTimeOffset.Parse(market.GetProperty("as_of").GetString()!).UtcDateTime;
var profile = FrozenR3.ConfigSha256;
if (profile != "13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"
    || !FrozenR3.Matches()
    || market.GetProperty("read_only").GetBoolean() != true
    || native.GetProperty("read_only").GetBoolean() != true
    || market.GetProperty("account_binding").GetString() != native.GetProperty("account_binding").GetString())
    throw new InvalidDataException("READ_ONLY_PROFILE_ACCOUNT_PARITY_REQUIRED");

static DateTime? Stamp(JsonElement obj, string key) {
    if (!obj.TryGetProperty(key,out var v)||v.ValueKind!=JsonValueKind.String)return null;
    try{return DateTimeOffset.Parse(v.GetString()!).UtcDateTime;}catch{return null;}
}
static bool Frozen(DateTime? at,DateTime now,int maxS) =>
    at.HasValue && (now-at.Value).TotalSeconds>=-5 && (now-at.Value).TotalSeconds<=maxS;
static double? Num(JsonElement obj,string key) =>
    obj.TryGetProperty(key,out var x)&&x.ValueKind==JsonValueKind.Number&&x.TryGetDouble(out var d)&&double.IsFinite(d)?d:null;
static (double bid,double ask)? Quote(JsonElement market,string symbol,DateTime now) {
    if (!market.TryGetProperty("quotes",out var q)||!q.TryGetProperty(symbol,out var obj)||
        !obj.TryGetProperty("BID",out var b)||!obj.TryGetProperty("ASK",out var a))return null;
    if(!Frozen(Stamp(b,"at"),now,15)||!Frozen(Stamp(a,"at"),now,15))return null;
    var bid=Num(b,"price");var ask=Num(a,"price");
    return bid>0&&ask>=bid?(bid.Value,ask.Value):null;
}
static List<X.Candle> Bars(JsonElement market,string symbol,DateTime now){
    if(!market.TryGetProperty("bars",out var all)||!all.TryGetProperty(symbol,out var data))return new();
    var rows=new List<X.Candle>();
    foreach(var j in data.EnumerateArray()) {
        var at=Stamp(j,"timestamp");
        var o=Num(j,"open");var h=Num(j,"high");var l=Num(j,"low");var c=Num(j,"close");
        if(at==null||at.Value.AddMinutes(1)>now||at.Value>now||
           o<=0||h<o||h<c||l>o||l>c||l<=0)continue;
        rows.Add(new(at.Value,o!.Value,h!.Value,l!.Value,c!.Value));
    }
    return rows.OrderBy(x=>x.OpenUtc).DistinctBy(x=>x.OpenUtc).ToList();
}
static object Empty(string symbol,DateTime? bar,string code,string note)=>new{
    symbol,status=code,reason=note,bar_at=bar,
    candidate=(object?)null,source_core="BUY050_NATIVE_CSHARP",
    execution_authority=false,execution_influence=false
};
static object Candidate(string symbol,DateTime now,DateTime at,int side,string origin,double entry,
                        double distance,double rr,string reason,DateTime? bar,params string[] blockers) {
    if(!double.IsFinite(entry)||!double.IsFinite(distance)||!double.IsFinite(rr)||entry<=0||distance<=0)
        return Empty(symbol,bar,"INVALID_GEOMETRY","Candidate geometry tidak valid.");
    double sl=entry-side*distance,tp=entry+side*distance*rr;
    if(sl<=0||tp<=0||side*(entry-sl)<=0||side*(tp-entry)<=0)
        return Empty(symbol,bar,"INVALID_GEOMETRY","SL/TP tidak memenuhi geometri.");
    return new{
        symbol,status="SETUP_SHADOW",reason,bar_at=bar,
        candidate=new {at,side=side>0?"BUY":"SELL",origin,
            entry,sl,tp,target_r=rr,valid_until=at.AddSeconds(symbol=="BTCUSD"?5:60),
            blockers=new[]{"CANDIDATE_NOT_BROKER_EXECUTED","NATIVE_TERMINAL_GATES_NOT_FULLY_OBSERVED"}.Concat(blockers).ToArray(),
            confidence="TECHNICAL_GEOMETRY_ONLY"},
        source_core="BUY050_NATIVE_CSHARP",execution_authority=false,execution_influence=false
    };
}
var result = new List<object>();
foreach(var symbol in new[]{"XAUUSD","EURUSD","BTCUSD"}) {
    try{
        var state = native.GetProperty("states").GetProperty(symbol);
        var quote = Quote(market,symbol,now);
        // A source-level signal never overrides native risk state or a broker
        // position. Hide actionable geometry when exposure is uncertain.
        bool flagged(string key) => state.TryGetProperty(key,out var v)&&v.ValueKind==JsonValueKind.True;
        if(flagged("Quarantined") || flagged("Fault") || flagged("ExitPending") || flagged("has_basket") || flagged("pending_intent")){
            result.Add(Empty(symbol,null,"NATIVE_BLOCK","Native checkpoint has quarantine, fault, position or outstanding intent."));continue;
        }
        if((market.TryGetProperty("foreign_exposure",out var foreign)&&foreign.ValueKind==JsonValueKind.True)
           || (market.TryGetProperty("pending_orders",out var pending)&&pending.ValueKind==JsonValueKind.True)
           || (market.TryGetProperty("positions",out var active)&&active.ValueKind==JsonValueKind.Array&&active.GetArrayLength()>0)){
            result.Add(Empty(symbol,null,"PORTFOLIO_EXPOSURE_BLOCK","Account exposure or pending orders require native portfolio reconciliation."));continue;
        }
        if(symbol=="BTCUSD" && Stamp(state,"WeekendLockUntil") is DateTime lockedUntil && now<lockedUntil){
            result.Add(Empty(symbol,null,"BTC_WEEKEND_LOCK","Native BTC lock remains in force."));continue;
        }
        if(symbol=="BTCUSD"){
            if(!native.TryGetProperty("btc_feed",out var packet)||packet.ValueKind!=JsonValueKind.Object){
                result.Add(Empty(symbol,null,"BTC_FEED_MISSING","BTC seed dan extension belum tervalidasi."));continue;
            }
            var feed=new BtcSevenDayFeed();
            feed.Accept(packet,now);
            var at=BtcSevenDayFeed.Hour(now);
            if(!feed.Signals.TryGetValue(at,out var s)){
                result.Add(Empty(symbol,at,"NO_SIGNAL","Tidak ada sinyal BTC BUY050 pada hour terbaru."));continue;
            }
            if(!Frozen(s.At,now,5)||quote==null){
                result.Add(Empty(symbol,at,"CANDIDATE_EXPIRED","Sinyal BTC harus diproses dalam 5 detik dan quote harus baru."));continue;
            }
            int side=s.Side;
            double entry=(side>0?quote.Value.ask:quote.Value.bid)+side*quote.Value.bid*.0001;
            double dist=(side>0?RP.C.BtcBuyStop:RP.C.BtcSellStop)*s.Atr;
            if(side*(entry-s.Reference)>.5*s.Atr){
                result.Add(Empty(symbol,at,"PRICE_CHASE_BLOCK","Harga BTC menjauh lebih dari batas 0,5 ATR."));continue;
            }
            result.Add(Candidate(symbol,now,s.At,side,s.Origin,entry,dist,side>0?RP.C.BtcBuyTarget:RP.C.BtcSellTarget,
                "Setup teknis dihitung menggunakan BTC native original + H4 Break40.",
                at, "BROKER_WEEKEND_AND_NATIVE_STATE_MUST_BE_RECHECKED"));
            continue;
        }
        var bars=Bars(market,symbol,now);
        if(bars.Count<1000){
            result.Add(Empty(symbol,null,"INSUFFICIENT_HISTORY","Riwayat M1 tertutup belum cukup."));continue;
        }
        var available=bars[^1].End(1);
        if (available>now) {
            result.Add(Empty(symbol,available,"FUTURE_BAR","Timestamp candle belum tutup."));continue;
        }
        if(symbol=="XAUUSD"){
            X.Signal? s=CompressionEntry.Signal(bars,available) ?? EntryFamilies.XauSignal(bars,available);
            if(s==null || s.AtUtc!=available){
                result.Add(Empty(symbol,available,"NO_SIGNAL","Tidak ada pola XAU BUY050 pada penutupan candle terbaru."));continue;
            }
            if(!Frozen(s.AtUtc,now,60)||quote==null){
                result.Add(Empty(symbol,available,"CANDIDATE_EXPIRED","Window 60 detik/quote 15 detik sudah lewat."));continue;
            }
            double spread=quote.Value.ask-quote.Value.bid;
            if(spread>1.5){
                result.Add(Empty(symbol,available,"SPREAD_BLOCK","Spread XAU melebihi 1,5."));continue;
            }
            var c=RP.X(X.FrozenContract.Xau) with{ReferenceLeverage=200};
            c=EntryFamilies.XauContract(c with{RiskFraction=Math.Min(c.RiskFraction,.121*RP.C.XauRisk),
                 Slip=.10,CommissionPerSide=.06},s.Origin,s.Side);
            double entry=(s.Side>0?quote.Value.ask:quote.Value.bid)+s.Side*c.Slip;
            double anchor=s.Anchor+(s.Side==-1?spread:0);
            double dist=Math.Max(.5,Math.Max(c.StopAtrMultiplier*s.Atr,s.Side*(entry-anchor)));
            result.Add(Candidate(symbol,now,s.AtUtc,s.Side,s.Origin,entry,dist,c.TargetR,
                "Compression atau H1 Displacement dari frozen XAU BUY050.",
                available,"XAU_MACRO_NEWS_HOLD_GATE_NOT_VERIFIED","BROKER_MARGIN_AND_POSITION_GATES_NOT_VERIFIED"));
        } else {
            E.EurState eur;
            if(state.TryGetProperty("Eur",out var eurRaw)&&eurRaw.ValueKind==JsonValueKind.Object)
                eur=JsonSerializer.Deserialize<E.EurState>(eurRaw.GetRawText())??new();
            else {
                result.Add(Empty(symbol,available,"EUR_STATE_MISSING","EurState native dibutuhkan untuk bias dan fitur."));continue;
            }
            var ebar=bars.Select(x=>new E.Candle(x.OpenUtc,x.Open,x.High,x.Low,x.Close)).ToList();
            var features=E.FrozenCore.EurFeatures(ebar,available,eur);
            var signals=features.Select(E.FrozenCore.EurSignal).Where(s=>s!=null).ToList();
            var s=signals.LastOrDefault(s=>s!.AtUtc==available);
            if(s==null){
                result.Add(Empty(symbol,available,"NO_SIGNAL","Tidak ada pola EUR F0245/Asia pada candle terbaru."));continue;
            }
            s=E.F0245Policy.ExecutionSignal(s);
            if(!Frozen(s.AtUtc,now,60)||quote==null) {
                result.Add(Empty(symbol,available,"CANDIDATE_EXPIRED","Window EUR 60 detik atau quote 15 detik sudah lewat."));continue;
            }
            if(quote.Value.ask-quote.Value.bid>.00022){
                result.Add(Empty(symbol,available,"SPREAD_BLOCK","Spread EUR > 0,00022."));continue;
            }
            double entry=s.Side>0?quote.Value.ask:quote.Value.bid;
            result.Add(Candidate(symbol,now,s.AtUtc,s.Side,s.AsiaExtra?"F0245_ASIA":"F0245",
                entry,s.Distance,E.F0245Policy.Contract.TargetR,
                "Konfirmasi EUR menggunakan C# frozen F0245 dan state H1 native.",
                available,"EUR_BATCH_MARGIN_AND_BROKER_GATES_NOT_VERIFIED"));
        }
    }catch(Exception ex){
        result.Add(Empty(symbol,null,"SHADOW_ERROR","Perhitungan ditahan: "+ex.GetType().Name));
    }
}
var output = new {
    contract="RIZAN_BUY050_SHADOW_V1",
    strategy="P3_BUY050",
    profile_sha256=profile,
    source_core="BUY050_NATIVE_CSHARP",
    as_of=now,
    read_only=true,
    execution_authority=false,
    execution_influence=false,
    symbols=result
};
File.WriteAllText(args[1],JsonSerializer.Serialize(output,
    new JsonSerializerOptions{WriteIndented=false}));
