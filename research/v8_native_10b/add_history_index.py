from pathlib import Path
root=Path(__file__).resolve().parent/'native_diagnostics'
p=root/'native_replay/ApiStubs.cs';s=p.read_text()
needle=' public IAccount Account{get;}=new();'
assert s.count(needle)==1
code='''
 readonly Dictionary<(string,string),List<HistoricalTrade>> historyLabels=new();
 readonly Dictionary<(string,string),List<HistoricalTrade>> historyBaskets=new();int indexedHistory;
 void IndexHistory(){while(indexedHistory<History.Count){var h=History[indexedHistory++];var key=(h.SymbolName,h.Label);if(!historyLabels.TryGetValue(key,out var l))historyLabels[key]=l=new();l.Add(h);int first=h.Label.IndexOf('|'),second=first<0?-1:h.Label.IndexOf('|',first+1);if(second>=0){key=(h.SymbolName,h.Label.Substring(0,second+1));if(!historyBaskets.TryGetValue(key,out l))historyBaskets[key]=l=new();l.Add(h);}}}
 public IEnumerable<HistoricalTrade> HistoryForLabel(string symbol,string label){IndexHistory();return historyLabels.TryGetValue((symbol,label),out var l)?l:Array.Empty<HistoricalTrade>();}
 public IEnumerable<HistoricalTrade> HistoryForBasket(string symbol,string prefix){IndexHistory();return historyBaskets.TryGetValue((symbol,prefix),out var l)?l:Array.Empty<HistoricalTrade>();}
'''
s=s.replace(needle,code+needle);p.write_text(s)
for f in ['source/xau/RizanRobot.cs','source/eur/RizanRobot.cs']:
 p=root/f;s=p.read_text();old='History.Where(x=>x.Label==_state.PendingLabel&&x.SymbolName==SymbolName)';assert s.count(old)==1
 s=s.replace(old,'Host.HistoryForLabel(SymbolName,_state.PendingLabel)')
 old='History.Where(t=>t.SymbolName==SymbolName && t.Label.StartsWith(Prefix+"|"+b.AtUtc.Ticks+"|",StringComparison.Ordinal))'
 if old in s:s=s.replace(old,'Host.HistoryForBasket(SymbolName,Prefix+"|"+b.AtUtc.Ticks+"|")')
 p.write_text(s)
p=root/'native_replay/Replay.cs';s=p.read_text()
old='host.History.Where(h=>h.SymbolName==l.Symbol&&h.Label.StartsWith(label,StringComparison.Ordinal))';assert s.count(old)==1
s=s.replace(old,'host.HistoryForBasket(l.Symbol,label)')
old='host.History.Where(p=>p.SymbolName==l.Symbol&&p.Label.StartsWith(l.Prefix+"|"+((DateTime)basket.AtUtc).Ticks+"|",StringComparison.Ordinal))';assert s.count(old)==1
s=s.replace(old,'host.HistoryForBasket(l.Symbol,l.Prefix+"|"+((DateTime)basket.AtUtc).Ticks+"|")')
p.write_text(s)
