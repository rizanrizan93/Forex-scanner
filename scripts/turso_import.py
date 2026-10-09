"""Decrypt a reviewed migration envelope inside GitHub; no values are logged."""
import base64, hashlib, json, os, sys, zlib
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fx_scanner.storage.turso_client import TursoClient
from fx_scanner.storage.turso_schema import SCHEMA
from turso_bootstrap import AAD, wrapping_key

ORDER=['fx_symbols','scanner_runs','signals','broker_accounts','broker_account_state','broker_position_state','currency_macro_state','model_performance','broker_order_events','xau_outcome_ledger','xau_prepared_plan_lifecycle','runtime_heartbeats','execution_control']
def main():
    c=TursoClient.from_env();envelope=json.loads(Path('turso/migration.encrypted.json').read_text())
    fingerprint=hashlib.sha256(Path('turso/migration.encrypted.json').read_bytes()).hexdigest()
    done=c.table('runtime_heartbeats').select('details').eq('worker_name','turso_migration_ready_v1').execute().data
    if done:
        if done[0]['details'].get('envelope_sha256')!=fingerprint:raise RuntimeError('different migration cannot replace active state')
        print('TURSO_MIGRATION_ALREADY_VERIFIED');return
    row=c.execute("SELECT sealed_private_key FROM turso_migration_keys WHERE key_id='migration-v1'").data[0]
    sealed=base64.b64decode(row['sealed_private_key']);pem=AESGCM(wrapping_key()).decrypt(sealed[:12],sealed[12:],AAD)
    private=serialization.load_pem_private_key(pem,password=None)
    aes_key=private.decrypt(base64.b64decode(envelope['wrapped_key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=AAD))
    payload=AESGCM(aes_key).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),AAD)
    data=json.loads(zlib.decompress(payload))
    counts={table:len(data.get(table,[])) for table in ORDER}
    control=data['execution_control']
    if len(control)!=1 or control[0]['control_key']!='primary':raise RuntimeError('ambiguous execution control')
    md=control[0].get('metadata',{})
    if not md.get('demo_only') or md.get('live_execution_enabled') or set(md.get('allowed_symbols',[]))!={'XAUUSD','EURUSD'}:raise RuntimeError('invalid demo-only migration scope')
    active={r['symbol'] for r in data['fx_symbols'] if r['active']}
    if active!={'EURUSD','XAUUSD'}:raise RuntimeError('active symbol contract mismatch')
    if not any(r['worker_name']=='ctrader_token_state_v1' and r['details'].get('ciphertext_b64') for r in data['runtime_heartbeats']):raise RuntimeError('encrypted token state missing')
    for table in ORDER:
        if table=='execution_control':continue
        # Schema primary keys are retained. Migration resumes idempotently but
        # cannot run after activation; a verified migration never overwrites state.
        keys=PRIMARY[table]
        rows=data.get(table,[])
        for start in range(0,len(rows),50):
            c.table(table).upsert(rows[start:start+50],on_conflict=keys,returning='minimal').execute()
        actual=c.execute('SELECT count(*) AS n FROM "'+table+'"').data[0]['n']
        if actual!=len(rows):raise RuntimeError('migration count mismatch: '+table)
        print('TURSO_MIGRATED table='+table+' rows='+str(actual))
    # Check the vault decrypts with the existing GitHub client secret before enabling.
    from fx_scanner.execution.ctrader_tokens import CTraderTokenStateStore
    CTraderTokenStateStore._decrypt_tokens(next(r['details'] for r in data['runtime_heartbeats'] if r['worker_name']=='ctrader_token_state_v1'))
    ctl=dict(control[0]);ctl['version']+=1;ctl['updated_at']=datetime.now(timezone.utc).isoformat()
    ctl['metadata']=dict(md,database_backend='turso',migration_source='ForexRizan',migration_verified_at=ctl['updated_at'])
    c.table('execution_control').upsert(ctl,on_conflict='control_key').execute()
    c.table('runtime_heartbeats').upsert({'worker_name':'turso_migration_ready_v1','observed_at':ctl['updated_at'],'healthy':True,'lag_seconds':0.,'details':{'envelope_sha256':fingerprint,'counts':counts,'demo_only':True,'source_archive_preserved':True}},on_conflict='worker_name').execute()
    print('TURSO_MIGRATION_VERIFIED demo_only=True active_symbols=EURUSD,XAUUSD')

PRIMARY={
 'fx_symbols':'symbol','scanner_runs':'id','signals':'id','broker_accounts':'backend,account_id','broker_account_state':'backend,account_id','broker_position_state':'backend,account_id,position_id','currency_macro_state':'currency,observed_at','model_performance':'id','broker_order_events':'id','xau_outcome_ledger':'episode_key','xau_prepared_plan_lifecycle':'plan_key','runtime_heartbeats':'worker_name','execution_control':'control_key'}
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('TURSO_IMPORT_FAILED '+type(e).__name__+': '+str(e));sys.exit(1)
