"""Explicit backend selection; never silently fall back after a Turso failure."""
import os

def backend_name():
    name=os.getenv('FX_DATABASE_BACKEND','supabase').strip().lower()
    if name not in {'supabase','turso'}:raise ValueError('invalid FX_DATABASE_BACKEND')
    return name

def create_backend_client(url='',secret=''):
    if backend_name()=='turso':
        from .turso_client import TursoClient
        client=TursoClient.from_env()
        ready=client.table('runtime_heartbeats').select('healthy').eq('worker_name','turso_migration_ready_v1').limit(1).execute().data
        if ready != [{'healthy':True}]:raise RuntimeError('Turso migration is not verified; execution remains blocked')
        return client
    from supabase import create_client
    return create_client(url,secret)
