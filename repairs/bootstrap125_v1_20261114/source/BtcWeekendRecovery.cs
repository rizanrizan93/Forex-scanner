using System;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;

internal sealed partial class BtcEngine
{
    // One narrowly scoped migration for the observed, never-traded BTC checkpoint.
    // Future locks and ordinary weekend protection are never generically cleared.
    static readonly DateTime RepairWeek = new(2026,11,2,0,0,0,DateTimeKind.Utc);
    static readonly DateTime PoisonedLock = new(2026,11,9,0,0,0,DateTimeKind.Utc);
    bool CleanKnownLockRepairState()=>
        state.WeekendLockUntil==PoisonedLock&&state.Revision>0&&
        !state.Fault&&!state.Sending&&!state.ExitPending&&state.ExitReason==""&&
        !state.BatchActive&&state.BatchRemaining==0&&state.BatchSent==0&&
        state.NativePendingSequence==0&&state.NativePendingLabel==""&&
        state.NativePendingMaxUnits==0&&state.NativePendingReference==0&&
        state.LastSignal==default&&state.Expiry==default&&prepared==null;

    bool TryRepairKnownWeekendLock(DateTime now)
    {
        if(FrozenR3.ProfileId!="F005_BTC10_FROZEN_20261102"||replay||!lockRepairRecoveryEligible||!CleanKnownLockRepairState()||
           !Account.Number.ToString().EndsWith("7903",StringComparison.Ordinal)||
           Host.ExpectedAccount!=Account.Number.ToString()||
           BtcWeekendPolicy.Monday(now)!=RepairWeek||
           !BtcWeekendPolicy.CanEnter(now,weekClose,marketOpen,RepairWeek)||
           link==null||!link.Persisted(state.Revision)||!link.FeedReady||!feed.Fresh(now)||
           !Host.PortfolioReady||Positions.Any()||PendingOrders.Any()||
           Host.Engines.Any(e=>e!=this&&(e.PendingRisk>0||e.PendingMargin>0||e.PendingOrderLabel.Length>0))||
           History.Any(p=>p.SymbolName==Instrument&&p.Label?.StartsWith(Prefix+"|",StringComparison.Ordinal)==true))return false;
        // The selected state has already passed identity validation, native recovery,
        // exclusive lease acquisition and a durable ACK. Never edit SQLite directly.
        lockRepairRecoveryEligible=false;
        try{
            string before=JsonSerializer.Serialize(state);
            if(LocalStorage.GetString(key,LocalStorageScope.Instance)!=before)throw new InvalidOperationException("LOCAL_REPAIR_STATE_CHANGED");
            string backupKey=FrozenR3.NativeStorageKey("BTCFIX",Account.Number);
            var prior=LocalStorage.GetString(backupKey,LocalStorageScope.Instance);
            if(!string.IsNullOrEmpty(prior)&&prior!=before)throw new InvalidOperationException("REPAIR_BACKUP_CONFLICT");
            LocalStorage.SetString(backupKey,before,LocalStorageScope.Instance);
            LocalStorage.Flush(LocalStorageScope.Instance);
            if(LocalStorage.GetString(backupKey,LocalStorageScope.Instance)!=before)throw new InvalidOperationException("REPAIR_BACKUP_READBACK");
            long priorRevision=state.Revision;
            state.WeekendLockUntil=RepairWeek;
            Save(); // Monotonic client revision, existing CAS base revision and lease.
            Print("BTC_WEEKEND_LOCK_REPAIRED from={0:o} to={1:o} prior_revision={2} saved_revision={3} backup_sha256={4} awaiting_remote_ack=True",
                  PoisonedLock,RepairWeek,priorRevision,state.Revision,Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(before))).ToLowerInvariant());
        }catch(Exception ex){state.Fault=true;Print("BTC_WEEKEND_LOCK_REPAIR_BLOCK type={0} new_entries_blocked=True",ex.GetType().Name);}
        // Never evaluate/send an order on the repair tick. RecoveryReady remains false
        // until the new revision is ACKed by the unchanged bridge protocol.
        return true;
    }
}

