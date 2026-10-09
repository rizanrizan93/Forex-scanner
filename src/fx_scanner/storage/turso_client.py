"""Backend-only libSQL HTTP adapter for the scanner's table-query contract.

All writes use bound parameters. Conditional UPDATE RETURNING remains one SQL
statement, so control versions, signal claims and durable leases are atomic.
Network writes are never retried here: uncertain outcomes must be reconciled.
"""
from __future__ import annotations
import json
import math
import os
import re
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from .turso_schema import SCHEMA

class TursoError(RuntimeError):
    pass

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('invalid SQL identifier')
    return '"'+value+'"'

def scalar(value):
    if value is None: return {'type':'null'}
    if isinstance(value, bool): return {'type':'integer','value':str(int(value))}
    if isinstance(value, int): return {'type':'integer','value':str(value)}
    if isinstance(value, float):
        if not math.isfinite(value): raise ValueError('nonfinite SQL parameter')
        return {'type':'float','value':value}
    if isinstance(value, (dict,list)): value=json.dumps(value, separators=(',',':'),allow_nan=False)
    if isinstance(value, datetime): value=value.isoformat()
    return {'type':'text','value':str(value)}

def decode(cell):
    t=cell['type']
    if t=='null':return None
    if t=='integer':return int(cell['value'])
    if t=='float':return float(cell['value'])
    if t=='text':return cell['value']
    raise TursoError('unsupported Turso response type')

@dataclass
class Result:
    data: list
    count: int | None = None

class TursoClient:
    def __init__(self,url,token,*,transport=None):
        p=urlsplit(url.strip())
        if p.scheme not in {'libsql','https'} or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in {'','/'}:
            raise ValueError('TURSO_DATABASE_URL must be a libsql/https database origin')
        if not token.strip():raise ValueError('TURSO_AUTH_TOKEN is required')
        self.endpoint='https://'+p.netloc+'/v2/pipeline'
        self.http=transport or httpx.Client(timeout=30)
        self._usage_lock=Lock()
        self._usage=dict.fromkeys(('requests','statements','rows_read','rows_written','unmetered_statements'),0)
        self.headers={'Authorization':'Bearer '+token.strip(),'Content-Type':'application/json'}
    @classmethod
    def from_env(cls):return cls(os.getenv('TURSO_DATABASE_URL',''),os.getenv('TURSO_AUTH_TOKEN',''))
    def table(self,name):
        if name not in SCHEMA:raise ValueError('unknown scanner table')
        return Query(self,name)
    def usage_snapshot(self):
        with self._usage_lock:return dict(self._usage)
    def execute(self,sql,args=()):
        return self.batch([(sql,args)])[0]
    def batch(self,statements,*,transaction=False,track_usage=True):
        steps=[{'stmt':{'sql':sql,'args':[scalar(v) for v in args],'want_rows':True}} for sql,args in statements]
        if transaction:
            steps.insert(0,{'stmt':{'sql':'BEGIN IMMEDIATE'}})
            for i in range(1,len(steps)):
                steps[i]['condition']={'type':'ok','step':i-1}
            steps.append({'condition':{'type':'ok','step':len(steps)-1},'stmt':{'sql':'COMMIT'}})
        steps.insert(0,{'stmt':{'sql':'PRAGMA foreign_keys=ON'}})
        for step in steps[1:]:
            if 'condition' in step:step['condition']['step']+=1
        payload={'requests':[{'type':'batch','batch':{'steps':steps}},{'type':'close'}]}
        try:r=self.http.post(self.endpoint,headers=self.headers,json=payload)
        except httpx.HTTPError as exc:raise TursoError('Turso network outcome unknown') from exc
        if r.status_code!=200:raise TursoError(f'Turso HTTP {r.status_code}')
        body=r.json()
        result=body['results'][0]
        if result['type']!='ok':raise TursoError('Turso pipeline rejected')
        b=result['response']['result']
        items=b['step_results'][2:-1] if transaction else b['step_results'][1:]
        if track_usage:
            with self._usage_lock:
                self._usage['requests']+=1
                self._usage['statements']+=len(items)
                for item in items:
                    if item and all(isinstance(item.get(f),int) for f in ('rows_read','rows_written')):
                        for f in ('rows_read','rows_written'):self._usage[f]+=max(0,item[f])
                    else:self._usage['unmetered_statements']+=1
            from .turso_usage import record
            record(self, items)
        for e in b['step_errors']:
            if e is not None:raise TursoError('Turso SQL rejected: '+str(e.get('code','UNKNOWN')))
        items=b['step_results'][2:-1] if transaction else b['step_results'][1:]
        out=[]
        for item in items:
            if item is None:raise TursoError('Turso statement skipped')
            names=[c['name'] for c in item['cols']]
            out.append(Result([dict(zip(names,map(decode,row))) for row in item['rows']],item['affected_row_count']))
        return out

class Query:
    def __init__(self,client,table):
        self.client=client;self.name=table;self.meta=SCHEMA[table];self.operation='select';self.fields='*';self.pred=[];self.args=[];self.sort=[];self.maximum=None;self.payload=None;self.conflict=None;self.returning='representation';self.want_count=False
    def expression(self,field):
        parts=re.split(r'->>?',field)
        if parts[0] not in self.meta['columns']:raise ValueError('unknown scanner column')
        base=identifier(parts[0])
        if len(parts)>1:
            if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',x) for x in parts[1:]):raise ValueError('invalid JSON path')
            return "json_extract("+base+", '$."+'.'.join(parts[1:])+"')"
        return base
    def select(self,fields='*',*,count=None,head=False):
        if head:raise ValueError('head queries unsupported')
        self.fields=fields;self.want_count=count is not None;return self
    def where(self,field,op,value):
        self.pred.append(self.expression(field)+' '+op+' ?');self.args.append(value);return self
    def eq(self,f,v):return self.where(f,'=',v)
    def neq(self,f,v):return self.where(f,'<>',v)
    def gt(self,f,v):return self.where(f,'>',v)
    def gte(self,f,v):return self.where(f,'>=',v)
    def lt(self,f,v):return self.where(f,'<',v)
    def lte(self,f,v):return self.where(f,'<=',v)
    def in_(self,f,values):
        values=list(values);self.pred.append(self.expression(f)+' IN ('+','.join('?' for _ in values)+')' if values else '0');self.args.extend(values);return self
    def is_(self,f,v):
        if v not in {None,'null'}:raise ValueError('unsupported IS predicate')
        self.pred.append(self.expression(f)+' IS NULL');return self
    def order(self,f,desc=False,**kwargs):self.sort.append(self.expression(f)+(' DESC' if desc else ' ASC'));return self
    def limit(self,n):
        if not isinstance(n,int) or not 0<=n<=100000:raise ValueError('invalid query limit')
        self.maximum=n;return self
    def insert(self,payload,*,returning='representation'):
        self.operation='insert';self.payload=payload;self.returning=returning;return self
    def upsert(self,payload,*,on_conflict=None,returning='representation',**kwargs):
        if kwargs:raise ValueError('unsupported upsert options')
        self.insert(payload,returning=returning);self.operation='upsert';self.conflict=on_conflict;return self
    def update(self,payload,*,returning='representation'):self.operation='update';self.payload=payload;self.returning=returning;return self
    def delete(self,*,returning='representation'):self.operation='delete';self.returning=returning;return self
    def projection(self):
        if self.fields=='*':return '*'
        out=[]
        for f in self.fields.split(','):
            alias,field=f.split(':',1) if ':' in f else (f,f)
            out.append(self.expression(field)+' AS '+identifier(alias))
        return ','.join(out)
    def parse_rows(self,rows):
        out=[]
        for row in rows:
            r=dict(row)
            for field in (self.meta['json'] if self.fields=='*' else []):
                if r.get(field) is not None:r[field]=json.loads(r[field])
            if self.fields!='*':
                for f in self.fields.split(','):
                    alias,field=f.split(':',1) if ':' in f else (f,f)
                    if field.split('->')[0] in self.meta['json'] and '->>' not in field and isinstance(r.get(alias),str):
                        try:r[alias]=json.loads(r[alias])
                        except json.JSONDecodeError:pass
            for f in self.meta['bool']:
                if f in r and r[f] is not None:r[f]=bool(r[f])
            out.append(r)
        return out
    def build(self):
        table=identifier(self.name);where=' WHERE '+' AND '.join(self.pred) if self.pred else '';ret=' RETURNING *' if self.returning!='minimal' else ''
        if self.operation=='select':
            sql='SELECT '+self.projection()+' FROM '+table+where
            if self.sort:sql+=' ORDER BY '+','.join(self.sort)
            if self.maximum is not None:sql+=' LIMIT '+str(self.maximum)
            return [(sql,self.args)]
        if self.operation in {'update','delete'}:
            if not self.pred:raise ValueError('unfiltered mutation forbidden')
            if self.operation=='delete':return [('DELETE FROM '+table+where+ret,self.args)]
            vals=dict(self.payload)
            cols=list(vals);sql='UPDATE '+table+' SET '+','.join(self.expression(c)+'=?' for c in cols)+where+ret
            return [(sql,[vals[c] for c in cols]+self.args)]
        rows=self.payload if isinstance(self.payload,list) else [self.payload];statements=[]
        for item in rows:
            row=dict(item)
            for f in self.meta['uuid']:
                if f not in row:row[f]=str(uuid4())
            cols=list(row)
            if not cols:raise ValueError('empty insert forbidden')
            for c in cols:self.expression(c)
            sql='INSERT INTO '+table+' ('+','.join(identifier(c) for c in cols)+') VALUES ('+','.join('?' for c in cols)+')'
            if self.operation=='upsert':
                conflicts=self.conflict.split(',') if self.conflict else []
                for c in conflicts:self.expression(c)
                if not conflicts:raise ValueError('explicit conflict key required')
                update=[c for c in cols if c not in conflicts and c not in self.meta['uuid']]
                sql+=' ON CONFLICT ('+','.join(identifier(c) for c in conflicts)+') DO '
                sql+='UPDATE SET '+','.join(identifier(c)+'=excluded.'+identifier(c) for c in update) if update else 'NOTHING'
            statements.append((sql+ret,[row[c] for c in cols]))
        return statements
    def execute(self):
        statements=self.build()
        if not statements:return Result([])
        results=self.client.batch(statements,transaction=len(statements)>1)
        data=self.parse_rows([row for r in results for row in r.data])
        return Result(data, len(data) if self.want_count else None)
