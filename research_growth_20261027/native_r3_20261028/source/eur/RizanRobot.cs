using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
using cAlgo.API.Internals;

namespace Rizan.Portfolio.Eur;

public sealed class Checkpoint
{
    public int Schema { get; set; } = 3;
    public string ExecutionModel { get; set; } = "";
    public int PendingChildren { get; set; }
    public bool PendingFirstFill { get; set; }
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

public abstract class RizanRobot : Rizan.Portfolio.EngineContext
{
    protected RizanRobot(RizanPortfolio host, string instrument) : base(host, instrument) {}

    public bool EnableTrading { get; set; }
    public string ExpectedAccount { get; set; } = "";
    public string BridgeUrl { get; set; } = "";
    public string BridgeToken { get; set; } = "";
    public string RecoveryCheckpoint { get; set; } = "";
    private int ChildrenPerSecond => 3;
    protected abstract FrozenContract Contract { get; }
    protected abstract string Prefix { get; }
    protected abstract string LoginSuffix { get; }
    private static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, Converters={new UtcDateTimeConverter()} };
    private Bars _m1 = null!;
    private Checkpoint _state = new();
    private WebSocketClient? _bridge;
    private ExternalSnapshot? _snapshot;
    private long _remoteRevision, _persistedRevision, _sentRevision;
    private bool _bridgeReady, _saveInFlight;
    // Session-only authorization: a process restart must handshake/reconcile again.
    private bool _continuityReady;
    private long _localRevision = -1;
    private bool _pendingPreparedHere, _pendingSubmitted;
    // Lifecycle transitions run on the cTrader main thread. Fence stale callbacks.
    private bool _connecting, _stopping, _closing;
    private int _bridgeGeneration, _backoffAttempt, _validHeartbeats;
    private DateTime _handshakeDeadline, _saveDeadline, _healthySince;
    private readonly Random _reconnectJitter = new();
    private DateTime _lastBridgeAck, _nextConnect, _nextPing, _nextTelemetry;
    private DateTime _opsSecond;
    private int _ops;
    private string _stateKey = "";
    private string _storageKey = "";
    private string _status = "STARTING";
    private readonly string _lease = Guid.NewGuid().ToString("N");
    private bool Batch => Contract.Symbol=="EURUSD";
    private string ExecutionModel => Batch ? EurBatchExecution.Model : "CHILD_V1";
    private int OrderRate => Batch ? 1 : ChildrenPerSecond;
    internal bool BridgeEntryHealthy => !UsesBridge || (_bridgeReady && (Server.TimeInUtc-_lastBridgeAck).TotalSeconds<25);
    private bool UsesBridge => !string.IsNullOrWhiteSpace(BridgeUrl);
    private bool Owns(Position p) => p.SymbolName == SymbolName && p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true;
    private Position[] Owned => Positions.Where(Owns).ToArray();
    private string Serialize() => JsonSerializer.Serialize(_state,Json);
    public override void OnStart()
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
            ConnectBridge();
        }
        else { RecoverAttempt();ReconcileExposure();Changed();Persist(); }
        if(Math.Abs(Account.PreciseLeverage-Contract.ReferenceLeverage)>1e-8) Print("LEVERAGE_DIFFERENT: actual {0}, reference {1}; margin uses broker estimate",Account.PreciseLeverage,Contract.ReferenceLeverage);
        Print("RIZAN {0} contract {1}; order={2}; account suffix={3}",Contract.Symbol,Contract.Hash,EnableTrading,LoginSuffix);
        _status=!BindingOk ? "ACCOUNT_NOT_BOUND" : Account.Equity<=0 ? "NO_EQUITY_MONITORING" : "STARTED";
        Print("RIZAN_STARTUP_OK version=1.2.0_F0245; status={0}; storageKeyLength={1}",_status,_storageKey.Length);
        // The portfolio host owns the single timer.
    }
    private void FreshState()
    {
        var now=Server.TimeInUtc;
        _state=new(){ExecutionModel=ExecutionModel,ContractHash=Contract.Hash,Symbol=SymbolName,AccountNumber=Account.Number,EpochUtc=now,
            LastBarUtc=FrozenCore.Floor(now,1).AddMinutes(-1),PeakEquity=Math.Max(0,Account.Equity),
            Eur=new(){CursorUtc=FrozenCore.Floor(now,1).AddMinutes(-1)}};
        // A missing checkpoint on an account with previous owned activity is
        // not a new deployment. Manage protected exposure, do not reset budgets.
        if(Owned.Length>0 || History.Any(t=>t.SymbolName==SymbolName && t.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true))
        { _state.Quarantined=true;_state.QuarantineReason="CHECKPOINT_REQUIRED_FOR_EXISTING_DEPLOYMENT";RecoverExposureForExitOnly(); }
    }
    private void ValidateState()
    {
        if(_state.Schema!=3 || _state.ExecutionModel!=ExecutionModel || _state.PendingChildren<0 || (_state.PendingLabel!="" && (_state.PendingChildren<1 || _state.PendingChildren>EurBatchExecution.MaxChildren || _state.Basket==null || _state.PendingStage!=_state.Basket.QueueStage || _state.PendingChildren>_state.Basket.QueueRemaining || (_state.PendingFirstFill && _state.Basket.Accepted.Sum()!=0))) || _state.ContractHash!=Contract.Hash || _state.Symbol!=SymbolName || _state.AccountNumber!=Account.Number || _state.Revision<0 || _state.Eur==null || !FrozenCore.ValidCheckpointPeak(_state.PeakEquity) || _state.LastBarUtc>Server.TimeInUtc || _state.EpochUtc>Server.TimeInUtc || _state.LastRealExitUtc>Server.TimeInUtc)
            throw new Exception("CHECKPOINT_IDENTITY_OR_CLOCK_MISMATCH");
        if(Batch&&_state.PendingLabel!=""&&(_state.PendingLabel!=Label(_state.Basket!,_state.PendingStage,_state.Basket!.Sequence)+"|"+_state.PendingChildren||(_state.PendingFirstFill&&_state.PendingStage!=0)))throw new Exception("CHECKPOINT_BATCH_INTENT_INVALID");
        if(!new[]{_state.Eur.Fast,_state.Eur.Slow}.All(FrozenCore.Finite) || _state.Eur.CursorUtc>Server.TimeInUtc || _state.Eur.H1==null || _state.Eur.H1.Any(x=>!FrozenCore.Finite(x.Ema) || x.AtUtc>Server.TimeInUtc || x.Bias is not(-1 or 0 or 1)))
            throw new Exception("CHECKPOINT_FEEDBACK_INVALID");
        if(_state.Eur.Virtual!=null && (!new[]{_state.Eur.Virtual.Entry,_state.Eur.Virtual.Distance,_state.Eur.Virtual.LastClose}.All(x=>FrozenCore.Finite(x)&&x>0) || _state.Eur.Virtual.Side is not(1 or -1)))throw new Exception("CHECKPOINT_VIRTUAL_INVALID");
        if(_state.Basket!=null)
        {
            var b=_state.Basket;
            if(b.Side is not(1 or -1) || !new[]{b.Entry,b.Stop,b.Target,b.RiskBudget}.All(x=>FrozenCore.Finite(x)&&x>=0) || b.Accepted==null || b.Accepted.Length!=4 || b.StageRisk==null || b.StageRisk.Length!=4 || b.Accepted.Any(x=>x<0) || b.StageRisk.Any(x=>!FrozenCore.Finite(x)||x<0) || b.QueueStage< -1 || b.QueueStage>=Contract.Stages || _state.PendingStage<0 || _state.PendingStage>=Contract.Stages || b.QueueRemaining<0 || b.NextStage<0 || b.NextStage>Contract.Stages || b.OriginalDistance<=0 || !FrozenCore.Finite(b.OriginalDistance) || !FrozenCore.Finite(b.BestExit) || b.BestExit<=0 || b.Side*(b.Target-b.Stop)<=0 || b.Side*(b.Stop-(b.Entry-b.Side*b.OriginalDistance))< -Symbol.TickSize*1.1 || b.Side*(b.Target-b.Entry)<=0 || b.ExitUtc<=b.AtUtc || b.AtUtc>Server.TimeInUtc || b.InitialWanted<0 ||
                !new[]{b.ReferenceBalance,b.InitialRiskAllocation,b.RemainingStageBudget,b.UsedRisk,b.MaxDepthPrevious}.All(x=>FrozenCore.Finite(x)&&x>=0) || b.ReferenceBalance<=0 ||
                (Contract.Symbol=="XAUUSD" ? b.Scale!=1 : b.Scale!=1 && b.Scale!=.625 && b.Scale!=.1) ||
                b.RiskBudget>b.ReferenceBalance*Contract.RiskFraction*b.Scale+1e-8 || b.InitialRiskAllocation+b.RemainingStageBudget>b.RiskBudget+1e-8 ||
                Math.Abs(b.Target-b.Entry-b.OriginalDistance*b.Side*Contract.TargetR)>Symbol.TickSize*1.1 ||
                (b.BreakEvenArmed && (b.NextStage!=Contract.Stages || b.QueueStage!=-1 || b.QueueRemaining!=0)) ||
                (!b.BreakEvenArmed && Math.Abs(b.Stop-(b.Entry-b.Side*b.OriginalDistance))>Symbol.TickSize*1.1))
                throw new Exception("CHECKPOINT_BASKET_INVALID");
        }
    }
    private static bool ConnectivityQuarantine(string reason) => reason is
        "BRIDGE_MESSAGE_INVALID" or "BRIDGE_TIMESTAMP_OFFSET_REQUIRED" or
        "BRIDGE_LEASE_BUSY" or "BRIDGE_LEASE_EXPIRED";
    private void BridgeOffline(string reason)
    {
        if(_closing)return;
        _closing=true;
        try
        {
            _bridgeReady=false;_connecting=false;_saveInFlight=false;_validHeartbeats=0;
            ++_bridgeGeneration; // Fence callbacks before synchronous Dispose/close.
            var old=_bridge;_bridge=null;
            _status="BRIDGE_DEGRADED";Print("BRIDGE_DEGRADED reason={0}",reason);
            // cTrader WebSocketClient owns its receive loop; Dispose tears it down.
            // Never allocate another socket if teardown fails.
            try { old?.Dispose(); }
            catch { _continuityReady=false;_stopping=true;Print("BRIDGE_CLOSE_FAILED restart_required=True");return; }
            Print("BRIDGE_DISCONNECTED");
            int[] delays={1,2,4,8,15,30};
            var seconds=delays[Math.Min(_backoffAttempt++,delays.Length-1)];
            _nextConnect=Server.TimeInUtc.AddSeconds(seconds).AddMilliseconds(_reconnectJitter.Next(0,251));
            Print("BRIDGE_RECONNECT_SCHEDULED delay_seconds={0}",seconds);
        }
        finally { _closing=false; }
    }
    private void ConnectBridge()
    {
        if(_stopping || _closing || _connecting || _bridge!=null)return;
        _connecting=true;_handshakeDeadline=Server.TimeInUtc.AddSeconds(10);
        var generation=++_bridgeGeneration;
        Print(_backoffAttempt>0 ? "BRIDGE_RECONNECTING" : "BRIDGE_CONNECTING");
        try
        {
            var socket=new WebSocketClient();_bridge=socket;
            socket.TextReceived += e=>BeginInvokeOnMainThread(()=>{if(!_stopping && generation==_bridgeGeneration)ReceiveBridge(e.Text);});
            socket.Disconnected += _=>BeginInvokeOnMainThread(()=>{if(!_stopping && generation==_bridgeGeneration)BridgeOffline("SOCKET_DROP");});
            socket.Connect(new Uri(BridgeUrl));Print("BRIDGE_CONNECTED");
            socket.Send(JsonSerializer.Serialize(new{type="hello",token=BridgeToken,key=_stateKey,contract=Contract.Hash,lease=_lease},Json));
        }
        catch(Exception e){BridgeOffline("CONNECT_FAILED");Print("BRIDGE_CONNECT_FAILED type={0}",e.GetType().Name);}
    }
    private void ServiceBridge(DateTime now)
    {
        if(_connecting && now>=_handshakeDeadline)BridgeOffline("HANDSHAKE_TIMEOUT");
        if(_bridgeReady && ((now-_lastBridgeAck).TotalSeconds>=30 || (_saveInFlight && now>=_saveDeadline)))
            BridgeOffline(_saveInFlight ? "ACK_TIMEOUT" : "HEARTBEAT_TIMEOUT");
        if(!_bridgeReady && !_connecting && now>=_nextConnect)ConnectBridge();
        if(_bridgeReady && now>=_nextPing)
        {
            try
            {
                _bridge!.Send(JsonSerializer.Serialize(new{type="ping",timestamp=DateTimeOffset.UtcNow.ToString("O",System.Globalization.CultureInfo.InvariantCulture)},Json));
                _nextPing=now.AddSeconds(10);
            }
            catch { BridgeOffline("HEARTBEAT_SEND_FAILED"); }
        }
    }
    private void ReceiveBridge(string text)
    {
        try
        {
            using var doc=JsonDocument.Parse(text);var root=doc.RootElement;
            if(root.TryGetProperty("timestamp",out var timestamp))JsonSerializer.Deserialize<DateTime>(timestamp.GetRawText(),Json);
            var type=root.GetProperty("type").GetString();
            if(type=="ready")
            {
                if(!_connecting || _bridgeReady)throw new JsonException("READY_UNEXPECTED");
                _remoteRevision=root.GetProperty("revision").GetInt64();
                if(_remoteRevision<0)throw new JsonException("REVISION_INVALID");
                if(root.TryGetProperty("state",out var value) && value.ValueKind!=JsonValueKind.Null)
                {
                    var previous=_state;
                    try
                    {
                        var recovered=JsonSerializer.Deserialize<Checkpoint>(value.GetRawText(),Json) ?? throw new JsonException("EMPTY_CHECKPOINT");
                        // An active process is authoritative for its newer offline WAL.
                        // A remote writer ahead of it means concurrent ownership: stop entry.
                        if(_continuityReady && recovered.Revision>previous.Revision)
                            throw new InvalidOperationException("REMOTE_STATE_AHEAD_OF_ACTIVE_PROCESS");
                        // Never rewind a local WAL intent or LastSignalUtc after a lost ACK.
                        if(recovered.Revision<previous.Revision)
                        {
                            // Local WAL may be newer after a save/ACK loss. Keep its
                            // intent and watermark; resync it via the normal CAS save.
                            ValidateState();Print("BRIDGE_RESYNC_LOCAL_WAL_PRESERVED");
                        }
                        if(recovered.Revision==previous.Revision && JsonSerializer.Serialize(recovered,Json)!=Serialize())
                            throw new InvalidOperationException("STATE_REVISION_CONFLICT");
                        if(recovered.Revision>=previous.Revision)_state=recovered;
                        ValidateState();
                    }
                    catch { _state=previous;throw; }
                }
                else if(_state.Revision>0) { /* local/manual recovery will be written after lease acquisition */ }
                _bridgeReady=true;_connecting=false;_nextPing=Server.TimeInUtc;_validHeartbeats=0;_healthySince=Server.TimeInUtc;
                _saveInFlight=false;_persistedRevision=_state.Revision;_lastBridgeAck=Server.TimeInUtc;
                Print("BRIDGE_HANDSHAKE_OK");Print("TIMESTAMP_VALID checkpoint=True");
                // A known-unsent intent created here is still safe to send after ACK;
                // a restored/uncertain intent must be matched to broker evidence first.
                if(!(_pendingPreparedHere && !_pendingSubmitted))RecoverAttempt();
                ReconcileExposure();Changed();Persist();
                _continuityReady=!_state.Quarantined && BindingOk && !Stopped && !_stopping && _localRevision>=_state.Revision;
                _status="BRIDGE_READY";
            }
            else if(type=="ack")
            {
                _remoteRevision=root.GetProperty("revision").GetInt64();
                _persistedRevision=root.GetProperty("client_revision").GetInt64();_saveInFlight=false;_lastBridgeAck=Server.TimeInUtc;
                Persist();ProcessQueue(Server.TimeInUtc);
            }
            else if(type=="snapshot")
            {
                if(!_bridgeReady)throw new JsonException("SNAPSHOT_BEFORE_HANDSHAKE");
                var snapshot=JsonSerializer.Deserialize<ExternalSnapshot>(root.GetProperty("data").GetRawText(),Json) ?? throw new JsonException("EMPTY_SNAPSHOT");
                _snapshot=snapshot;Print("TIMESTAMP_VALID snapshot=True");
            }
            else if(type=="pong")
            {
                if(!_bridgeReady)throw new JsonException("PONG_BEFORE_HANDSHAKE");
                _lastBridgeAck=Server.TimeInUtc;++_validHeartbeats;Print("BRIDGE_HEARTBEAT_OK count={0}",_validHeartbeats);
                if(_validHeartbeats>=3 && (Server.TimeInUtc-_healthySince).TotalSeconds>=20)_backoffAttempt=0;
                // Only the historical connectivity reason can recover automatically.
                // Account, execution uncertainty and checkpoint safety faults stay quarantined.
                if(_validHeartbeats>=3 && BindingOk && _state.Quarantined && ConnectivityQuarantine(_state.QuarantineReason))
                {
                    ValidateState();RecoverAttempt();ReconcileExposure();
                    if(ConnectivityQuarantine(_state.QuarantineReason))
                    { _state.Quarantined=false;_state.QuarantineReason="";Changed();Persist();Print("BRIDGE_CONNECTIVITY_RECOVERED"); }
                }
            }
            else if(type=="error")
            {
                var code=root.GetProperty("code").GetString() ?? "MESSAGE_INVALID";BridgeOffline(code);
                if(code=="LEASE_BUSY" || code=="AUTH_FAILED")_continuityReady=false;
                if(code=="AUTH_FAILED")_stopping=true;
                else if(code!="LEASE_BUSY" && code!="LEASE_EXPIRED" && code!="MESSAGE_INVALID" && code!="TIMESTAMP_OFFSET_REQUIRED")Quarantine("BRIDGE_"+code);
            }
            else throw new JsonException("MESSAGE_TYPE_INVALID");
        }
        catch(Exception e)
        {
            BridgeOffline("MESSAGE_INVALID");Print("BRIDGE_MESSAGE_INVALID type={0}",e.GetType().Name);
            if(e is InvalidOperationException)Quarantine("BRIDGE_STATE_SAFETY_FAULT");
        }
    }
    private void Changed(){_state.Revision++;}
    private void Persist()
    {
        if(string.IsNullOrEmpty(_storageKey))return;
        var json=Serialize();
        try
        {
            LocalStorage.SetString(_storageKey,json,LocalStorageScope.Instance);
            LocalStorage.Flush(LocalStorageScope.Instance);
            if(LocalStorage.GetString(_storageKey,LocalStorageScope.Instance)!=json)
                throw new InvalidOperationException("LOCAL_CHECKPOINT_READBACK_MISMATCH");
            _localRevision=_state.Revision;
        }
        catch(Exception e)
        {
            _localRevision=-1;_continuityReady=false;
            _state.Quarantined=true;_state.QuarantineReason="LOCAL_CHECKPOINT_WRITE_FAILED";
            _status="LOCAL_CHECKPOINT_WRITE_FAILED";
            Print("LOCAL_CHECKPOINT_WRITE_FAILED type={0}; entry_blocked=True",e.GetType().Name);
            return;
        }
        if(!UsesBridge){_persistedRevision=_state.Revision;return;}
        if(!_bridgeReady || _saveInFlight || _state.Revision<=_persistedRevision)return;
        try
        {
            _sentRevision=_state.Revision;_saveInFlight=true;_saveDeadline=Server.TimeInUtc.AddSeconds(15);
            _bridge!.Send(JsonSerializer.Serialize(new{type="save",base_revision=_remoteRevision,client_revision=_sentRevision,state=_state},Json));
        }
        catch{BridgeOffline("CHECKPOINT_SEND_FAILED");}
    }
    private bool Durable => _localRevision>=_state.Revision &&
        (!UsesBridge || (_bridgeReady ? _persistedRevision>=_state.Revision && (Server.TimeInUtc-_lastBridgeAck).TotalSeconds<30 : _continuityReady));
    private void Quarantine(string reason){_state.Quarantined=true;_state.QuarantineReason=reason;Changed();Print("QUARANTINED: {0}",reason);Persist();}
    private bool BindingOk => ExpectedAccount==Account.Number.ToString() && (!Account.IsLive || ExpectedAccount.EndsWith(LoginSuffix,StringComparison.Ordinal));
    private List<Candle> ClosedM1(DateTime now)
    {
        var r=new List<Candle>();for(int i=0;i<_m1.Count;i++)
        { var at=DateTime.SpecifyKind(_m1.OpenTimes[i],DateTimeKind.Utc);if(at.AddMinutes(1)>now)break;
            r.Add(new(at,_m1.OpenPrices[i],_m1.HighPrices[i],_m1.LowPrices[i],_m1.ClosePrices[i])); }
        return r;
    }
    public override void OnTick()
    {
        try { ManagePositions(Server.TimeInUtc); }
        catch(Exception e){Quarantine("POSITION_MANAGEMENT_EXCEPTION:"+e.GetType().Name);}
    }
    public override void OnTimer()
    {
        try { Cycle(); }
        catch(Exception e){Quarantine("RUNTIME_EXCEPTION:"+e.GetType().Name);Print(e.Message);}
    }
    private void Cycle()
    {
        var now=Server.TimeInUtc;
        if(UsesBridge)ServiceBridge(now);
        ManagePositions(now);
        if(UsesBridge && !_bridgeReady && !_continuityReady){Telemetry(now);return;}
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
                if(Owned.Length>0 && b.QueueStage<0 && b.NextStage<Contract.Stages && latest.AddMinutes(1)<=b.AtUtc.AddMinutes(Contract.AddMinutes))
                {
                    var at=latest.AddMinutes(1);
                    bool confirmed=at.Minute%5==0 && FrozenCore.XauConfirmation(bars,at,b.Side);
                    double fill=Quote(b.Side);
                    if(confirmed && at!=b.LastConfirmationUtc && b.MaxDepthPrevious>=Contract.Depths[b.NextStage] && b.Side*(b.Entry-fill)>=.05*distance)
                    { b.LastConfirmationUtc=at;QueueStage(b.NextStage,fill); }
                }
                foreach(var bar in bars.Where(x=>x.OpenUtc>_state.LastBarUtc))
                { double extreme=b.Side==1 ? bar.Low : bar.High+(Symbol.Ask-Symbol.Bid);b.MaxDepthPrevious=Math.Max(b.MaxDepthPrevious,b.Side*(b.Entry-extreme)/distance); }
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
        Persist();for(int i=0;i<OrderRate;i++)ProcessQueue(now);Telemetry(now);
    }
    private bool NoForeignExposure() => Host.PortfolioReady && Host.NoForeignExposure();
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
        if(!ExternalOk(s,now))return;
        if(Contract.Hash==F0245Policy.ConfigHash)s=F0245Policy.ExecutionSignal(s);
        if(Symbol.Ask-Symbol.Bid>(Contract.Symbol=="XAUUSD" ? 1.5 : .00022)){_status="SPREAD_ABOVE_LIMIT";return;}
        if(Contract.Symbol=="XAUUSD")
        {
            var day=s.AtUtc.AddHours(7).Date;
            if(_state.XauDay!=day){_state.XauDay=day;_state.XauDaySignals=0;}
            if(_state.XauDaySignals>=6){_status="XAU_DAILY_BASKET_LIMIT";return;}
        }
        var side=s.Side==1 ? TradeType.Buy : TradeType.Sell;double entry=Quote(s.Side);
        // SELL structural anchor is BID-based and is converted to ASK geometry.
        if(Contract.Symbol=="XAUUSD" && s.Side==-1)s=s with{Anchor=s.Anchor+Symbol.Ask-Symbol.Bid};
        double margin=Symbol.GetEstimatedMargin(side,Contract.ChildUnits);
        var b=(Batch ? EurBatchExecution.Start : (Func<FrozenContract,Signal,double,double,double,double,double,double,double,double,Basket?>)FrozenCore.StartBasket)(Contract,s,entry,Account.Balance,Account.Equity,Account.FreeMargin,Account.Margin,margin,
            Contract.Symbol=="EURUSD" ? FrozenCore.EurScale(_state.Eur) : 1,_state.PeakEquity);
        _state.LastSignalUtc=s.AtUtc;Changed();
        if(b==null){_status="NO_INTEGER_CHILD_WITHIN_BUDGET";return;}
        RP.Buffer(b);_state.Basket=b;if(Contract.Symbol=="XAUUSD")_state.XauDaySignals++;
        _status="BASKET_PREPARED";Changed();
    }
    private void QueueStage(int stage,double fill)
    {
        var b=_state.Basket!;if(!GeometryOk(b,fill))return;
        int wanted=FrozenCore.StageWanted(Contract,b,stage,fill,Account.Equity,Account.FreeMargin,
            Symbol.GetEstimatedMargin(b.Side==1 ? TradeType.Buy : TradeType.Sell,Contract.ChildUnits),Account.Margin);
        if(stage>0)wanted=RP.SafeQuantity(wanted);b.QueueStage=stage;b.QueueRemaining=wanted;b.NextStage=stage+1;Changed();
        if(wanted==0)b.QueueStage=-1;
    }
    private string Label(Basket b,int stage,long sequence) => Prefix+"|"+b.AtUtc.Ticks+"|"+stage+"|"+sequence;
    private string Comment(Basket b) => FormattableString.Invariant($"RZ1;{b.AtUtc.Ticks};{b.ExitUtc.Ticks};{b.Side};{b.Stop:R};{b.Target:R}");
    private void ClearPending(){_pendingPreparedHere=false;_pendingSubmitted=false;_state.PendingLabel="";_state.PendingChildren=0;_state.PendingFirstFill=false;}
    private void ProcessQueue(DateTime now){if(Batch)ProcessBatchQueue(now);else ProcessChildQueue(now);}
    private void ProcessBatchQueue(DateTime now)
    {
        var b=_state.Basket;if(b==null||b.QueueStage<0||b.QueueRemaining<=0||_state.Quarantined||!EnableTrading||!BindingOk||!NoForeignExposure())return;
        var second=FrozenCore.Floor(now,1).AddSeconds(now.Second);
        if(_opsSecond!=second){_opsSecond=second;_ops=0;}if(_ops>=1)return;
        if(now>=b.ExitUtc||(b.QueueStage==0&&now>=b.AtUtc.AddMinutes(b.Accepted.Sum()==0?1:RP.C.EurWindow))||(b.QueueStage>0&&now>b.AtUtc.AddMinutes(Contract.AddMinutes))){CancelQueue();return;}
        if(b.QueueStage>0&&Owned.Length==0){CancelQueue();return;}
        double quote=Quote(b.Side),spread=Symbol.Ask-Symbol.Bid;
        if(!GeometryOk(b,quote)||spread>.00022){CancelQueue();_status="BATCH_PRICE_ZONE_OR_GEOMETRY_BLOCK";return;}
        if(!EurBatchExecution.InZone(Contract,b,b.QueueStage,quote)){
         if(RP.C.EurPause&&b.Accepted.Sum()>0&&b.QueueStage==0)return;
         CancelQueue();return;
        }
        bool first=b.Accepted.Sum()==0;
        var side=b.Side==1?TradeType.Buy:TradeType.Sell;
        int cap=Math.Min(b.QueueRemaining,Math.Min(EurBatchExecution.MaxChildren,FrozenCore.FloorCount(Symbol.VolumeInUnitsMax/Contract.ChildUnits)));
        int quantity=EurBatchExecution.Count(Contract,b,b.QueueStage,quote,Account.Equity,Account.FreeMargin,Account.Margin,spread,cap,first,q=>Symbol.GetEstimatedMargin(side,q*Contract.ChildUnits));
        if(_state.PendingLabel=="")quantity=Host.CapQuantity(this,quantity,(first ? FrozenCore.ChildRisk(Contract,b.Side,b.Entry,b.Stop) : FrozenCore.PlannedChildRisk(Contract,b.Side,quote,b.Stop)),Contract.ChildUnits,b.Side,quote,spread);
        // Startup guarantees one virtual child lies exactly on the broker volume grid.
        if(_state.PendingLabel==""&&RP.C.SafetyFraction<1)quantity=RP.SafeQuantity(quantity);
        double volume=quantity*Contract.ChildUnits;
        if(quantity<1||volume<Symbol.VolumeInUnitsMin||Math.Abs(Symbol.NormalizeVolumeInUnits(volume,RoundingMode.Down)-volume)>1e-8){CancelQueue();_status="NO_BATCH_VOLUME_WITHIN_BUDGET";return;}
        if(_state.PendingLabel=="")
        {_pendingPreparedHere=true;_pendingSubmitted=false;b.Sequence++;_state.PendingStage=b.QueueStage;_state.PendingChildren=quantity;_state.PendingFirstFill=first;_state.PendingLabel=Label(b,b.QueueStage,b.Sequence)+"|"+quantity;Changed();Persist();if(!Durable)return;}
        if(!Durable)return;
        quantity=_state.PendingChildren;volume=quantity*Contract.ChildUnits;
        if(Host.CapQuantity(this,quantity,(first ? FrozenCore.ChildRisk(Contract,b.Side,b.Entry,b.Stop) : FrozenCore.PlannedChildRisk(Contract,b.Side,quote,b.Stop)),Contract.ChildUnits,b.Side,quote,spread)<quantity){CancelQueue();_status="PORTFOLIO_BUDGET_CHANGED_BEFORE_SEND";return;}
        // Recheck the full persisted request after any bridge wait; never resize an intent silently.
        if(!EurBatchExecution.PlannedOk(Contract,b,_state.PendingStage,quote,Account.Equity,Account.FreeMargin,Account.Margin,Symbol.GetEstimatedMargin(side,volume),spread,quantity,_state.PendingFirstFill)){CancelQueue();_status="BATCH_BUDGET_CHANGED_BEFORE_SEND";return;}
        _pendingSubmitted=true;
        _ops++;
        double distance=Math.Abs(b.Entry-b.Stop);
        var trade=ExecuteMarketOrder(side,SymbolName,volume,_state.PendingLabel,
            _state.PendingFirstFill?distance/Symbol.PipSize:Math.Abs(quote-b.Stop)/Symbol.PipSize,
            _state.PendingFirstFill?distance*Contract.TargetR/Symbol.PipSize:Math.Abs(b.Target-quote)/Symbol.PipSize,Comment(b));
        if(!trade.IsSuccessful||trade.Position==null){Quarantine("BATCH_ORDER_RESULT_UNCERTAIN_OR_REJECTED:"+trade.Error);return;}
        var p=trade.Position;
        if(_state.PendingFirstFill)EurBatchExecution.AnchorFirstFill(Contract,b,p.EntryPrice);
        var protection=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);
        bool protectionInvalid=Math.Abs(p.VolumeInUnits-volume)>1e-8||p.TradeType!=side||!protection.IsSuccessful||p.StopLoss==null||p.TakeProfit==null||Math.Abs(p.StopLoss.Value-b.Stop)>Symbol.TickSize*1.1||Math.Abs(p.TakeProfit.Value-b.Target)>Symbol.TickSize*1.1;
        bool budgetInvalid=!EurBatchExecution.ActualOk(Contract,b,_state.PendingStage,p.EntryPrice,Account.Equity,Account.Margin,quantity,Math.Abs(p.Commissions));
        if(protectionInvalid||budgetInvalid)
        {
            var closed=ClosePosition(p);
            if(protectionInvalid||!closed.IsSuccessful){Quarantine(closed.IsSuccessful?"BATCH_FILL_OR_PROTECTION_INVALID_CLOSED":"BATCH_INVALID_POSITION_CLOSE_FAILED");return;}
            ClearPending();CancelQueue();_status="BATCH_BUDGET_REJECTED_CLOSED";Changed();Persist();return;
        }
        EurBatchExecution.Accept(Contract,b,_state.PendingStage,p.EntryPrice,quantity,Math.Abs(p.Commissions));ClearPending();
        _status="BROKER_BATCH_ACCEPTED";Print("RIZAN_BATCH children={0}; lots={1}; equity={2}; margin={3}",quantity,Symbol.VolumeInUnitsToQuantity(volume),Account.Equity,Account.Margin);Changed();Persist();
    }
    private void ProcessChildQueue(DateTime now)
    {
        var b=_state.Basket;if(b==null || b.QueueStage<0 || b.QueueRemaining<=0 || _state.Quarantined || !EnableTrading || !BindingOk || !NoForeignExposure())return;
        if(_opsSecond!=new DateTime(now.Ticks-now.Ticks%TimeSpan.TicksPerSecond,DateTimeKind.Utc)){_opsSecond=new DateTime(now.Ticks-now.Ticks%TimeSpan.TicksPerSecond,DateTimeKind.Utc);_ops=0;}
        if(_ops>=OrderRate)return;
        if(now>=b.ExitUtc || (b.QueueStage==0 && now>=b.AtUtc.AddMinutes(b.Accepted.Sum()==0?1:RP.C.EurWindow)) || (b.QueueStage>0 && now>b.AtUtc.AddMinutes(Contract.AddMinutes))) { CancelQueue();return; }
        if(b.QueueStage>0 && Owned.Length==0){CancelQueue();return;}
        double fill=Quote(b.Side),risk=Contract.Symbol=="EURUSD" ? FrozenCore.PlannedChildRisk(Contract,b.Side,fill,b.Stop) : FrozenCore.ChildRisk(Contract,b.Side,fill,b.Stop);
        double margin=Symbol.GetEstimatedMargin(b.Side==1 ? TradeType.Buy : TradeType.Sell,Contract.ChildUnits);
        double reference=Math.Min(b.ReferenceBalance,Account.Equity);
        if(!GeometryOk(b,fill) || Symbol.Ask-Symbol.Bid>(Contract.Symbol=="XAUUSD" ? 1.5 : .00022) || !FrozenCore.Finite(risk) || risk<=0 || b.StageRisk[b.QueueStage]+risk>FrozenCore.StageAllocation(Contract,b,b.QueueStage)+1e-8 || b.UsedRisk+risk>Math.Min(b.RiskBudget,reference*Contract.RiskFraction*b.Scale)+1e-8 || Account.Margin+margin>reference*Contract.MarginFraction*b.Scale+1e-8 || Account.FreeMargin<margin+Contract.CommissionPerSide)
        {CancelQueue();_status="FILL_TIME_BUDGET_OR_GEOMETRY_BLOCK";return;}
        if(Contract.Symbol=="EURUSD" && !FrozenCore.FillBudgetOk(Contract,b,b.QueueStage,fill,Account.Equity,Account.FreeMargin,Account.Margin,margin,Symbol.Ask-Symbol.Bid))
        {CancelQueue();_status="FILL_TIME_BUDGET_OR_GEOMETRY_BLOCK";return;}
        if(_state.PendingLabel=="")
        {_pendingPreparedHere=true;_pendingSubmitted=false;b.Sequence++;_state.PendingStage=b.QueueStage;_state.PendingChildren=1;_state.PendingLabel=Label(b,b.QueueStage,b.Sequence);Changed();Persist();if(!Durable)return;}
        if(!Durable)return;
        _ops++;
        // Bracket is included in the initial broker request, then converted to
        // the common absolute SL/TP and verified against the broker response.
        var trade=ExecuteMarketOrder(b.Side==1 ? TradeType.Buy : TradeType.Sell,SymbolName,Contract.ChildUnits,
            _state.PendingLabel,Math.Abs(fill-b.Stop)/Symbol.PipSize,Math.Abs(b.Target-fill)/Symbol.PipSize,Comment(b));
        if(!trade.IsSuccessful || trade.Position==null)
        {Quarantine("ORDER_RESULT_UNCERTAIN_OR_REJECTED:"+trade.Error);return;}
        var p=trade.Position;
        var protection=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);
        double actualRisk=FrozenCore.ChildRisk(Contract,b.Side,p.EntryPrice,b.Stop);
        bool protectionInvalid=(Batch ? EurBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits)<1 : Math.Abs(p.VolumeInUnits-Contract.ChildUnits)>1e-8) || p.TradeType!=(b.Side==1 ? TradeType.Buy : TradeType.Sell) || !protection.IsSuccessful || p.StopLoss==null || p.TakeProfit==null || Math.Abs(p.StopLoss.Value-b.Stop)>Symbol.TickSize*1.1 || Math.Abs(p.TakeProfit.Value-b.Target)>Symbol.TickSize*1.1;
        bool budgetInvalid=Contract.Symbol=="EURUSD" ? !FrozenCore.ActualFillBudgetOk(Contract,b,_state.PendingStage,p.EntryPrice,Account.Equity,Account.Margin) : actualRisk<=0 || b.StageRisk[_state.PendingStage]+actualRisk>FrozenCore.StageAllocation(Contract,b,_state.PendingStage)+1e-8 || b.UsedRisk+actualRisk>b.RiskBudget+1e-8 || Account.Margin>Math.Min(b.ReferenceBalance,Account.Equity)*Contract.MarginFraction*b.Scale+1e-8;
        if(protectionInvalid || budgetInvalid)
        {
            var closed=ClosePosition(p);
            if(Contract.Symbol!="EURUSD" || protectionInvalid || !closed.IsSuccessful)
            {Quarantine(closed.IsSuccessful ? "FILL_OR_PROTECTION_OUTSIDE_CONTRACT_CLOSED" : "UNPROTECTED_POSITION_CLOSE_FAILED");return;}
            // Confirmed closed child: cancel queue without repeating the signal.
            _state.PendingLabel="";CancelQueue();_status="FILL_BUDGET_REJECTED_CHILD_CLOSED";Changed();Persist();return;
        }
        b.Accepted[_state.PendingStage]++;b.UsedRisk+=actualRisk;b.StageRisk[_state.PendingStage]+=actualRisk;b.QueueRemaining--;_state.PendingLabel="";
        if(b.QueueRemaining==0){b.NextStage=Math.Max(b.NextStage,b.QueueStage+1);b.QueueStage=-1;}
        _status="BROKER_CHILD_ACCEPTED";Changed();Persist();
    }
    private void CancelQueue(){if(_state.Basket!=null){_state.Basket.QueueRemaining=0;_state.Basket.QueueStage=-1;if(!_state.Quarantined)ClearPending();Changed();}}
    private void RecoverAttempt()
    {
        if(_state.PendingLabel==""||_state.Basket==null)return;
        var positions=Owned.Where(x=>x.Label==_state.PendingLabel).ToArray();
        var history=History.Where(x=>x.Label==_state.PendingLabel&&x.SymbolName==SymbolName).ToArray();
        if(positions.Length>1||(positions.Length==0&&history.Length==0)){Quarantine("PREPARED_ATTEMPT_NOT_RECONCILED_NO_RETRY");return;}
        int quantity=_state.PendingChildren;var b=_state.Basket;
        double totalVolume=positions.Sum(x=>x.VolumeInUnits)+history.Sum(x=>x.VolumeInUnits);
        if(EurBatchExecution.ChildrenForVolume(totalVolume,Contract.ChildUnits)!=quantity||history.Select(x=>(long)x.PositionId).Concat(positions.Select(x=>(long)x.Id)).Distinct().Count()!=1||positions.Any(x=>x.TradeType!=(b.Side==1?TradeType.Buy:TradeType.Sell))||history.Any(x=>x.TradeType!=(b.Side==1?TradeType.Buy:TradeType.Sell)))
        {Quarantine("RECOVERED_BATCH_VOLUME_OR_IDENTITY_INVALID");return;}
        double entry=positions.Length>0?positions[0].EntryPrice:history[0].EntryPrice;
        if(history.Any(x=>Math.Abs(x.EntryPrice-entry)>Symbol.TickSize)){Quarantine("RECOVERED_BATCH_ENTRY_INCONSISTENT");return;}
        if(Batch&&_state.PendingFirstFill)EurBatchExecution.AnchorFirstFill(Contract,b,entry);
        if(!FrozenCore.Finite(entry)||entry<=0||b.QueueRemaining<quantity||b.QueueStage!=_state.PendingStage){Quarantine("RECOVERED_FILL_GEOMETRY_INVALID");return;}
        double commission=positions.Sum(x=>Math.Abs(x.Commissions))+history.Sum(x=>Math.Abs(x.Commissions));
        bool budgetOk=Batch?EurBatchExecution.ActualOk(Contract,b,_state.PendingStage,entry,Account.Equity,Account.Margin,quantity,commission):FrozenCore.ActualFillBudgetOk(Contract,b,_state.PendingStage,entry,Account.Equity,Account.Margin);
        foreach(var p in positions){var r=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);if(!r.IsSuccessful||p.StopLoss==null||p.TakeProfit==null||Math.Abs(p.StopLoss.Value-b.Stop)>Symbol.TickSize*1.1||Math.Abs(p.TakeProfit.Value-b.Target)>Symbol.TickSize*1.1){Quarantine("RECOVERED_BATCH_PROTECTION_INVALID");ClosePosition(p);return;}}
        EurBatchExecution.Accept(Contract,b,_state.PendingStage,entry,quantity,commission);ClearPending();Changed();
        if(!budgetOk)Quarantine("RECOVERED_BATCH_BUDGET_EXCEEDED_NO_ADDS");
    }
    private void ReconcileExposure()
    {
        if(Owned.Length==0)return;
        var b=_state.Basket;
        if(b==null){Quarantine("BROKER_EXPOSURE_WITHOUT_CHECKPOINT_BASKET");RecoverExposureForExitOnly();return;}
        if(Batch)
        {
            if(Owned.Any(p=>EurBatchExecution.ExposureStage(Contract,b,Prefix,p.Label,p.VolumeInUnits)<0)||Enumerable.Range(0,Contract.Stages).Any(stage=>Owned.Where(p=>EurBatchExecution.ExposureStage(Contract,b,Prefix,p.Label,p.VolumeInUnits)==stage).Sum(p=>EurBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits))>b.Accepted[stage]))
            {Quarantine("BROKER_BATCH_STAGE_OR_VOLUME_MISMATCH");return;}
        }
        if(Owned.Sum(p=>EurBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits))>b.Accepted.Sum() || Owned.GroupBy(p=>p.Label).Any(g=>g.Count()>1) || Owned.Any(p=>
            !p.Label.StartsWith(Prefix+"|"+b.AtUtc.Ticks+"|",StringComparison.Ordinal) ||
            (Batch ? EurBatchExecution.ChildrenForVolume(p.VolumeInUnits,Contract.ChildUnits)<1 : Math.Abs(p.VolumeInUnits-Contract.ChildUnits)>1e-8) || p.TradeType!=(b.Side==1 ? TradeType.Buy : TradeType.Sell)))
            Quarantine("BROKER_EXPOSURE_CHECKPOINT_MISMATCH");
    }
    private void RecoverExposureForExitOnly()
    {
        var owned=Owned;if(owned.Length==0)return;
        var parts=owned[0].Comment?.Split(';');
        try
        {
            if(parts==null || parts.Length!=6 || parts[0]!="RZ1")return;
            var b=new Basket{AtUtc=new DateTime(long.Parse(parts[1]),DateTimeKind.Utc),ExitUtc=new DateTime(long.Parse(parts[2]),DateTimeKind.Utc),Side=int.Parse(parts[3]),
                Stop=double.Parse(parts[4],System.Globalization.CultureInfo.InvariantCulture),Target=double.Parse(parts[5],System.Globalization.CultureInfo.InvariantCulture),Entry=owned[0].EntryPrice,
                NextStage=Contract.Stages,QueueStage=-1,ReferenceBalance=Math.Max(.01,Account.Balance),Scale=1};
            b.OriginalDistance=Math.Abs(b.Target-b.Stop)/(Contract.TargetR+1);
            b.Entry=b.Stop+b.Side*b.OriginalDistance;b.BestExit=b.Entry;
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
        if(Contract.Hash==F0245Policy.ConfigHash)ManageF0245BreakEven();
        if(now>b.AtUtc.AddMinutes(Contract.AddMinutes))CancelQueue();
        if(Owned.Length==0 && (b.Accepted.Sum()>0 || b.QueueStage<0 || now>=b.ExitUtc))
        {if(_state.PendingLabel!=""){if(_pendingPreparedHere&&!_pendingSubmitted)CancelQueue();else Quarantine("ORPHAN_PENDING_ATTEMPT");}_state.LastRealExitUtc=FrozenCore.Floor(now,1);_state.Basket=null;Changed();}
    }
    private void ManageF0245BreakEven()
    {
        var b=_state.Basket;var owned=Owned;if(b==null||owned.Length==0)return;
        double exit=b.Side==1?Symbol.Bid:Symbol.Ask;
        // An unresolved persisted order intent must be reconciled before modifying its budget/queue state.
        if(_state.PendingLabel=="")
        {
            double units=owned.Sum(p=>p.VolumeInUnits),entry=owned.Sum(p=>p.EntryPrice*p.VolumeInUnits)/units;
            double fees=owned.Sum(p=>Math.Abs(p.Commissions));
            if(F0245Policy.UpdateBreakEven(Contract,b,exit,units,entry,fees))
            {Changed();Persist();_status="F0245_BREAK_EVEN_ARMED";Print("F0245_BE stop={0}; originalDistance={1}",b.Stop,b.OriginalDistance);}
        }
        if(!b.BreakEvenArmed)return;
        foreach(var p in owned)
        {
            // Brackets can be crossed during latency/restart. Never attach a stop beyond the executable quote.
            if(b.Side*(exit-b.Stop)<=0)
            {var close=ClosePosition(p);if(!close.IsSuccessful&&!_state.Quarantined)Quarantine("F0245_BE_CROSSED_CLOSE_FAILED");continue;}
            // Never loosen an already more protective broker stop.
            if(p.StopLoss!=null&&b.Side*(p.StopLoss.Value-b.Stop)>=-Symbol.TickSize*.1&&p.TakeProfit!=null)continue;
            var r=ModifyPosition(p,b.Stop,b.Target,ProtectionType.Absolute);
            if(!r.IsSuccessful||p.StopLoss==null||p.TakeProfit==null||b.Side*(p.StopLoss.Value-b.Stop)<-Symbol.TickSize*1.1)
            {if(!_state.Quarantined)Quarantine("F0245_BE_MODIFY_FAILED");_status="F0245_BE_RETRY_PROTECTED_POSITION";}
        }
    }
    private void Telemetry(DateTime now)
    {
        if(now<_nextTelemetry)return;_nextTelemetry=now.AddMinutes(1);
        Print("RIZAN_TRANSPORT symbol={0}; bridge={1}; continuity={2}; local_revision={3}",SymbolName,_bridgeReady,_continuityReady,_localRevision);
        Print("RIZAN_STATE status={0}; trading={1}; accountBound={2}; positions={3}; quarantined={4}; reason={5}",_status,EnableTrading,BindingOk,Owned.Length,_state.Quarantined,_state.QuarantineReason);
        Print("RIZAN_CHECKPOINT {0}",Serialize());
    }
    public override void OnStop(){_stopping=true;Persist();++_bridgeGeneration;_bridge?.Dispose();_bridge=null;Print("RIZAN stopped. Broker SL/TP remain attached; restart requires checkpoint reconciliation.");}
    internal override bool RecoveryReady => !_state.Quarantined && (_bridgeReady || _continuityReady) && !Stopped && !_stopping;
    internal override string PendingOrderLabel => _state.PendingLabel;
    internal override double PendingRisk {
        get { var b=_state.Basket; return b==null || _state.PendingLabel=="" || Positions.Any(p=>p.SymbolName==SymbolName&&p.Label==_state.PendingLabel) ? 0 : _state.PendingChildren*(_state.PendingFirstFill ? FrozenCore.ChildRisk(Contract,b.Side,b.Entry,b.Stop) : FrozenCore.PlannedChildRisk(Contract,b.Side,Quote(b.Side),b.Stop)); }
    }
    internal override double PendingMargin {
        get { var b=_state.Basket; return b==null || _state.PendingLabel=="" || Positions.Any(p=>p.SymbolName==SymbolName&&p.Label==_state.PendingLabel) ? 0 : Symbol.GetEstimatedMargin(b.Side==1?TradeType.Buy:TradeType.Sell,_state.PendingChildren*Contract.ChildUnits); }
    }

}
