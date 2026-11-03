"""Patch transport only after restoring the pinned frozen package in CI."""
from pathlib import Path
import hashlib,json

root=Path('candidate')
def replace(path,old,new):
    p=root/path;s=p.read_text()
    if old not in s:raise RuntimeError('PATCH_BASE_MISMATCH:'+path)
    p.write_text(s.replace(old,new,1))

before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root/'source').rglob('*.cs')}
replace('bridge/server.py','        self.feed = None','''        self.feed = None
        self.sent_feed = {}
        self.cached_feed = None
        self.cached_feed_wire = None
        self.ownership_lock = asyncio.Lock()''')
replace('bridge/server.py','''        if wire is not None:
            await ws.send(json.dumps(wire, allow_nan=False, separators=(",", ":")))''','''        if wire is not None:
            if symbol == "BTCUSD" and wire.get("type") == "feed":
                # Completed-hour packets are immutable; each socket receives a
                # verified full seed on connect, then only changed hourly data.
                through = wire["through"]
                if self.sent_feed.get(ws) == through:
                    return
                if self.cached_feed is not wire:
                    self.cached_feed_wire = json.dumps(wire, allow_nan=False, separators=(",", ":"))
                    self.cached_feed = wire
                await ws.send(self.cached_feed_wire)
                self.sent_feed[ws] = through
            else:
                if symbol == "BTCUSD":
                    self.sent_feed.pop(ws, None)
                await ws.send(json.dumps(wire, allow_nan=False, separators=(",", ":")))''')
replace('bridge/server.py','''            if any(peer_key == key for peer_key, _ in self.peers.values()):
                raise ValueError("LEASE_BUSY")''','''            for old_ws, (peer_key, peer_lease) in tuple(self.peers.items()):
                if peer_key != key:
                    continue
                # An authenticated reconnect may replace its own socket. A
                # different process must wait until its durable lease expires.
                row = self.store.db.execute(
                    "SELECT expires_at FROM bridge_leases WHERE key=?", (key,)
                ).fetchone()
                expired = row is not None and row[0] <= self.store.clock()
                if peer_lease != lease and not expired:
                    raise ValueError("LEASE_BUSY")
                await asyncio.wait_for(old_ws.close(code=1000, reason="connection replaced"), 3)
                await asyncio.wait_for(old_ws.wait_closed(), 3)
                # The closed handler may still have finally queued. Removing
                # its exact socket cannot remove the replacement connection.
                self.peers.pop(old_ws, None)
                self.sent_feed.pop(old_ws, None)''')
replace('bridge/server.py','''            self.peers.pop(ws, None)''','''            self.peers.pop(ws, None)
            self.sent_feed.pop(ws, None)''')
# Serialize ownership transitions across the awaits used to close an old socket.
p=root/'bridge/server.py';s=p.read_text();a=s.index('            for old_ws,');b=s.index('            await ws.send(json.dumps({"type": "ready"',a)
s=s[:a]+'            async with self.ownership_lock:\n'+''.join('    '+l+'\n' for l in s[a:b].splitlines())+s[b:];p.write_text(s)
# Above replacement targets the existing finally (old_ws is a different name).
replace('bridge/server.py','''        except Exception:
            with contextlib.suppress(Exception):
                await ws.close(code=1011)
        finally:''','''        except Exception as exc:
            # No client address, token, account ID, lease ID or payload logging.
            print("BRIDGE_DISCONNECT " + json.dumps({
                "utc": utc_text(datetime.now(timezone.utc)),
                "error_type": type(exc).__name__,
                "received_close_code": getattr(getattr(exc, "rcvd", None), "code", None),
                "sent_close_code": getattr(getattr(exc, "sent", None), "code", None)
            }), flush=True)
            with contextlib.suppress(Exception):
                await ws.close(code=1011)
        finally:''')
replace('source/BtcSevenDayFeed.cs','''var v=row.EnumerateArray().ToArray();long at=v[0].GetInt64();double o=v[1].GetDouble(),h=v[2].GetDouble(),l=v[3].GetDouble(),c=v[4].GetDouble();int n=v[5].GetInt32();''','''long at=row[0].GetInt64();double o=row[1].GetDouble(),h=row[2].GetDouble(),l=row[3].GetDouble(),c=row[4].GetDouble();int n=row[5].GetInt32();''')
replace('source/BtcSevenDayFeed.cs','SHA256.HashData(buffer.ToArray())','SHA256.HashData(buffer.GetBuffer().AsSpan(0,checked((int)buffer.Length)))')
replace('source/BtcStateLink.cs','''void Offline(){''','''void Offline(string reason="SOCKET_OR_SEND_FAILURE"){''')
replace('source/BtcStateLink.cs','''host.Log("BTC_BRIDGE_OFFLINE entry_blocked=True");''','''host.Log("BTC_BRIDGE_OFFLINE entry_blocked=True reason="+reason);''')
replace('source/BtcStateLink.cs','''if(connecting&&now>=deadline||connected&&((now-lastAck).TotalSeconds>=25||inFlight&&now>=deadline))Offline();''','''if(connecting&&now>=deadline)Offline("HANDSHAKE_TIMEOUT");
        else if(connected&&inFlight&&now>=deadline)Offline("ACK_TIMEOUT");
        else if(connected&&(now-lastAck).TotalSeconds>=25)Offline("HEARTBEAT_TIMEOUT");''')
replace('source/BtcStateLink.cs','''socket.Disconnected+=_=>host.Dispatch(()=>{if(!stopped&&g==generation)Offline();});''','''socket.Disconnected+=_=>host.Dispatch(()=>{if(!stopped&&g==generation)Offline("SOCKET_DROP");});''')
replace('source/BtcStateLink.cs','''Fatal=true;Offline();host.Log("BTC_BRIDGE_REJECTED entry_blocked=True");''','''Fatal=true;Offline(code??"MESSAGE_INVALID");host.Log("BTC_BRIDGE_REJECTED entry_blocked=True code="+code);''')
changed={k for k,v in before.items() if hashlib.sha256((root/k).read_bytes()).hexdigest()!=v}
assert changed=={'source/BtcStateLink.cs','source/BtcSevenDayFeed.cs'},changed
(root/'TRANSPORT_SOURCE_AUDIT.json').write_text(json.dumps({'strategy_sources_unchanged':True,'changed_source_files':sorted(changed),'original_hashes':before},indent=2))
print('TRANSPORT_ONLY_PATCH_OK strategy_sources_unchanged=True')
# The protocol no longer repeats a full feed after every successful pong.
replace('bridge/test_bridge.py', '''self.assertEqual(json.loads(await ws.recv())['type'],'pong');self.assertEqual(json.loads(await ws.recv())['type'],'feed');await ws.close()''', '''self.assertEqual(json.loads(await ws.recv())['type'],'pong');await ws.close()''')
