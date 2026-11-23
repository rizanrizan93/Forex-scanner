"""Evidence-only liveness. This module has no recovery/execution capabilities."""
from datetime import datetime, timezone

ROLES = ('BOOTSTRAP', 'XAUUSD', 'EURUSD', 'BTCUSD')

def timestamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def recent(value, now, seconds):
    at = timestamp(value)
    return at is not None and -5 <= (now-at).total_seconds() <= seconds


def observe(payload, now):
    """Validated dashboard payload only. Missing native telemetry stays unknown.

    A current lease proves recent accepted traffic, not current broker readiness,
    unique native instance ownership, or permission to restart trading.
    """
    source_fresh = recent(payload.get('observed_at'), now, 30)
    bridge = payload.get('bridge') or {}
    bridge_active = (source_fresh and payload.get('service_active') is True
                     and bridge.get('profile_ok') is True
                     and recent(bridge.get('observed_at'), now, 30))
    roles = {}
    for row in payload['roles']:
        touched = timestamp(row.get('lease_touched_at'))
        expires = timestamp(row.get('lease_expires_at'))
        identity = row.get('identity_ok') is True
        lease_active = bool(source_fresh and identity and row.get('lease_active') is True
                            and recent(row.get('lease_touched_at'), now, 45)
                            and expires and expires > now)
        if not source_fresh:
            status, reason = 'STALE', 'OBSERVATION_STALE'
        elif not identity:
            status, reason = 'UNKNOWN', 'CHECKPOINT_IDENTITY_UNVERIFIED'
        elif expires and expires <= now:
            status, reason = 'STALE', 'LEASE_EXPIRED'
        elif not bridge_active:
            status, reason = 'UNKNOWN', 'BRIDGE_PATH_UNVERIFIED'
        elif lease_active:
            status, reason = 'LEASE_ACTIVE', 'RECENT_ACCEPTED_HEARTBEAT'
        else:
            status, reason = 'UNKNOWN', 'HEARTBEAT_UNVERIFIED'
        roles[row['role']] = dict(status=status, reason=reason,
            bridge_active=bridge_active, lease_active=lease_active,
            bot_connected='RECENT_HEARTBEAT' if lease_active and bridge_active else 'UNVERIFIED',
            last_heartbeat_at=row.get('lease_touched_at'),
            heartbeat_age_seconds=(now-touched).total_seconds() if touched else None,
            # Native lifecycle, account binding, open-order reconciliation and
            # duplicate-instance inventory are absent from this contract.
            execution_ready=None, native_lifecycle='UNKNOWN',
            recovery_allowed=False, recovery_reason='NATIVE_OWNERSHIP_AND_BROKER_RECONCILIATION_REQUIRED')
    return dict(source_fresh=source_fresh, bridge_active=bridge_active, roles=roles,
                attention_required=any(not x['lease_active'] or not bridge_active for x in roles.values()),
                execution_ready=None, automatic_recovery=False)
