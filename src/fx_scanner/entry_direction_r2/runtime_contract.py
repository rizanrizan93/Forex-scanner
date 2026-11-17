"""Lightweight source/expiry validation; no scientific dependencies or model load."""
from datetime import UTC,datetime
import math
CONTRACT='RIZAN_ENTRY_DIRECTION_R2_V1'

def stamp(value):
 try:
  t=datetime.fromisoformat(str(value).replace('Z','+00:00'));return t.astimezone(UTC) if t.tzinfo else None
 except (TypeError,ValueError):return None

def validate_snapshot(payload,*,now):
 if not isinstance(payload,dict) or payload.get('contract')!=CONTRACT or payload.get('execution_authority') is not False or payload.get('execution_influence') is not False or payload.get('model_id')!='R2_RULE_670':raise ValueError('R2_CONTRACT_INVALID')
 at=stamp(payload.get('as_of'))
 if not at or not -5<=(now-at).total_seconds()<=90:raise ValueError('R2_SNAPSHOT_STALE')
 p=dict(payload)
 if p.get('status')=='TRIGGER_SELL':
  q=p.get('quote') or {};qt=stamp(q.get('at'));s=p.get('signal') or {};end=stamp(s.get('valid_until'));start=stamp(s.get('signal_at'))
  numeric=all(type(q.get(k)) in [int,float] and math.isfinite(q[k]) for k in ['bid','ask'])
  if not numeric or not 0<q['bid']<=q['ask'] or not qt or not -5<=(now-qt).total_seconds()<=30 or not end or not start or not start<=now<end:
   p.update(status='WAIT_DATA',direction='WAIT',reason='Pemicu sebelumnya sudah kedaluwarsa atau quote belum valid')
 return p
