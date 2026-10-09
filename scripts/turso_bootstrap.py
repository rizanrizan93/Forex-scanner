"""Initialize Turso without enabling execution; publish only an RSA public key."""
import base64, hashlib, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fx_scanner.storage.turso_client import TursoClient

AAD=b'forex-rizan-migration-v1'
def wrapping_key():
    secret=os.environ['CTRADER_CLIENT_SECRET']
    if not secret:raise RuntimeError('missing migration wrapping secret')
    return hashlib.sha256(AAD+secret.encode()).digest()
def main():
    c=TursoClient.from_env()
    if c.execute('SELECT 1 AS connected').data!=[{'connected':1}]:raise RuntimeError('connection probe failed')
    print('TURSO_CONNECTION_OK credentials_valid=True')
    schema=Path('turso/schema.sql').read_text()
    statements=[(s.strip(),()) for s in schema.split(';') if s.strip()]
    c.batch(statements,transaction=True)
    # Fail-closed fresh database: migration is responsible for restoring control.
    c.execute("INSERT INTO execution_control(control_key) VALUES('primary') ON CONFLICT DO NOTHING")
    c.execute('CREATE TABLE IF NOT EXISTS turso_migration_keys (key_id TEXT PRIMARY KEY, sealed_private_key TEXT NOT NULL, public_key TEXT NOT NULL)')
    row=c.execute("SELECT public_key FROM turso_migration_keys WHERE key_id='migration-v1'").data
    if not row:
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        nonce=os.urandom(12)
        sealed=base64.b64encode(nonce+AESGCM(wrapping_key()).encrypt(nonce,private,AAD)).decode()
        c.execute('INSERT INTO turso_migration_keys VALUES (?,?,?)',('migration-v1',sealed,public))
    else:public=row[0]['public_key']
    Path('turso-migration-public.pem').write_text(public)
    print('TURSO_SCHEMA_OK migration_public_key='+base64.b64encode(public.encode()).decode())
    print('EXECUTION_UNCHANGED migration_pending=True')
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('TURSO_BOOTSTRAP_FAILED '+type(e).__name__+': '+str(e));sys.exit(1)
