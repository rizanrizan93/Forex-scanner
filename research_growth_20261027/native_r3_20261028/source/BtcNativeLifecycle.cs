using System;
using System.Linq;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;

internal sealed partial class BtcEngine
{
    sealed partial class State
    {
        public string NativeProfileHash {get;set;}=FrozenR3.ConfigSha256;
        public int NativePendingSequence {get;set;}
        public string NativePendingLabel {get;set;}="";
        public double NativePendingMaxUnits {get;set;}
        public double NativePendingReference {get;set;}
    }
    State? DecodeNativeState(string text)
    {
        if(!replay){using var doc=JsonDocument.Parse(text);if(!doc.RootElement.TryGetProperty(nameof(State.NativeProfileHash),out var hash)||hash.GetString()!=FrozenR3.ConfigSha256)throw new InvalidOperationException("R3_BTC_PROFILE_STATE_MISMATCH");}
        return JsonSerializer.Deserialize<State>(text);
    }
    void ValidateNativeState(State x)
    {
        if(x.NativeProfileHash!=FrozenR3.ConfigSha256||x.BatchSent<0||x.BatchSent>RP.C.BtcBatchOrders||x.BatchRemaining<0||x.BatchRemaining>RP.C.BtcBatchOrders||x.BatchSent+x.BatchRemaining>RP.C.BtcBatchOrders||x.NativePendingSequence<0||x.NativePendingSequence>RP.C.BtcBatchOrders)
            throw new InvalidOperationException("R3_BTC_BATCH_STATE_INVALID");
        if(x.NativePendingSequence>0&&(!x.Sending||!double.IsFinite(x.NativePendingMaxUnits)||x.NativePendingMaxUnits<=0||!double.IsFinite(x.NativePendingReference)||x.NativePendingReference<=0||x.NativePendingLabel!=NativeLabel(x.LastSignal,x.NativePendingSequence)))
            throw new InvalidOperationException("R3_BTC_INTENT_STATE_INVALID");
    }
    static string NativeLabel(DateTime at,int sequence)=>Prefix+"|"+at.Ticks+(sequence==1?"":"|B"+sequence);
    void ClearNativeIntent(){state.NativePendingSequence=0;state.NativePendingLabel="";state.NativePendingMaxUnits=0;state.NativePendingReference=0;}
    bool EnsureNativeIntent(int sequence,ref double units,double reference)
    {
        if(replay)return true;
        if(sequence<1||sequence>RP.C.BtcBatchOrders||link==null||!link.Healthy||link.Fatal||!feed.Fresh(Server.TimeInUtc))return false;
        string label=NativeLabel(state.LastSignal,sequence);
        if(state.NativePendingSequence==0){
            state.NativePendingSequence=sequence;state.NativePendingLabel=label;state.NativePendingMaxUnits=units;state.NativePendingReference=reference;state.Sending=true;Save();return false;
        }
        if(state.NativePendingSequence!=sequence||state.NativePendingLabel!=label){state.Fault=true;Save();throw new InvalidOperationException("R3_BTC_INTENT_SEQUENCE_CONFLICT");}
        if(!link.Persisted(state.Revision))return false;
        units=Math.Min(units,state.NativePendingMaxUnits);
        return units>=Symbol.VolumeInUnitsMin;
    }
    bool NativeResultOwned(Position p)=>p.SymbolName==Instrument&&p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true;
    bool NativeFillIdentityOk(Position p){bool ok=state.NativePendingSequence>0&&p.SymbolName==Instrument&&p.Label==state.NativePendingLabel&&p.TradeType==(state.BatchSide>0?TradeType.Buy:TradeType.Sell)&&p.VolumeInUnits>0&&p.VolumeInUnits<=state.NativePendingMaxUnits+1e-8;if(!ok){state.Fault=true;Print("R3_BTC_FILL_IDENTITY_INVALID entry_blocked=True");}return ok;}
    internal void NativeRuntimeFault(Exception ex){state.Fault=true;state.BatchRemaining=0;prepared=null;Print("R3_BTC_RUNTIME_BLOCK type={0} new_entries_blocked=True",ex.GetType().Name);}
    bool NativeSequence(string label,out int sequence)
    {
        sequence=0;string root=Prefix+"|"+state.LastSignal.Ticks;
        if(label==root){sequence=1;return true;}
        if(!label.StartsWith(root+"|B",StringComparison.Ordinal)||!int.TryParse(label.Substring(root.Length+2),out sequence))return false;
        return sequence>=2&&sequence<=RP.C.BtcBatchOrders;
    }
    void NativeRecoveryFault(string reason,bool closeOwned=false){state.Fault=true;state.BatchRemaining=0;if(closeOwned){state.ExitPending=true;state.ExitReason=reason;}Print("R3_BTC_RECOVERY_BLOCK reason={0} new_entries_blocked=True",reason);}
    void ReconcileNativeBatch()
    {
        ValidateNativeState(state);
        var owned=Owned.ToArray();
        if(owned.Length>RP.C.BtcBatchOrders||owned.Any(p=>p.StopLoss==null||p.TakeProfit==null)||owned.Any()&&state.Expiry==default){NativeRecoveryFault("POSITION_PROTECTION_OR_COUNT",owned.Any(p=>p.StopLoss==null||p.TakeProfit==null));return;}
        var sequences=owned.Select(p=>{int q;return NativeSequence(p.Label,out q)?q:0;}).ToArray();
        if(sequences.Any(q=>q==0)||sequences.Distinct().Count()!=sequences.Length){NativeRecoveryFault("LABEL_SEQUENCE");return;}
        if(state.Sending){
            if(state.NativePendingSequence==0){state.Fault=true;state.Sending=false;state.BatchRemaining=0;return;}
            int pending=state.NativePendingSequence;string label=state.NativePendingLabel;
            var positions=owned.Where(p=>p.Label==label).ToArray();
            var history=History.Where(p=>p.SymbolName==Instrument&&p.Label==label).ToArray();
            var ids=positions.Select(p=>(long)p.Id).Concat(history.Select(p=>(long)p.PositionId)).Distinct().ToArray();
            double volume=positions.Sum(p=>p.VolumeInUnits)+history.Sum(p=>p.VolumeInUnits);
            if(ids.Length!=1||volume<=0||volume>state.NativePendingMaxUnits+1e-8||positions.Any(p=>p.TradeType!=(state.BatchSide>0?TradeType.Buy:TradeType.Sell))||history.Any(p=>p.TradeType!=(state.BatchSide>0?TradeType.Buy:TradeType.Sell))){NativeRecoveryFault("PENDING_RESULT_UNCERTAIN");return;}
            state.BatchSent=Math.Max(state.BatchSent,pending);
            // A crash during an in-flight request must never recreate that request.
            // Manage confirmed positions, but cancel the uncommitted remainder.
            state.BatchRemaining=0;state.Sending=false;ClearNativeIntent();
        }
        if(sequences.Any(q=>q>state.BatchSent)){NativeRecoveryFault("COMMITTED_COUNT_MISMATCH");return;}
        if(state.BatchRemaining>0&&(!state.BatchActive||state.BatchSent<1||state.BatchSent+state.BatchRemaining!=RP.C.BtcBatchOrders)){NativeRecoveryFault("BATCH_REMAINDER_MISMATCH");return;}
        if(!owned.Any()||owned.Length<state.BatchSent||Server.TimeInUtc>=state.BatchDeadline)state.BatchRemaining=0;
    }
}
