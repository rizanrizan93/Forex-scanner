using Rizan.Frozen;
using System.Text.Json;
using System.Globalization;
static double? Clean(double x)=>FrozenCore.Finite(x)?x:null;
var options=new JsonSerializerOptions{PropertyNameCaseInsensitive=true,Converters={new UtcDateTimeConverter()}};
using var document=JsonDocument.Parse(File.ReadAllText(args[1]));
var root=document.RootElement;
if(args[0]=="xau"){
    var rows=root.EnumerateArray().ToArray();
    double D(JsonElement r,string key)=>r.GetProperty(key).ValueKind==JsonValueKind.Null?double.NaN:r.GetProperty(key).GetDouble();
    var bars=rows.Select(r=>new Candle(DateTime.Parse(r.GetProperty("timestamp").GetString()!,CultureInfo.InvariantCulture,DateTimeStyles.AdjustToUniversal).AddMinutes(-5),D(r,"open"),D(r,"high"),D(r,"low"),D(r,"close"))).ToArray();
    var data=FrozenCore.XauRaw(bars,rows.Select(r=>D(r,"atr")).ToArray(),rows.Select(r=>FrozenCore.Finite(D(r,"h1strict"))?(int)D(r,"h1strict"):0).ToArray(),rows.Select(r=>FrozenCore.Finite(D(r,"m15strict"))?(int)D(r,"m15strict"):0).ToArray());
    Console.WriteLine(JsonSerializer.Serialize(data.Select(x=>new{x.Buy,x.Sell,BuyAnchor=Clean(x.BuyAnchor),SellAnchor=Clean(x.SellAnchor)})));return;
}
if(args[0]=="confirmation"){
    var bars=JsonSerializer.Deserialize<List<Candle>>(root.GetProperty("bars"),options)!;
    var times=JsonSerializer.Deserialize<List<DateTime>>(root.GetProperty("times"),options)!;
    Console.WriteLine(JsonSerializer.Serialize(times.Select(at=>new{AtUtc=at,Buy=FrozenCore.XauConfirmation(bars,at,1),Sell=FrozenCore.XauConfirmation(bars,at,-1)})));return;
}
if(args[0]=="eur"){
    var bars=JsonSerializer.Deserialize<List<Candle>>(root.GetProperty("bars"),options)!;
    var state=root.TryGetProperty("state",out var st)?JsonSerializer.Deserialize<EurState>(st,options)!:new EurState{CursorUtc=bars[0].OpenUtc.AddMinutes(-1)};
    var f=FrozenCore.EurFeatures(bars,bars[^1].OpenUtc.AddMinutes(1),state);
    FrozenCore.AdvanceVirtual(bars,f,state);
    Console.WriteLine(JsonSerializer.Serialize(new{Features=f.Select(x=>new{x.AtUtc,x.Count,Atr=Clean(x.Atr),Body=Clean(x.Body),PriorHigh=Clean(x.PriorHigh),PriorLow=Clean(x.PriorLow),x.Bias,Signal=FrozenCore.EurSignal(x)}),State=state,Scale=FrozenCore.EurScale(state)}));return;
}
if(args[0]=="virtual"){
    var result=new List<object>();
    foreach(var r in root.EnumerateArray()){
        var trade=JsonSerializer.Deserialize<VirtualTrade>(r.GetProperty("trade"),options)!;
        var bar=JsonSerializer.Deserialize<Candle>(r.GetProperty("bar"),options)!;
        var exit=FrozenCore.VirtualStep(trade,bar);
        result.Add(new{R=exit?.R,AtUtc=exit?.AtUtc,trade.LastUtc,trade.LastClose});
    }
    Console.WriteLine(JsonSerializer.Serialize(result));return;
}
if(args[0]=="sizing"){
    var output=new List<object>();
    foreach(var r in root.EnumerateArray()){
        var c=r.GetProperty("symbol").GetString()=="EURUSD"?FrozenContract.Eur:FrozenContract.Xau;
        double D(string name)=>r.GetProperty(name).GetDouble();
        int side=r.GetProperty("side").GetInt32();
        var signal=new Signal(DateTime.Parse("2026-10-09T12:00:00Z").ToUniversalTime(),side,D("distance"),D("atr"),D("anchor"));
        var basket=FrozenCore.StartBasket(c,signal,D("entry"),D("balance"),D("equity"),D("free"),D("used"),D("margin"),D("scale"),D("peak"));
        if(basket==null){output.Add(new{Initial=0});continue;}
        basket.UsedRisk=basket.InitialWanted*FrozenCore.ChildRisk(c,side,basket.Entry,basket.Stop);
        var counts=Enumerable.Range(1,c.Stages-1).Select(k=>FrozenCore.StageWanted(c,basket,k,basket.Entry-side*c.Depths[k]*Math.Abs(basket.Entry-basket.Stop),D("equity"),D("free"),D("margin"),D("used"))).ToArray();
        output.Add(new{Initial=basket.InitialWanted,basket.RiskBudget,basket.Stop,basket.Target,basket.RemainingStageBudget,Stages=counts});
    }
    Console.WriteLine(JsonSerializer.Serialize(output));return;
}
throw new Exception("Unknown mode");
