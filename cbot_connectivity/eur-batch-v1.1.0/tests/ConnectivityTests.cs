using System;using System.Linq;using System.Reflection;using System.Text.Json;using Rizan.Frozen;using cAlgo.API;
int checks=0;
void Check(bool pass,string label){if(!pass)throw new Exception(label);checks++;}
var options=new JsonSerializerOptions{Converters={new UtcDateTimeConverter()}};
foreach(var text in new[]{"2026-10-12T13:30:03.640Z","2026-10-12T13:30:03.640+00:00","2026-10-12T20:30:03.640+07:00","2026-10-12T08:30:03.640-05:00"})
 Check(JsonSerializer.Deserialize<DateTime>(JsonSerializer.Serialize(text),options)==new DateTime(2026,10,12,13,30,3,640,DateTimeKind.Utc),"UTC_OFFSET");
try{JsonSerializer.Deserialize<DateTime>("\"2026-10-12T13:30:03.640\"",options);throw new Exception("NAIVE_ACCEPTED");}catch(JsonException){checks++;}
var r=new T{SymbolName="EURUSD",BridgeUrl="wss://example.invalid:25345",BridgeToken="synthetic-only",ExpectedAccount="1237903"};
var state=new Checkpoint{ContractHash=FrozenContract.Eur.Hash,ExecutionModel="EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1",AccountNumber=r.Account.Number,Symbol="EURUSD",PeakEquity=100,LastSignalUtc=new DateTime(2019,12,31,0,0,0)};
Set(r,"_state",state);Set(r,"_stateKey","RZEU4B:1237903:EURUSD");Set(r,"_storageKey","test");
for(int cycle=0;cycle<200;cycle++){
 Run(r,"ConnectBridge");var socket=Get<WebSocketClient>(r,"_bridge");int created=WebSocketClient.Created;
 Run(r,"ConnectBridge");Run(r,"ConnectBridge");Check(WebSocketClient.Created==created && WebSocketClient.Active==1,"SINGLE_FLIGHT");
 socket.Emit("{\"type\":\"ready\",\"revision\":0,\"state\":null}");Check(Get<bool>(r,"_bridgeReady"),"HANDSHAKE");
 var save=socket.Sent.Last(x=>x.Contains("\"save\""));using(var doc=JsonDocument.Parse(save)){
  var recovered=JsonSerializer.Deserialize<Checkpoint>(doc.RootElement.GetProperty("state").GetRawText(),options)!;
  Check(recovered.LastSignalUtc==state.LastSignalUtc && recovered.LastSignalUtc.Kind==DateTimeKind.Utc,"WAL_OFFSET_ROUNDTRIP");
 }
 socket.Emit(JsonSerializer.Serialize(new{type="ack",revision=1,client_revision=state.Revision}));
 if(cycle%3==0){
  socket.Emit("{\"type\":\"snapshot\",\"data\":{\"ProducedUtc\":\"2026-10-12T13:30:03.640\"}}");
  Check(!Get<bool>(r,"_bridgeReady") && !state.Quarantined && r.Requests==0,"MALFORMED_FAIL_CLOSED");
 }else if(cycle%3==1)socket.Drop();
 else {r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(31);Run(r,"ServiceBridge",r.Server.TimeInUtc);}
 Check(WebSocketClient.Active==0 && socket.Disposed,"CLEAN_TEARDOWN");
 // Late callbacks must never affect the next generation.
 r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(31);Run(r,"ServiceBridge",r.Server.TimeInUtc);
 var next=Get<WebSocketClient>(r,"_bridge");Check(next!=socket && WebSocketClient.Active==1,"RECONNECT_ONCE");
 socket.Emit("{\"type\":\"error\",\"code\":\"AUTH_FAILED\"}");Check(!Get<bool>(r,"_stopping"),"OLD_CALLBACK_FENCED");
 next.Emit("{\"type\":\"ready\",\"revision\":0,\"state\":null}");
 for(int i=0;i<3;i++){r.Server.TimeInUtc=r.Server.TimeInUtc.AddSeconds(10);next.Emit("{\"type\":\"pong\"}");}
 Check(Get<bool>(r,"_bridgeReady") && !state.Quarantined && Get<int>(r,"_backoffAttempt")==0,"RECOVERY_HEALTHY");
 Check(r.Requests==0 && r.LocalStorage.Values["test"].Contains("LastSignalUtc"),"CHECKPOINT_SURVIVES");
 Run(r,"BridgeOffline","TEST_RESET");
}
// A lost ACK must not rewind the more recent local WAL watermark.
Run(r,"ConnectBridge");var resync=Get<WebSocketClient>(r,"_bridge");
var older=JsonSerializer.Deserialize<Checkpoint>(JsonSerializer.Serialize(state,options),options)!;
older.Revision=state.Revision-1;older.LastSignalUtc=state.LastSignalUtc.AddMinutes(-1);
resync.Emit(JsonSerializer.Serialize(new{type="ready",revision=1,state=older},options));
Check(Get<Checkpoint>(r,"_state")==state && state.LastSignalUtc!=older.LastSignalUtc,"LOCAL_WAL_NO_REWIND");
Run(r,"BridgeOffline","RESYNC_DONE");
Run(r,"ConnectBridge");var ws=Get<WebSocketClient>(r,"_bridge");ws.Emit("{\"type\":\"ready\",\"revision\":0,\"state\":null}");
state.Quarantined=true;state.QuarantineReason="BRIDGE_TIMESTAMP_OFFSET_REQUIRED";
for(int i=0;i<3;i++)ws.Emit("{\"type\":\"pong\"}");Check(!state.Quarantined,"LEGACY_CONNECTIVITY_RECOVERY");
state.Quarantined=true;state.QuarantineReason="BATCH_ORDER_RESULT_UNCERTAIN_OR_REJECTED";
for(int i=0;i<3;i++)ws.Emit("{\"type\":\"pong\"}");Check(state.Quarantined,"SAFETY_QUARANTINE_PRESERVED");
Run(r,"BridgeOffline","FINAL");
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Checks=checks,Cycles=200,MaximumActiveSockets=WebSocketClient.Maximum,FinalActiveSockets=WebSocketClient.Active,BrokerRequests=r.Requests,LiveVerified=false}));
void Set(object target,string n,object value)=>typeof(RizanRobot).GetField(n,BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(target,value);
U Get<U>(object target,string n)=>(U)typeof(RizanRobot).GetField(n,BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(target)!;
void Run(object target,string n,params object[] values){try{typeof(RizanRobot).GetMethod(n,BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(target,values);}catch(TargetInvocationException e){throw e.InnerException!;}}
sealed class T:RizanRobot{protected override FrozenContract Contract=>FrozenContract.Eur;protected override string Prefix=>"RZEU4B";protected override string LoginSuffix=>"7903";}
