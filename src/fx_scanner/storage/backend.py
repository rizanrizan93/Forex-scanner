"""Explicit backend selection; never silently fall back after a Turso failure."""
import os

def backend_name():
    name=os.getenv('FX_DATABASE_BACKEND','supabase').strip().lower()
    if name not in {'supabase','turso'}:raise ValueError('invalid FX_DATABASE_BACKEND')
    return name

def create_backend_client(url='',secret=''):
    if backend_name()=='turso':
        from .turso_client import TursoClient
        return TursoClient.from_env()
    from supabase import create_client
    return create_client(url,secret)
