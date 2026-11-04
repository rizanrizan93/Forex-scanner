using System;using System.IO;using System.Linq;using System.Collections.Generic;using System.Globalization;using System.Text.Json;using Rizan.Portfolio;
using X=Rizan.Portfolio.Xau;
var rows=new List<X.Candle>();foreach(var line in File.ReadLines(args[0]).Skip(1)){var p=line.Split(',');rows.Add(new(DateTime.Parse(p[0],CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal),double.Parse(p[1],CultureInfo.InvariantCulture),double.Parse(p[2],CultureInfo.InvariantCulture),double.Parse(p[3],CultureInfo.InvariantCulture),double.Parse(p[4],CultureInfo.InvariantCulture)));}
var m=X.FrozenCore.Aggregate(rows,5,rows[^1].End(1));var h=X.FrozenCore.Aggregate(rows,60,rows[^1].End(1));var atr=X.FrozenCore.Atr(m);var bias=X.FrozenCore.Strict(h);int hj=-1;var results=new List<X.Signal>();
for(int i=0;i<m.Count;i++){var at=m[i].End(5);while(hj+1<h.Count&&h[hj+1].End(60)<=at)hj++;if(hj<199)continue;var s=CompressionEntry.Evaluate(m,atr,i,bias[hj],at,h[hj].Count);if(s!=null)results.Add(s);}
File.WriteAllText(args[1],JsonSerializer.Serialize(results));Console.WriteLine(JsonSerializer.Serialize(new{AdditionalRaw=results.Count,ComputedFromM1=true,HistoricalCacheNotUsedToGenerate=true}));
var m15=X.FrozenCore.Aggregate(rows,15,rows[^1].End(1));var raw=X.FrozenCore.XauRaw(m,atr,X.FrozenCore.AlignStrict(h,60,m),X.FrozenCore.AlignStrict(m15,15,m));
hj=-1;int mj=-1;var original=new List<X.Signal>();
for(int i=0;i<m.Count;i++){var at=m[i].End(5);while(hj+1<h.Count&&h[hj+1].End(60)<=at)hj++;while(mj+1<m15.Count&&m15[mj+1].End(15)<=at)mj++;
 if(i+1<100||hj+1<200||mj+1<200||!CompressionEntry.EligibleTime(at))continue;
 var v=raw[i];int side=v.Sell?-1:v.Buy?1:0;if(side!=0)original.Add(new(at,side,0,atr[i],side==1?v.BuyAnchor:v.SellAnchor));}
File.WriteAllText(args[1]+".original.json",JsonSerializer.Serialize(original));Console.WriteLine(JsonSerializer.Serialize(new{OriginalRaw=original.Count,ComputedFromNativeFrozenCore=true}));
