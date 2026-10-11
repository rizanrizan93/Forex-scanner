import asyncio, json, os, secrets, ssl, subprocess, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from server import Store, CONTRACTS, strict_load
from websockets.asyncio.client import connect

class StoreTests(unittest.TestCase):
    def test_both_versions_restart_lease_and_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'state.db'); store=Store(path)
            for prefix,symbol,schema in [('RZXA1','XAUUSD',1),('RZEU4B','EURUSD',2)]:
                key=f'{prefix}:1237903:{symbol}'; lease='a'*32
                self.assertEqual(store.acquire(key,lease),(0,None))
                state=dict(Schema=schema,ContractHash=CONTRACTS[prefix],AccountNumber=1237903,Symbol=symbol,Revision=1,PendingLabel='durable-intent')
                if schema==2: state['ExecutionModel']='EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1'
                self.assertEqual(store.save(key,lease,0,1,state),1)
                with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):store.save(key,lease,0,2,{**state,'Revision':2})
                with self.assertRaisesRegex(ValueError,'STATE_IDENTITY_INVALID'):store.save(key,lease,1,2,{**state,'Schema':3,'Revision':2})
                second=Store(path)
                with self.assertRaisesRegex(ValueError,'LEASE_BUSY'):second.acquire(key,'b'*32)
                self.assertEqual(second.acquire(key,lease),(1,state))
                second.db.execute('UPDATE leases SET expires=0 WHERE key=?',(key,));second.db.commit()
                self.assertEqual(second.acquire(key,'b'*32),(1,state));second.db.close()
            store.db.close()
    def test_strict_json(self):
        with self.assertRaises(ValueError):strict_load('{"x":NaN}')

class WssTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_protocol_reconnect_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp); cert=tmp/'cert.pem';key=tmp/'key.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            env={**os.environ,'RIZAN_BRIDGE_TOKEN':secrets.token_hex(32),'RIZAN_TLS_CERT':str(cert),'RIZAN_TLS_KEY':str(key),'RIZAN_STATE_DB':str(tmp/'state.db')}
            bridge=Path(__file__).resolve().parents[1]/'bridge'
            # Fixture snapshots avoid contacting external providers; transport runs unchanged.
            script="import feeds; feeds.snapshot=lambda: {'ForexFactoryOk':False,'BlsOk':False}; import asyncio,server; asyncio.run(server.main())"
            def start():return subprocess.Popen([sys.executable,'-c',script],cwd=bridge,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            process=start();context=ssl.create_default_context(cafile=str(cert));url='wss://localhost:25345'
            async def open_ws():
                for _ in range(50):
                    try:return await connect(url,ssl=context)
                    except OSError:await asyncio.sleep(.05)
                self.fail('WSS listener unavailable')
            async def message(ws,wanted):
                while True:
                    obj=json.loads(await asyncio.wait_for(ws.recv(),3))
                    if obj['type']==wanted:return obj
            hello=dict(type='hello',token=env['RIZAN_BRIDGE_TOKEN'],key='RZEU4B:1237903:EURUSD',contract=CONTRACTS['RZEU4B'],lease='a'*32)
            state=dict(Schema=2,ExecutionModel='EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1',ContractHash=CONTRACTS['RZEU4B'],AccountNumber=1237903,Symbol='EURUSD',Revision=1,PendingLabel='prepared')
            try:
                ws=await open_ws();await ws.send(json.dumps(hello));self.assertEqual((await message(ws,'ready'))['revision'],0)
                await ws.send(json.dumps(dict(type='save',base_revision=0,client_revision=1,state=state)))
                self.assertEqual((await message(ws,'ack'))['client_revision'],1)
                await ws.send('{"type":"ping"}');await message(ws,'pong')
                duplicate=await open_ws();await duplicate.send(json.dumps(hello));self.assertEqual((await message(duplicate,'error'))['code'],'LEASE_BUSY');await duplicate.close()
                await ws.close();await asyncio.sleep(.05)
                process.terminate();process.wait(timeout=5);process=start()
                ws=await open_ws();await ws.send(json.dumps(hello));self.assertEqual((await message(ws,'ready'))['state'],state);await ws.close()
                other=await open_ws();await other.send(json.dumps({**hello,'lease':'b'*32}));self.assertEqual((await message(other,'error'))['code'],'LEASE_BUSY');await other.close()
                xau=await open_ws();xh={**hello,'key':'RZXA1:2144480:XAUUSD','contract':CONTRACTS['RZXA1']};await xau.send(json.dumps(xh));await message(xau,'ready')
                xs=dict(Schema=1,ContractHash=CONTRACTS['RZXA1'],AccountNumber=2144480,Symbol='XAUUSD',Revision=1)
                await xau.send(json.dumps(dict(type='save',base_revision=0,client_revision=1,state=xs)));await message(xau,'ack');await xau.close()
            finally:
                process.terminate();process.wait(timeout=5)

if __name__=='__main__':unittest.main()
