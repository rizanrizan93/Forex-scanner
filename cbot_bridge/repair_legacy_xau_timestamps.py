"""Offline repair of checkpoints emitted by the verified XAU v1.1.0 UTC producer.

Default: read-only audit. Apply only while bridge is stopped, with explicit UTC
provenance confirmation. Never shifts a time, revision, label, intent or watermark.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
try:
    from .timestamps import validate_timestamps
except ImportError:
    from timestamps import validate_timestamps

HASH="7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf"
MODEL="XAU_BATCH_STAGE_FIXED_REF_WAL_V1"
LEGACY_MODEL="XAU_LEGACY_CORE_V1"
NAIVE=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?$")

def repair(value):
    count=0
    if isinstance(value,dict):
        for key,item in value.items():
            if key.lower().endswith('utc') or key=='XauDay':
                if isinstance(item,str) and NAIVE.fullmatch(item):
                    datetime.fromisoformat(item) # validate without inferring local timezone
                    value[key]=item+'Z';count+=1
            else:count+=repair(item)
    elif isinstance(value,list):
        for item in value:count+=repair(item)
    return count

def encoded(state):
    return json.dumps(state,sort_keys=True,allow_nan=False,separators=(',',':'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    parser.add_argument('--key',required=True,help='Exact RZXA1:account:XAUUSD key; never an account wildcard')
    parser.add_argument('--execution-model',choices=(MODEL,'XAU_BATCH_SEND_REF_COOLDOWN_V1',LEGACY_MODEL),default=MODEL)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--confirm-legacy-utc-producer',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'RZXA1:\d+:XAUUSD',args.key):raise SystemExit('KEY_INVALID')
    if args.apply and not args.confirm_legacy_utc_producer:raise SystemExit('UTC_PROVENANCE_CONFIRMATION_REQUIRED')
    db=sqlite3.connect(f'file:{args.database.resolve()}?mode=rw' if args.apply else f'file:{args.database.resolve()}?mode=ro',uri=True)
    row=db.execute('SELECT version,state FROM checkpoints WHERE key=?',(args.key,)).fetchone()
    if not row:raise SystemExit('CHECKPOINT_NOT_FOUND')
    state=json.loads(row[1]);old=encoded(state)
    # Canonical v1.0.1 has schema 1 and no ExecutionModel property. Its UTC
    # converter and source are archived with the same core hash. This sentinel
    # selects that provenance without adding/changing the checkpoint model.
    model_ok = (state.get('ExecutionModel') in (None, '') and state.get('Schema') == 1
                if args.execution_model == LEGACY_MODEL
                else state.get('ExecutionModel') == args.execution_model)
    if state.get('ContractHash')!=HASH or not model_ok or str(state.get('AccountNumber'))!=args.key.split(':')[1] or state.get('Symbol')!='XAUUSD':raise SystemExit('SOURCE_IDENTITY_INVALID')
    count=repair(state);validate_timestamps(state);new=encoded(state)
    print(json.dumps({'mode':'apply' if args.apply else 'audit','naive_fields':count,'version_unchanged':row[0],'revision_unchanged':state['Revision']}))
    if args.apply and count:
        backup=args.database.with_name(args.database.name+'.before-utc-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup_db=sqlite3.connect(backup);db.backup(backup_db);backup_db.close();backup.chmod(0o600)
        with db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute('UPDATE checkpoints SET state=? WHERE key=? AND version=? AND state=?',(new,args.key,row[0],row[1])).rowcount
            if changed!=1:raise RuntimeError('CHECKPOINT_CHANGED_DURING_REPAIR')
            # Preserve lost-ACK idempotency for the current state's exact receipt.
            db.execute('UPDATE checkpoint_receipts SET digest=? WHERE key=? AND client_revision=? AND version=? AND digest=?',
                       (hashlib.sha256(new.encode()).hexdigest(),args.key,state['Revision'],row[0],hashlib.sha256(old.encode()).hexdigest()))
        print('OFFLINE_REPAIR_OK BACKUP_CREATED')
    db.close()

if __name__=='__main__':main()
