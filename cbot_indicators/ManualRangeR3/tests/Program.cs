using System.Globalization;
using System.Text.Json;
using Rizan.ManualR3;
var culture=CultureInfo.InvariantCulture;
var input=File.ReadAllLines(args[0]).Skip(1).Where(s=>s.Length>0).Select(line=>{
    var p=line.Split(',');return new Candle(DateTime.Parse(p[0],culture,DateTimeStyles.AdjustToUniversal|DateTimeStyles.AssumeUniversal),
        double.Parse(p[1],culture),double.Parse(p[2],culture),double.Parse(p[3],culture),double.Parse(p[4],culture));}).ToList();
var cases=JsonDocument.Parse(File.ReadAllText(args[1]));int passed=0;double maxError=0;
foreach(var row in cases.RootElement.EnumerateArray()){
    DateTime now=DateTime.Parse(row.GetProperty("now").GetString()!,culture,DateTimeStyles.AdjustToUniversal|DateTimeStyles.AssumeUniversal);
    var history=input.Where(x=>x.At.AddMinutes(1)<=now).TakeLast(12000).ToList();var core=new ManualR3Core(history,now);
    double bid=row.GetProperty("bid").GetDouble(),ask=row.GetProperty("ask").GetDouble();
    var result=core.Evaluate(now,bid,ask,now,new List<News>());
    var expected=row.GetProperty("expected");string state=expected.GetProperty("status").GetString()!;
    if(result.State!=state)throw new Exception($"STATE {now:O}: {result.State}!={state}");
    foreach(var (key,value) in new (string,double)[]{("atr_m5",result.Atr),("h1_adx",result.Adx),
               ("lower",result.Lower),("upper",result.Upper)}){
        double e=expected.GetProperty(key).GetDouble();maxError=Math.Max(maxError,Math.Abs(value-e));
        if(Math.Abs(value-e)>1e-7)throw new Exception($"VALUE {now:O} {key}: {value}!={e}");
    }
    if(expected.TryGetProperty("entry",out var entry)){
        if(result.Plan==null)throw new Exception("PLAN_MISSING");
        foreach(var (value,e) in new (double,double)[]{(result.Plan.Entry,entry.GetDouble()),(result.Plan.Stop,expected.GetProperty("sl").GetDouble()),(result.Plan.Target,expected.GetProperty("tp").GetDouble())})
            if(Math.Abs(value-e)>1e-7)throw new Exception("PLAN_PARITY");
        var saved=result.Plan;var repeat=core.Evaluate(now.AddSeconds(1),bid,ask,now,new List<News>());
        if(repeat.Plan!=saved)throw new Exception("PLAN_CHANGED");
        var blocked=core.Evaluate(now,bid,ask,now,null);if(blocked.State.StartsWith("TRIGGER"))throw new Exception("NEWS_FAIL_OPEN");
    }
    passed++;
}
var report=new{passed,max_absolute_error=maxError,core=ManualR3Core.Version,status="PASS",scope="Identical timestamped M1 fixtures; not terminal/broker parity"};
Console.WriteLine(JsonSerializer.Serialize(report));
if(args.Length>2)File.WriteAllText(args[2],JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));
