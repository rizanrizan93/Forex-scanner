using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using cAlgo.API.Internals;

namespace Rizan.Frozen;

public sealed class Checkpoint
{
    public int Schema { get; set; } = 1;
    public Signal? XauPendingSignal { get; set; }
    public DateTime XauResumeUtc { get; set; }
    public int PendingChildren { get; set; }
    public bool PendingFirstFill { get; set; }
    public string ExecutionModel { get; set; } = "";
    public string ContractHash { get; set; } = "";
    public long AccountNumber { get; set; }
    public string Symbol { get; set; } = "";
    public long Revision { get; set; }
    public DateTime EpochUtc { get; set; }
    public DateTime LastBarUtc { get; set; }
    public DateTime LastSignalUtc { get; set; }
    public DateTime LastRealExitUtc { get; set; }
    public double PeakEquity { get; set; }
    public bool Quarantined { get; set; }
    public string QuarantineReason { get; set; } = "";
    public EurState Eur { get; set; } = new();
    public Basket? Basket { get; set; }
    public string PendingLabel { get; set; } = "";
    public int PendingStage { get; set; }
    public int XauDaySignals { get; set; }
    public DateTime XauDay { get; set; }
}
public sealed class MacroPoint
{
    public double Delta { get; set; }
    public DateTime AvailableUtc { get; set; }
}
public sealed class NewsPoint
{
    public DateTime AtUtc { get; set; }
    public string Category { get; set; } = "";
}
public sealed class ExternalSnapshot
{
    public DateTime ProducedUtc { get; set; }
    public DateTime CoverageFromUtc { get; set; }
    public DateTime CoverageToUtc { get; set; }
    public bool ForexFactoryOk { get; set; }
    public bool BlsOk { get; set; }
    public MacroPoint? Dgs10 { get; set; }
    public MacroPoint? Dfii10 { get; set; }
    public List<NewsPoint> Events { get; set; } = new();
}

public abstract class RizanRobot : Robot
{
    [Parameter("Kirim order", DefaultValue = false, Group = "Eksekusi")]
    public bool EnableTrading { get; set; }
    [Parameter("Nomor akun penuh", DefaultValue = "", Group = "Eksekusi")]
    public string ExpectedAccount { get; set; } = "";
    [Parameter("Bridge WSS :25345", DefaultValue = "", Group = "Pemulihan dan data")]
    public string BridgeUrl { get; set; } = "";
    [Parameter("Token bridge", DefaultValue = "", Group = "Pemulihan dan data")]
    public string BridgeToken { get; set; } = "";
    [Parameter("Checkpoint pemulihan JSON", DefaultValue = "", Group = "Pemulihan dan data")]
    public string RecoveryCheckpoint { get; set; } = "";
    [Parameter("Batch per detik", DefaultValue = 1, MinValue = 1, MaxValue = 1, Group = "Eksekusi")]
    public int ChildrenPerSecond { get; set; }
    protected abstract FrozenContract Contract { get; }
    protected abstract string Prefix { get; }
    protected abstract string LoginSuffix { get; }
    private const string XauExecutionModel = "XAU_BATCH_SEND_REF_COOLDOWN_V1";
    private static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, Converters={new UtcDateTimeConverter()} };
    private const double RiskCap = .121;
    private const int LossCooldownDays = 3;
    private const double SendToleranceR = .20;
    private FrozenContract ExecutionContract => Contract with { RiskFraction = Math.Min(Contract.RiskFraction,RiskCap), Slip=.10, CommissionPerSide=.06 };
    private Bars _m1 = null!;
    private Checkpoint _state = new();
    private WebSocketClient? _bridge;
    private ExternalSnapshot? _snapshot;
    private long _remoteRevision, _persistedRevision, _sentRevision;
    private bool _bridgeReady, _saveInFlight;
    private bool _pendingPreparedHere, _pendingSubmitted;
    private DateTime _lastBridgeAck, _nextConnect, _nextPing, _nextTelemetry;
    private DateTime _opsSecond;
    private int _ops;
    private string _stateKey = "";
    private string _storageKey = "";
    private string _status = "STARTING";
    private long _decisionTicks, _intentTicks, _saveSentTicks;
    private double _lastAckRttMs = -1;
    private static double ElapsedMs(long ticks) => ticks==0 ? -1 : (System.Diagnostics.Stopwatch.GetTimestamp()-ticks)*1000d/System.Diagnostics.Stopwatch.Frequency;
    private readonly string _lease = Guid.NewGuid().ToString("N");
    private bool UsesBridge => !string.IsNullOrWhiteSpace(BridgeUrl);
    private bool Owns(Position p) => p.SymbolName == SymbolName && p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true;
    private Position[] Owned => Positions.Where(Owns).ToArray();
    private string Serialize() => JsonSerializer.Serialize(_state,Json);
    protected override void OnStart()
    {
        if(!SymbolName.StartsWith(Contract.Symbol,StringComparison.OrdinalIgnoreCase)) { Print("WRONG_SYMBOL: {0}",Contract.Symbol);Stop();return; }
        if(Account.AccountType!=AccountType.Hedged){Print("HEDGED_ACCOUNT_REQUIRED_FOR_INDIVIDUAL_CHILDREN");Stop();return;}
        if(Account.Asset.Name!="USD") { Print("USD_ACCOUNT_REQUIRED");Stop();return; }
        double units=Symbol.QuantityToVolumeInUnits(.01);
        if(Math.Abs(units-Contract.ChildUnits)>1e-8 || Math.Abs(Symbol.NormalizeVolumeInUnits(units,RoundingMode.Down)-units)>1e-8 || units<Symbol.VolumeInUnitsMin || units>Symbol.VolumeInUnitsMax)
        { Print("BROKER_CHILD_CONTRACT_MISMATCH: expected units {0}, broker {1}",Contract.ChildUnits,units);Stop();return; }
        _stateKey=Prefix+":"+Account.Number+":"+SymbolName;
        _storageKey=FrozenCore.CheckpointStorageKey(_stateKey);
        _m1=MarketData.GetBars(TimeFrame.Minute,SymbolName);
        DateTime wanted=Server.TimeInUtc.AddDays(-12);
        int loaded=0;while(_m1.Count>0 && _m1.OpenTimes[0]>wanted && loaded++<250){if(_m1.LoadMoreHistory()==0) break;}
        var local=string.IsNullOrWhiteSpace(RecoveryCheckpoint) ? LocalStorage.GetString(_storageKey,LocalStorageScope.Instance) : RecoveryCheckpoint;
        if(!string.IsNullOrWhiteSpace(local))
        {
            try { _state=JsonSerializer.Deserialize<Checkpoint>(local,Json) ?? throw new Exception("EMPTY_CHECKPOINT");ValidateState(); }
            catch(Exception e) { Print("CHECKPOINT_REJECTED: {0}",e.Message);Stop();return; }
        }
        else FreshState();
        _persistedRevision=_state.Revision;
        if(UsesBridge)
        {
            if(!Uri.TryCreate(BridgeUrl,UriKind.Absolute,out var url) || url.Port!=25345 || (url.Scheme!="wss" && !(url.Scheme=="ws" && url.IsLoopback)) || string.IsNullOrWhiteSpace(BridgeToken))
            { Print("BRIDGE_REQUIRES_WSS_PORT_25345_AND_TOKEN");Stop();return; }
            _bridge=new WebSocketClient();
            _bridge.TextReceived += e=>BeginInvokeOnMainThread(()=>ReceiveBridge(e.Text));
            _bridge.Disconnected += _=>BeginInvokeOnMainThread(()=>{_bridgeReady=false;_saveInFlight=false;_status="BRIDGE_DISCONNECTED";_nextConnect=Server.TimeInUtc.AddSeconds(15);});
            ConnectBridge();
        }
        else { RecoverAttempt();ReconcileExposure();Changed();Persist(); }
        if(Math.Abs(Account.PreciseLeverage-Contract.ReferenceLeverage)>1e-8) Print("LEVERAGE_DIFFERENT: actual {0}, reference {1}; margin uses broker estimate",Account.PreciseLeverage,Contract.ReferenceLeverage);
        Print("RIZAN {0} contract {1}; order={2}; account suffix={3}",Contract.Symbol,Contract.Hash,EnableTrading,LoginSuffix);
        _status=!BindingOk ? "ACCOUNT_NOT_BOUND" : Account.Equity<=0 ? "NO_EQUITY_MONITORING" : "STARTED";
        Print("RIZAN_STARTUP_OK version=1.2.1; status={0}; storageKeyLength={1}",_status,_storageKey.Length);
        Timer.Start(TimeSpan.FromSeconds(1));
    }
    private void FreshState()
    {
        var now=Server.TimeInUtc;
        _state=new(){ExecutionModel=Contract.Symbol=="XAUUSD" ? XauExecutionModel : "",ContractHash=Contract.Hash,Symbol=SymbolName,AccountNumber=Account.Number,EpochUtc=now,
            LastBarUtc=FrozenCore.Floor(now,1).AddMinutes(-1),PeakEquity=Math.Max(0,Account.Equity),
            Eur=new(){CursorUtc=FrozenCore.Floor(now,1).AddMinutes(-1)}};
        // A missing checkpoint on an account with previous owned activity is
        // not a new deployment. Manage protected exposure, do not reset budgets.
        if(Owned.Length>0 || History.Any(t=>t.SymbolName==SymbolName && t.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true))
        { _state.Quarantined=true;_state.QuarantineReason="CHECKPOINT_REQUIRED_FOR_EXISTING_DEPLOYMENT";RecoverExposureForExitOnly(); }
    }
    private void ValidateState()
    {
        if(_state.Schema!=1 || _state.ContractHash!=Contract.Hash || _state.Symbol!=SymbolName || _state.AccountNumber!=Account.Number || _state.Revision<0 || _state.Eur==null || !FrozenCore.ValidCheckpointPeak(_state.PeakEquity) || _state.LastBarUtc>Server.TimeInUtc || _state.EpochUtc>Server.TimeInUtc || _state.LastRealExitUtc>Server.TimeInUtc || _state.XauResumeUtc>Server.TimeInUtc.AddDays(LossCooldownDays+1))
            throw new Exception("CHECKPOINT_IDENTITY_OR_CLOCK_MISMATCH");
        if(Contract.Symbol=="XAUUSD" && _state.ExecutionModel!=XauExecutionModel)
        {
            if((_state.ExecutionModel!="" && _state.ExecutionModel!="XAU_ARCHIVE_PARITY_V2" && _state.ExecutionModel!="XAU_BATCH_STAGE_FIXED_REF_WAL_V1") || _state.Basket!=null || _state.PendingLabel!="" || Owned.Length>0)
                throw new Exception("EXECUTION_CHECKPOINT_MIGRATION_REQUIRES_FLAT");
            // Preserve account history, peak, revision and quarantine. Only flat legacy state can migrate.
            _state.ExecutionModel=XauExecutionModel;
        }
        if((_state.PendingFirstFill && _state.XauPendingSignal==null) || _state.PendingChildren<0 || (_state.PendingLabel!="" && (_state.Basket==null || _state.PendingChildren<1 || _state.PendingChildren>XauBatchExecution.MaxChildren || _state.PendingChildren>_state.Basket.QueueRemaining || _state.PendingStage!=_state.Basket.QueueStage || _state.PendingLabel!=Label(_state.Basket,_state.PendingStage,_state.Basket.Sequence)+"|"+_state.PendingChildren || (_state.PendingFirstFill && (_state.PendingStage!=0 || _state.Basket.Accepted.Sum()!=0)))) || (_state.PendingLabel=="" && (_state.PendingChildren!=0 || _state.PendingFirstFill)))
            throw new Exception("CHECKPOINT_BATCH_INTENT_INVALID");
        if(!new[]{_state.Eur.Fast,_state.Eur.Slow}.All(FrozenCore.Finite) || _state.Eur.CursorUtc>Server.TimeInUtc || _state.Eur.H1==null || _state.Eur.H1.Any(x=>!FrozenCore.Finite(x.Ema) || x.AtUtc>Server.TimeInUtc || x.Bias is not(-1 or 0 or 1)))
            throw new Exception("CHECKPOINT_FEEDBACK_INVALID");
        if(_state.Eur.Virtual!=null && (!new[]{_state.Eur.Virtual.Entry,_state.Eur.Virtual.Distance,_state.Eur.Virtual.LastClose}.All(x=>FrozenCore.Finite(x)&&x>0) || _state.Eur.Virtual.Side is not(1 or -1)))throw new Exception("CHECKPOINT_VIRTUAL_INVALID");
        if(_state.Basket!=null)
        {
            var b=_state.Basket;
            if(b.Side is not(1 or -1) || !new[]{b.Entry,b.Stop,b.Target,b.RiskBudget}.All(x=>FrozenCore.Finite(x)&&x>=0) || b.Accepted==null || b.Accepted.Length!=4 || b.StageRisk==null || b.StageRisk.Length!=4 || b.Accepted.Any(x=>x<0) || b.StageRisk.Any(x=>!FrozenCore.Finite(x)||x<0) || b.QueueStage< -1 || b.QueueStage>=Contract.Stages || _state.PendingStage<0 || _state.PendingStage>=Contract.Stages || b.QueueRemaining<0 || b.NextStage<0 || b.NextStage>Contract.Stages || b.Side*(b.Entry-b.Stop)<=0 || b.Side*(b.Target-b.Entry)<=0 || b.ExitUtc<=b.AtUtc || b.AtUtc>Server.TimeInUtc || b.InitialWanted<0 ||
                !new[]{b.ReferenceBalance,b.InitialRiskAllocation,b.RemainingStageBudget,b.UsedRisk,b.MaxDepthPrevious}.All(x=>FrozenCore.Finite(x)&&x>=0) || b.ReferenceBalance<=0 ||
                (Contract.Symbol=="XAUUSD" ? b.Scale!=1 : b.Scale!=1 && b.Scale!=.625 && b.Scale!=.1) ||
                b.RiskBudget>b.ReferenceBalance*ExecutionContract.RiskFraction*b.Scale+1e-8 || b.InitialRiskAllocation+b.RemainingStageBudget>b.RiskBudget+1e-8 ||
                Math.Abs(b.Target-b.Entry-Math.Abs(b.Entry-b.Stop)*b.Side*Contract.TargetR)>Symbol.TickSize*1.1)
                throw new Exception("CHECKPOINT_BASKET_INVALID");
        }
    }
    private void ConnectBridge()
    {
        if(_bridge==null) return;
        _nextConnect=Server.TimeInUtc.AddSeconds(30);
        try
        {
            _bridge.Connect(new Uri(BridgeUrl));
            _bridge.Send(JsonSerializer.Serialize(new{type="hello",token=BridgeToken,key=_stateKey,contract=Contract.Hash,lease=_lease}));
        }
        catch(Exception e){_status="BRIDGE_CONNECT_FAILED";Print("{0}: {1}",_status,e.GetType().Name);}
    }
    private void ReceiveBridge(string text)
    {
        try
        {
            using var doc=JsonDocument.Parse(text);var root=doc.RootElement;var type=root.GetProperty("type").GetString();
            if(type=="ready")
            {
                _remoteRevision=root.GetProperty("revision").GetInt64();
                if(root.TryGetProperty("state",out var value) && value.ValueKind!=JsonValueKind.Null)
                { _state=JsonSerializer.Deserialize<Checkpoint>(value.GetRawText(),Json)!;ValidateState(); }
                else if(_state.Revision>0) { /* local/manual recovery will be written after lease acquisition */ }
                _bridgeReady=true;_saveInFlight=false;_persistedRevision=_state.Revision;_lastBridgeAck=Server.TimeInUtc;
                RecoverAttempt();ReconcileExposure();Changed();Persist();_status="BRIDGE_READY";
            }
            else if(type=="ack")
            {
                long acknowledged=root.GetProperty("client_revision").GetInt64();
                if(!_saveInFlight || acknowledged!=_sentRevision){_status="BRIDGE_ACK_NOT_CURRENT";return;}
                _remoteRevision=root.GetProperty("revision").GetInt64();
                _persistedRevision=root.GetProperty("client_revision").GetInt64();
                if(_persistedRevision==_sentRevision)_lastAckRttMs=ElapsedMs(_saveSentTicks);
                _saveInFlight=false;_lastBridgeAck=Server.TimeInUtc;
                Persist();ProcessQueue(Server.TimeInUtc);
            }
            else if(type=="snapshot") _snapshot=JsonSerializer.Deserialize<ExternalSnapshot>(root.GetProperty("data").GetRawText(),Json);
            else if(type=="pong") _lastBridgeAck=Server.TimeInUtc;
            else if(type=="error") { _bridgeReady=false;_saveInFlight=false;Quarantine("BRIDGE_"+root.GetProperty("code").GetString()); }
        }
        catch(Exception e){_bridgeReady=false;_status="BRIDGE_MESSAGE_INVALID";Print("{0}: {1}",_status,e.Message);}
    }
    private void Changed(){_state.Revision++;}
    private void Persist()
    {
        if(string.IsNullOrEmpty(_storageKey))return;
        var json=Serialize();LocalStorage.SetString(_storageKey,json,LocalStorageScope.Instance);LocalStorage.Flush(LocalStorageScope.Instance);
        if(!UsesBridge){_persistedRevision=_state.Revision;return;}
        if(!_bridgeReady || _saveInFlight || _state.Revision<=_persistedRevision)return;
        try
        {
            _sentRevision=_state.Revision;_saveInFlight=true;_saveSentTicks=System.Diagnostics.Stopwatch.GetTimestamp();
            _bridge!.Send(JsonSerializer.Serialize(new{type="save",base_revision=_remoteRevision,client_revision=_sentRevision,state=_state}));
        }
        catch{_saveInFlight=false;_bridgeReady=false;}
    }
    private bool Durable => _persistedRevision>=_state.Revision && (!UsesBridge || (_bridgeReady && (Server.TimeInUtc-_lastBridgeAck).TotalSeconds<30));
    private void Quarantine(string reason){_state.Quarantined=true;_state.QuarantineReason=reason;Changed();Print("QUARANTINED: {0}",reason);Persist();}
    private bool BindingOk => ExpectedAccount==Account.Number.ToString() && (!Account.IsLive || ExpectedAccount.EndsWith(LoginSuffix,StringComparison.Ordinal));
    private List<Candle> ClosedM1(DateTime now)
    {
        var r=new List<Candle>();for(int i=0;i<_m1.Count;i++)
        { var at=DateTime.SpecifyKind(_m1.OpenTimes[i],DateTimeKind.Utc);if(at.AddMinutes(1)>now)break;
            r.Add(new(at,_m1.OpenPrices[i],_m1.HighPrices[i],_m1.LowPrices[i],_m1.ClosePrices[i])); }
        return r;
    }
    protected override void OnTimer()
    {
        try { Cycle(); }
        catch(Exception e){Quarantine("RUNTIME_EXCEPTION:"+e.GetType().Name);Print(e.Message);}
    }
    private void Cycle()
    {
        var now=Server.TimeInUtc;
        if(UsesBridge)
        {
            if(!_bridgeReady && now>=_nextConnect)ConnectBridge();
            if(_bridgeReady && now>=_nextPing){_bridge!.Send("{\"type\":\"ping\"}");_nextPing=now.AddSeconds(10);}
        }
        ManagePositions(now);
        if(UsesBridge && !_bridgeReady){Telemetry(now);return;}
        var bars=ClosedM1(now);if(bars.Count<100){_status="WARMUP_M1";Telemetry(now);return;}
        var latest=bars[^1].OpenUtc;
        if(latest>_state.LastBarUtc)
        {
            // Updating only at completed M1 boundaries makes the peak sampling explicit.
            _state.PeakEquity=Math.Max(_state.PeakEquity,Account.Equity);
            List<Feature>? f=null;
            if(Contract.Symbol=="EURUSD")
            {
                f=FrozenCore.EurFeatures(bars,latest.AddMinutes(1),_state.Eur);
                if(_state.Eur.CursorUtc<bars[0].OpenUtc.AddMinutes(-5))Quarantine("VIRTUAL_HISTORY_GAP");
                else FrozenCore.AdvanceVirtual(bars,f,_state.Eur);
            }
            if(_state.Basket!=null && Contract.Confirmed)
            {
                var b=_state.Basket;var distance=Math.Abs(b.Entry-b.Stop);
                foreach(var bar in bars.Where(x=>x.OpenUtc>_state.LastBarUtc && x.OpenUtc>=b.AtUtc))
                { double extreme=b.Side==1 ? bar.Low+(Symbol.Ask-Symbol.Bid) : bar.High;b.MaxDepthPrevious=Math.Max(b.MaxDepthPrevious,b.Side*(b.Entry-extreme)/distance); }
                if(Owned.Length>0 && b.QueueStage<0 && b.NextStage<Contract.Stages && latest.AddMinutes(1)<=b.AtUtc.AddMinutes(Contract.AddMinutes))
                {
                    var at=latest.AddMinutes(1);
                    var confirmationAt=FrozenCore.Floor(at,5);
                    bool confirmed=FrozenCore.XauConfirmation(bars,at,b.Side);
                    double fill=Quote(b.Side)+b.Side*ExecutionContract.Slip;
                    if(confirmed && confirmationAt!=b.LastConfirmationUtc && b.MaxDepthPrevious>=Contract.Depths[b.NextStage] && b.Side*(b.Entry-fill)>=.05*distance)
                    { b.LastConfirmationUtc=confirmationAt;QueueStage(b.NextStage,fill); }
                }

            }
            _state.LastBarUtc=latest;Changed();
            if(_state.Basket==null && EnableTrading && BindingOk && !_state.Quarantined && NoForeignExposure())
            {
                Signal? signal=Contract.Symbol=="EURUSD" ? f!.Select(FrozenCore.EurSignal).LastOrDefault(s=>s!=null && s.AtUtc==latest.AddMinutes(1)) : FrozenCore.XauSignal(bars,latest.AddMinutes(1));
                if(signal!=null && signal.AtUtc>_state.LastSignalUtc && signal.AtUtc>_state.LastRealExitUtc && (now-signal.AtUtc).TotalSeconds>=0 && (now-signal.AtUtc).TotalSeconds<60)
                    PrepareBasket(signal,now);
            }
        }
        if(_state.Basket!=null && !Contract.Confirmed && _state.Basket.QueueStage<0 && _state.Basket.NextStage<Contract.Stages && Owned.Length>0)
        {
            var b=_state.Basket;var fill=Quote(b.Side);double depth=b.Side*(b.Entry-fill)/Math.Abs(b.Entry-b.Stop);
            if(now<=b.AtUtc.AddMinutes(Contract.AddMinutes) && depth>=Contract.Depths[b.NextStage])QueueStage(b.NextStage,fill);
        }
        // Prepare and persist the pending order intent with the basket in one save.
        // ProcessQueue still requires the matching durable ACK before sending.
        ProcessQueue(now);Persist();Telemetry(now);
    }
    private bool NoForeignExposure() => !Positions.Any(p=>!Owns(p)) && !PendingOrders.Any();
    private double Quote(int side) => side==1 ? Symbol.Ask : Symbol.Bid;
    private bool GeometryOk(Basket b,double fill) => FrozenCore.Finite(fill) && b.Side*(fill-b.Stop)>Symbol.TickSize && b.Side*(b.Target-fill)>Symbol.TickSize;
    private bool ExternalOk(Signal s,DateTime now)
    {
        if(Contract.Symbol!="XAUUSD")return true;
        var x=_snapshot;
        if(x==null || !x.ForexFactoryOk || !x.BlsOk || x.ProducedUtc>now.AddSeconds(5) || (now-x.ProducedUtc).TotalSeconds>180 || x.CoverageFromUtc>s.AtUtc.AddMinutes(-30) || x.CoverageToUtc<s.AtUtc.AddMinutes(495))
        {_status="XAU_MACRO_NEWS_FEED_REQUIRED";return false;}
        var macro=s.Side==1 ? x.Dfii10 : x.Dgs10;
        if(macro==null || !FrozenCore.Finite(macro.Delta) || macro.AvailableUtc>s.AtUtc || s.AtUtc-macro.AvailableUtc>TimeSpan.FromDays(7))
        {_status="XAU_MACRO_STALE_OR_FUTURE";return false;}
        if(s.Side*macro.Delta>0){_status="XAU_MACRO_DIRECTION_BLOCK";return false;}
        var scope=new[]{"NFP","CPI","PPI","JOLTS","ECI","FOMC"};
        if(x.Events.Any(e=>scope.Contains(e.Category) && e.AtUtc>=s.AtUtc.AddMinutes(-30) && e.AtUtc<=s.AtUtc.AddMinutes(495)))
        {_status="XAU_PLANNED_HOLD_NEWS_EXPOSURE";return false;}
        return true;
    }
    private void PrepareBasket(Signal s,DateTime now)
    {
        if(now<_state.XauResumeUtc){_status="XAU_LOSS_COOLDOWN";return;}
        if(!ExternalOk(s,now))return;
        _state.XauPendingSignal=s;
        if(Symbol.Ask-Symbol.Bid>(Contract.Symbol=="XAUUSD" ? 1.5 : .00022)){_status="SPREAD_ABOVE_LIMIT";return;}
        if(Contract.Symbol=="XAUUSD")
        {
            var day=s.AtUtc.AddHours(7).Date;
            if(_state.XauDay!=day){_state.XauDay=day;_state.XauDaySignals=0;}
            if(_state.XauDaySignals>=6){_status="XAU_DAILY_BASKET_LIMIT";return;}
        }
        var side=s.Side==1 ? TradeType.Buy : TradeType.Sell;double entry=Quote(s.Side)+(Contract.Symbol=="XAUUSD" ? s.Side*ExecutionContract.Slip : 0);
        // SELL structural anchor is BID-based and is converted to ASK geometry.
        if(Contract.Symbol=="XAUUSD" && s.Side==-1)s=s with{Anchor=s.Anchor+Symbol.Ask-Symbol.Bid};
        double margin=Symbol.GetEstimatedMargin(side,Contract.ChildUnits);
        var b=FrozenCore.StartBasket(ExecutionContract,s,entry,Account.Balance,Account.Equity,Account.FreeMargin,Account.Margin,margin,
            Contract.Symbol=="EURUSD" ? FrozenCore.EurScale(_state.Eur) : 1,_state.PeakEquity,
            Contract.Symbol=="XAUUSD" ? Symbol.Ask-Symbol.Bid+ExecutionContract.Slip : 0);
        _state.LastSignalUtc=s.AtUtc;Changed();
        if(b==null){_status="NO_INTEGER_CHILD_WITHIN_BUDGET";return;}
        _state.Basket=b;_decisionTicks=System.Diagnostics.Stopwatch.GetTimestamp();if(Contract.Symbol=="XAUUSD")_state.XauDaySignals++;
        _status="BASKET_PREPARED";Changed();
    }
    private void QueueStage(int stage,double fill)
    {
        var b=_state.Basket!;if(!GeometryOk(b,fill))return;
        int wanted=FrozenCore.StageWanted(ExecutionContract,b,stage,fill,Account.Equity,Account.FreeMargin,
            Symbol.GetEstimatedMargin(b.Side==1 ? TradeType.Buy : TradeType.Sell,Contract.ChildUnits),Account.Margin);
        b.QueueStage=stage;b.QueueRemaining=wanted;b.NextStage=stage+1;Changed();
        if(wanted==0)b.QueueStage=-1;
    }
    private string Label(Basket b,int stage,long sequence) => Prefix+"|"+b.AtUtc.Ticks+"|"+stage+"|"+sequence;
    private string Comment(Basket b) => FormattableString.Invariant($"RZ1;{b.AtUtc.Ticks};{b.ExitUtc.Ticks};{b.Side};{b.Stop:R};{b.Target:R}");
    private void ProcessQueue(DateTime now)
    {
        var b=_state.Basket;if(b==null||b.QueueStage<0||b.QueueRemaining<=0||_state.Quarantined||!EnableTrading||!BindingOk||!NoForeignExposure())return;
        var second=FrozenCore.Floor(now,1).AddSeconds(now.Second);
        if(_opsSecond!=second){_opsSecond=second;_ops=0;}if(_ops>=1)return;
        if(now>=b.ExitUtc||(b.QueueStage==0&&now>=b.AtUtc.AddMinutes(1))||(b.QueueStage>0&&now>b.AtUtc.AddMinutes(Contract.AddMinutes))){CancelQueue();return;}
        if(b.QueueStage>0&&Owned.Length==0){CancelQueue();return;}
        double quote=Quote(b.Side),spread=Symbol.Ask-Symbol.Bid;
        if(!GeometryOk(b,quote)||spread>1.5){CancelQueue();_status="BATCH_PRICE_ZONE_OR_GEOMETRY_BLOCK";return;}
        bool first=b.Accepted.Sum()==0;
        var side=b.Side==1?TradeType.Buy:TradeType.Sell;
        int cap=Math.Min(b.QueueRemaining,Math.Min(XauBatchExecution.MaxChildren,FrozenCore.FloorCount(Symbol.VolumeInUnitsMax/Contract.ChildUnits)));
        int quantity=_state.PendingLabel!="" ? _state.PendingChildren : XauBatchExecution.Count(ExecutionContract,b,b.QueueStage,quote,Account.Equity,Account.FreeMargin,Account.Margin,spread,cap,first,q=>Symbol.GetEstimatedMargin(side,q*Contract.ChildUnits));
        // Startup guarantees one virtual child lies exactly on the broker volume grid.
        double volume=quantity*Contract.ChildUnits;
        if(quantity<1||volume<Symbol.VolumeInUnitsMin||Math.Abs(Symbol.NormalizeVolumeInUnits(volume,RoundingMode.Down)-volume)>1e-8){CancelQueue();_status="NO_BATCH_VOLUME_WITHIN_BUDGET";return;}
        if(_state.PendingLabel=="")
        {_pendingPreparedHere=true;_pendingSubmitted=false;_intentTicks=System.Diagnostics.Stopwatch.GetTimestamp();b.Sequence++;_state.PendingStage=b.QueueStage;_state.PendingChildren=quantity;_state.PendingFirstFill=first;_state.PendingLabel=Label(b,b.QueueStage,b.Sequence)+"|"+quantity;Changed();Persist();if(!Durable)return;}
        if(!Durable)return;
        quantity=_state.PendingChildren;
        if(_state.PendingFirstFill)
        {
            // Durable intent authorizes a bounded send-reference recipe and a maximum volume.
            // Broker comment records the exact derived geometry and requested count for recovery.
            var fresh=XauSendReference.Refresh(ExecutionContract,_state.XauPendingSignal,b,quote,spread,Account.FreeMargin,Symbol.GetEstimatedMargin(side,Contract.ChildUnits),SendToleranceR);
            if(fresh==null){CancelQueue();_status="XAU_SEND_REFERENCE_OUTSIDE_POLICY";return;}
            quantity=Math.Min(quantity,XauBatchExecution.Count(ExecutionContract,fresh,0,quote,Account.Equity,Account.FreeMargin,Account.Margin,spread,Math.Min(fresh.QueueRemaining,quantity),true,q=>Symbol.GetEstimatedMargin(side,q*Contract.ChildUnits)));
            if(quantity<1){CancelQueue();_status="XAU_SEND_REFERENCE_NO_VOLUME";return;}
            _state.Basket=b=fresh;
        }
        volume=quantity*Contract.ChildUnits;
        // Recheck the full persisted request after any bridge wait; never resize an intent silently.
        if(!XauBatchExecution.PlannedOk(ExecutionContract,b,_state.PendingStage,quote,Account.Equity,Account.FreeMargin,Account.Margin,Symbol.GetEstimatedMargin(side,volume),spread,quantity,_state.PendingFirstFill)){CancelQueue();_status="BATCH_BUDGET_CHANGED_BEFORE_SEND";return;}
        _pendingSubmitted=true;
        _ops++;
        double distance=Math.Abs(b.Entry-b.Stop);
        double decisionMs=ElapsedMs(_decisionTicks),intentMs=ElapsedMs(_intentTicks);long requestTicks=System.Diagnostics.Stopwatch.GetTimestamp();
        var trade=ExecuteMarketOrder(side,SymbolName,volume,_state.PendingLabel,
            Math.Abs(quote-b.Stop)/Symbol.PipSize,
            Math.Abs(b.Target-quote)/Symbol.PipSize,Comment(b)+(_state.PendingFirstFill ? ";"+b.InitialWanted+";"+quantity+";"+spread.ToString("R",System.Globalization.CultureInfo.InvariantCulture) : ""));
        Print("RIZAN_LATENCY signal_utc={0:O}; decision_to_request_ms={1:F3}; intent_to_request_ms={2:F3}; save_ack_rtt_ms={3:F3}; broker_request_to_result_ms={4:F3}; batch_children={5}",b.AtUtc,decisionMs,intentMs,_lastAckRttMs,ElapsedMs(requestTicks),quantity);
        if(!trade.IsSuccessful||trade.Position==null){Quarantine("BATCH_ORDER_RESULT_UNCERTAIN_OR_REJECTED:"+trade.Error);return;}
        var p=trade.Position;
        // Frozen common absolute SL/TP stay unchanged after the fill.
        var protection=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);
        bool protectionInvalid=Math.Abs(p.VolumeInUnits-volume)>1e-8||p.TradeType!=side||!protection.IsSuccessful||p.StopLoss==null||p.TakeProfit==null||Math.Abs(p.StopLoss.Value-b.Stop)>Symbol.TickSize*1.1||Math.Abs(p.TakeProfit.Value-b.Target)>Symbol.TickSize*1.1;
        bool budgetInvalid=!XauBatchExecution.ActualOk(ExecutionContract,b,_state.PendingStage,p.EntryPrice,Account.Equity,Account.Margin,quantity,Math.Abs(p.Commissions));
        if(protectionInvalid||budgetInvalid)
        {
            var closed=ClosePosition(p);
            if(protectionInvalid||!closed.IsSuccessful){Quarantine(closed.IsSuccessful?"BATCH_FILL_OR_PROTECTION_INVALID_CLOSED":"BATCH_INVALID_POSITION_CLOSE_FAILED");return;}
            ClearPending();CancelQueue();_status="BATCH_BUDGET_REJECTED_CLOSED";Changed();Persist();return;
        }
        XauBatchExecution.Accept(ExecutionContract,b,_state.PendingStage,p.EntryPrice,quantity,Math.Abs(p.Commissions));ClearPending();
        _status="BROKER_BATCH_ACCEPTED";Print("RIZAN_BATCH children={0}; lots={1}; equity={2}; margin={3}",quantity,Symbol.VolumeInUnitsToQuantity(volume),Account.Equity,Account.Margin);Changed();Persist();
    }
    private void ClearPending(){_pendingPreparedHere=false;_pendingSubmitted=false;_state.PendingLabel="";_state.PendingChildren=0;_state.PendingFirstFill=false;}
    private void CancelQueue(){if(_state.Basket!=null){_state.Basket.QueueRemaining=0;_state.Basket.QueueStage=-1;if(!_state.Quarantined)ClearPending();Changed();}}
    private void RecoverAttempt()
    {
        if(_state.PendingLabel==""||_state.Basket==null)return;
        var positions=Owned.Where(x=>x.Label==_state.PendingLabel).ToArray();
        var history=History.Where(x=>x.Label==_state.PendingLabel&&x.SymbolName==SymbolName).ToArray();
        if(positions.Length>1||(positions.Length==0&&history.Length==0)){Quarantine("PREPARED_ATTEMPT_NOT_RECONCILED_NO_RETRY");return;}
        int quantity=_state.PendingChildren;var b=_state.Basket;
        double totalVolume=positions.Sum(x=>x.VolumeInUnits)+history.Sum(x=>x.VolumeInUnits);
        if(_state.PendingFirstFill)
        {
            string[] comments=positions.Select(p=>p.Comment).Concat(history.Select(p=>p.Comment)).Distinct().ToArray();
            if(comments.Length!=1 || !XauSendReference.Restore(ExecutionContract,_state.XauPendingSignal,b,comments[0],quantity,SendToleranceR,out var restored,out var requested))
            {Quarantine("RECOVERED_SEND_REFERENCE_POLICY_INVALID");return;}
            _state.Basket=b=restored!;quantity=requested;
        }
        if(XauBatchExecution.ChildrenForVolume(totalVolume,Contract.ChildUnits)!=quantity||history.Select(x=>(long)x.PositionId).Concat(positions.Select(x=>(long)x.Id)).Distinct().Count()!=1||positions.Any(x=>x.TradeType!=(b.Side==1?TradeType.Buy:TradeType.Sell))||history.Any(x=>x.TradeType!=(b.Side==1?TradeType.Buy:TradeType.Sell)))
        {Quarantine("RECOVERED_BATCH_VOLUME_OR_IDENTITY_INVALID");return;}
        double entry=positions.Length>0?positions[0].EntryPrice:history[0].EntryPrice;
        if(history.Any(x=>Math.Abs(x.EntryPrice-entry)>Symbol.TickSize)){Quarantine("RECOVERED_BATCH_ENTRY_INCONSISTENT");return;}

        if(!FrozenCore.Finite(entry)||entry<=0||b.QueueRemaining<quantity||b.QueueStage!=_state.PendingStage){Quarantine("RECOVERED_FILL_GEOMETRY_INVALID");return;}
        double commission=positions.Sum(x=>Math.Abs(x.Commissions))+history.Sum(x=>Math.Abs(x.Commissions));
        bool budgetOk=XauBatchExecution.ActualOk(ExecutionContract,b,_state.PendingStage,entry,Account.Equity,Account.Margin,quantity,commission);
        foreach(var p in positions){var r=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);if(!r.IsSuccessful||p.StopLoss==null||p.TakeProfit==null||Math.Abs(p.StopLoss.Value-b.Stop)>Symbol.TickSize*1.1||Math.Abs(p.TakeProfit.Value-b.Target)>Symbol.TickSize*1.1){Quarantine("RECOVERED_BATCH_PROTECTION_INVALID");ClosePosition(p);return;}}
        XauBatchExecution.Accept(ExecutionContract,b,_state.PendingStage,entry,quantity,commission);ClearPending();Changed();
        if(!budgetOk)Quarantine("RECOVERED_BATCH_BUDGET_EXCEEDED_NO_ADDS");
    }
    private void ReconcileExposure()
    {
        if(Owned.Length==0)return;
        var b=_state.Basket;
        if(b==null){Quarantine("BROKER_EXPOSURE_WITHOUT_CHECKPOINT_BASKET");RecoverExposureForExitOnly();return;}
        if(true)
        {
            if(Owned.Any(p=>XauBatchExecution.ExposureStage(Contract,b,Prefix,p.Label,p.VolumeInUnits)<0)||Enumerable.Range(0,Contract.Stages).Any(stage=>Owned.Where(p=>XauBatchExecution.ExposureStage(Contract,b,Prefix,p.Label,p.VolumeInUnits)==stage).Sum(p=>XauBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits))>b.Accepted[stage]))
            {Quarantine("BROKER_BATCH_STAGE_OR_VOLUME_MISMATCH");return;}
        }
        if(Owned.Sum(p=>XauBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits))>b.Accepted.Sum() || Owned.GroupBy(p=>p.Label).Any(g=>g.Count()>1) || Owned.Any(p=>
            !p.Label.StartsWith(Prefix+"|"+b.AtUtc.Ticks+"|",StringComparison.Ordinal) ||
            XauBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits)<1 || p.TradeType!=(b.Side==1 ? TradeType.Buy : TradeType.Sell)))
            Quarantine("BROKER_EXPOSURE_CHECKPOINT_MISMATCH");
    }
    private void RecoverExposureForExitOnly()
    {
        var owned=Owned;if(owned.Length==0)return;
        var parts=owned[0].Comment?.Split(';');
        try
        {
            if(parts==null || parts.Length<6 || parts[0]!="RZ1")return;
            var b=new Basket{AtUtc=new DateTime(long.Parse(parts[1]),DateTimeKind.Utc),ExitUtc=new DateTime(long.Parse(parts[2]),DateTimeKind.Utc),Side=int.Parse(parts[3]),
                Stop=double.Parse(parts[4],System.Globalization.CultureInfo.InvariantCulture),Target=double.Parse(parts[5],System.Globalization.CultureInfo.InvariantCulture),Entry=owned[0].EntryPrice,
                NextStage=Contract.Stages,QueueStage=-1,ReferenceBalance=Math.Max(.01,Account.Balance),Scale=1};
            b.Entry=b.Stop+b.Side*Math.Abs(b.Target-b.Stop)/(Contract.TargetR+1);
            _state.Basket=b;
        }
        catch{Print("EXPOSURE_METADATA_INVALID; inspect owned positions");}
    }
    private void ManagePositions(DateTime now)
    {
        var owned=Owned;
        if(_state.Basket==null && owned.Length>0){Quarantine("OWNED_EXPOSURE_WITHOUT_BASKET_STATE");RecoverExposureForExitOnly();}
        var b=_state.Basket;if(b==null)return;
        foreach(var p in owned)
        {
            if(p.StopLoss==null || p.TakeProfit==null){Quarantine("BROKER_PROTECTION_MISSING");var r=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);if(!r.IsSuccessful)ClosePosition(p);}
            if(now>=b.ExitUtc){var closed=ClosePosition(p);if(!closed.IsSuccessful)Quarantine("EXPIRY_CLOSE_FAILED");}
        }
        if(now>b.AtUtc.AddMinutes(Contract.AddMinutes))CancelQueue();
        if(Owned.Length==0 && (b.Accepted.Sum()>0 || b.QueueStage<0 || now>=b.ExitUtc))
        {if(_state.PendingLabel!=""){if(_pendingPreparedHere && !_pendingSubmitted)CancelQueue();else Quarantine("ORPHAN_PENDING_ATTEMPT");}
            if(b.Accepted.Sum()>0)
            {
                var closed=History.Where(t=>t.SymbolName==SymbolName && t.Label.StartsWith(Prefix+"|"+b.AtUtc.Ticks+"|",StringComparison.Ordinal)).ToArray();
                if(XauBatchExecution.ChildrenForVolume(closed.Sum(t=>t.VolumeInUnits),Contract.ChildUnits)!=b.Accepted.Sum())
                {_status="XAU_CLOSED_HISTORY_SETTLEMENT_WAIT";return;}
                if(closed.Sum(t=>t.NetProfit)<0)_state.XauResumeUtc=now.AddDays(LossCooldownDays);
            }
            _state.XauPendingSignal=null;
            _state.LastRealExitUtc=FrozenCore.Floor(now,1);_state.Basket=null;Changed();}
    }
    private void Telemetry(DateTime now)
    {
        if(now<_nextTelemetry)return;_nextTelemetry=now.AddMinutes(1);
        Print("RIZAN_STATE status={0}; trading={1}; accountBound={2}; positions={3}; quarantined={4}; reason={5}",_status,EnableTrading,BindingOk,Owned.Length,_state.Quarantined,_state.QuarantineReason);
        Print("RIZAN_CHECKPOINT {0}",Serialize());
    }
    protected override void OnStop(){Persist();_bridge?.Dispose();Print("RIZAN stopped. Broker SL/TP remain attached; restart requires checkpoint reconciliation.");}
}
