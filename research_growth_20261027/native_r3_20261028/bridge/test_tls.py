import json,ssl,subprocess,tempfile,unittest
from pathlib import Path
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from server import Bridge,Store
from test_bridge import TOKEN,ACCOUNT,XAU
class WssTests(unittest.IsolatedAsyncioTestCase):
 async def test_real_tls_handshake_auth_and_heartbeat(self):
  with tempfile.TemporaryDirectory() as folder:
   folder=Path(folder);cert,key=folder/'cert.pem',folder/'key.pem'
   subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
   tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2;tls.load_cert_chain(cert,key)
   store=Store(folder/'db');bridge=Bridge(store,TOKEN,allowed_accounts=[ACCOUNT])
   try:
    async with serve(bridge.handler,'127.0.0.1',0,ssl=tls) as srv:
     port=srv.sockets[0].getsockname()[1];trust=ssl.create_default_context(cafile=str(cert))
     async with connect(f'wss://localhost:{port}/r3/',ssl=trust) as ws:
      await ws.send(json.dumps(dict(type='hello',key=XAU,lease='c'*32,token=TOKEN,contract='44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c')))
      self.assertEqual(json.loads(await ws.recv())['type'],'ready')
      await ws.send('{"type":"ping"}');self.assertEqual(json.loads(await ws.recv())['type'],'pong')
   finally:store.db.close()
