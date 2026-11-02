"""Probe only the known SSH and bridge ports; no authentication or writes."""
import concurrent.futures,json,socket,ssl,time
from datetime import datetime,timezone
HOST='rizan-bridge.duckdns.org';IP='202.74.74.172'
def probe(port):
 start=time.monotonic();result={'port':port}
 try:
  with socket.create_connection((IP,port),timeout=8) as raw:
   result.update(tcp_connected=True,tcp_seconds=round(time.monotonic()-start,3));raw.settimeout(6)
   if port==22:
    banner=raw.recv(256);result['ssh_banner_present']=banner.startswith(b'SSH-');result['banner_bytes']=len(banner)
   else:
    with ssl.create_default_context().wrap_socket(raw,server_hostname=HOST) as secure:
     result['tls_valid']=True;result['tls_version']=secure.version()
     secure.sendall(('GET /btc10/ HTTP/1.1\r\nHost: '+HOST+'\r\nConnection: close\r\n\r\n').encode())
     result['http_status_line']=secure.recv(512).split(b'\r\n')[0].decode(errors='replace')[:100]
 except Exception as e:result['error_type']=type(e).__name__
 result['seconds']=round(time.monotonic()-start,3);return result
try:dns=sorted({r[4][0] for r in socket.getaddrinfo(HOST,25345,type=socket.SOCK_STREAM)})
except Exception as e:dns={'error_type':type(e).__name__}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:ports=list(pool.map(probe,[22,25345]))
print('NETWORK_PREFLIGHT='+json.dumps({'observed_utc':datetime.now(timezone.utc).isoformat(),'dns':dns,'ports':ports,'read_only':True}),flush=True)
