using System.Text.Json;
using X=Rizan.Portfolio.Xau;
using E=Rizan.Portfolio.Eur;
using Rizan.Portfolio;
var input=JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
var now=input.GetProperty("as_of").GetDateTime();
var results=new List<object>();
foreach(var symbol in new[]{"XAUUSD","EURUSD"}){
 var bars=input.GetProperty("bars").GetProperty(symbol).EnumerateArray().Select(b=>new X.Candle(b.GetProperty("timestamp").GetDateTime(),b.GetProperty("open").GetDouble(),b.GetProperty("high").GetDouble(),b.GetProperty("low").GetDouble(),b.GetProperty("close").GetDouble())).Where(b=>b.End(1)<=now).OrderBy(b=>b.OpenUtc).ToList();
 if(bars.Count==0)continue;
 var available=bars[^1].End(1);
 if(symbol=="XAUUSD"){
  var m5=X.FrozenCore.Aggregate(bars,5,available);var m15=X.FrozenCore.Aggregate(bars,15,available);var h1=X.FrozenCore.Aggregate(bars,60,available);
  if(h1.Count<200||m15.Count<200||m5.Count<100)continue;
  var atr=X.FrozenCore.Atr(m5);var hb=X.FrozenCore.AlignStrict(h1,60,m5);var mb=X.FrozenCore.AlignStrict(m15,15,m5);
  var b=m5[^1];var n=m5.Count;var previous=m5.Skip(Math.Max(0,n-25)).Take(24).ToArray();
  // The regression threshold below is the exact previous-window band used in XauRaw.
  var win=m5.Skip(n-49).Take(48).Select(c=>c.Close).ToArray();double mean=win.Average(),weighted=win.Select((v,i)=>i*v).Sum();
  double slope=(weighted-48d*47/2*mean)/(48d*(48d*48-1)/12);double fit=mean+slope*47/2;double sd=Math.Sqrt(win.Average(v=>Math.Pow(v-mean,2)));
  var signal=X.FrozenCore.XauSignal(bars,available);
  results.Add(new{symbol,bar_at=b.End(5),h1_bias=hb[^1],m15_bias=mb[^1],session_open=b.End(5).Hour>=12&&b.End(5).Hour<17&&(int)b.End(5).DayOfWeek>0&&(int)b.End(5).DayOfWeek<6,
   warmup_start=bars[0].OpenUtc,areas=new[]{new{side="BUY",low=fit-1.5*sd,high=fit-1.5*sd,condition="Close M5 kembali di atas batas channel, candle bullish, bias H1 dan M15 BUY"},new{side="SELL",low=previous.Max(c=>c.High),high=previous.Max(c=>c.High),condition="Sweep high 24 candle M5 lalu close bearish menembus low candle sweep − 0,05 ATR dalam 1–3 candle; bias H1 dan M15 SELL"}},
   signal=signal==null?null:new{at=signal.AtUtc,side=signal.Side>0?"BUY":"SELL",atr=signal.Atr,anchor=signal.Anchor,distance=signal.Distance},target_r=5.5,stop_atr=2.4,depths=new[]{0d,.2,.4},addition_confirmation=true});
 }else{
  var eb=bars.Select(b=>new E.Candle(b.OpenUtc,b.Open,b.High,b.Low,b.Close)).ToList();
  // Resume a COPY of native EUR indicator state; never advance the live checkpoint.
  E.EurState state=new();
  if(input.TryGetProperty("native",out var nat)&&nat.TryGetProperty("states",out var states)&&states.TryGetProperty(symbol,out var ns)&&ns.TryGetProperty("Eur",out var es))state=JsonSerializer.Deserialize<E.EurState>(es.GetRawText())??new();
  var f=E.FrozenCore.EurFeatures(eb,available,state);if(f.Count<20)continue;var b=f[^1];var signal=E.FrozenCore.EurSignal(b);if(signal!=null)signal=E.F0245Policy.ExecutionSignal(signal);
  results.Add(new{symbol,bar_at=b.AtUtc,h1_bias=b.Bias,m15_bias=0,session_open=b.AtUtc.Hour>=7&&b.AtUtc.Hour<12,warmup_start=bars[0].OpenUtc,
   areas=new[]{new{side="BUY",low=b.PriorLow,high=b.PriorLow,condition="Sweep low 8 candle M15, close kembali di atasnya, body >20% range, H1 netral"},new{side="SELL",low=b.PriorHigh,high=b.PriorHigh,condition="Sweep high 8 candle M15, close kembali di bawahnya, body bearish >20% range, H1 netral"}},
   signal=signal==null?null:new{at=signal.AtUtc,side=signal.Side>0?"BUY":"SELL",atr=signal.Atr,anchor=signal.Anchor,distance=signal.Distance},target_r=10d,stop_atr=0d,depths=new[]{0d,.2,.4},addition_confirmation=false});
 }
}
try{
 var feed=new BtcSevenDayFeed();feed.Accept(input.GetProperty("native").GetProperty("btc_feed"),now);
 var at=BtcSevenDayFeed.Hour(now);var signals=feed.Signals;signals.TryGetValue(at,out var signal);
 // Inspect the unchanged core's features for explanatory breakout levels only.
 var hourly=input.GetProperty("native").GetProperty("btc_feed").GetProperty("bars").EnumerateArray().Select(v=>{var a=v.EnumerateArray().ToArray();return new BtcBar(DateTimeOffset.FromUnixTimeSeconds(a[0].GetInt64()).UtcDateTime,a[1].GetDouble(),a[2].GetDouble(),a[3].GetDouble(),a[4].GetDouble(),a[5].GetInt32());}).ToList();
 var four=BtcCore.Aggregate(hourly,240).Where(b=>b.At.AddHours(4)<=now).ToList();
 var method=typeof(BtcCore).GetMethod("Features",System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic)!;
 var hf=((System.Collections.IEnumerable)method.Invoke(null,new object[]{hourly})!).Cast<object>().ToArray();
 var qf=((System.Collections.IEnumerable)method.Invoke(null,new object[]{four})!).Cast<object>().ToArray();
 double Number(object f,string name)=>(double)f.GetType().GetProperty(name)!.GetValue(f)!;
 var last4=four[^1];double atr4=Number(qf[^1],"Atr"),atr1=Number(hf[^1],"Atr");
 double buyLevel=Math.Max(last4.Open+1.4*atr4,four[^2].High);
 double sellLevel=hourly.Skip(hourly.Count-17).Take(16).Min(b=>b.Low)-.1*atr1;
 results.Add(new{symbol="BTCUSD",bar_at=feed.Through,h1_bias=0,m15_bias=0,session_open=now.DayOfWeek!=DayOfWeek.Saturday&&now.DayOfWeek!=DayOfWeek.Sunday,
  areas=new[]{new{side="BUY",low=buyLevel,high=buyLevel,condition="Level momentum H4: close > high H4 sebelumnya dan body >1,4 ATR; tren EMA20/80 bullish, close sebelum 15:00 WIB"},new{side="SELL",low=sellLevel,high=sellLevel,condition="Close H1 di bawah range 16 jam − 0,1 ATR; tren H4 bearish, kompresi range, filter RSI dan volatilitas"}},signal=signal==null?null:new{at=signal.At,side=signal.Side>0?"BUY":"SELL",atr=signal.Atr,anchor=signal.Reference,distance=(signal.Side>0?2:1.5)*signal.Atr},target_r=signal?.Side>0?12d:2d,stop_atr=0d,depths=new[]{0d},addition_confirmation=false});
}catch{results.Add(new{symbol="BTCUSD",error="FEED_BTC_BELUM_TERVERIFIKASI"});}
File.WriteAllText(args[1],JsonSerializer.Serialize(results));
