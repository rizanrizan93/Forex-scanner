using System;
using System.Reflection;
using System.Text.Json;
using cAlgo.API;
using Rizan.Frozen;
int assertions=0;
var robot=new TestRobot();robot.SymbolName=TestRobot.C.Symbol;robot.BridgeUrl="wss://fixture.invalid:25345";
robot.BridgeToken="synthetic-only-token-not-a-credential";robot.EnableTrading=false;
var now=robot.Server.TimeInUtc;
var state=new Checkpoint{ContractHash=TestRobot.C.Hash,Symbol=TestRobot.C.Symbol,AccountNumber=robot.Account.Number,EpochUtc=now,LastBarUtc=now.AddMinutes(-1)};
#if !TEST_XAU
state.ExecutionModel=EurBatchExecution.Model;
#endif
Set("_state",state);Set("_storageKey","Synthetic");Set("_stateKey","synthetic-identity");
Run("ConnectBridge");var first=(WebSocketClient)Get("_bridge");
Run("ServiceBridge",now.AddSeconds(11));Check(!(bool)Get("_connecting")&&first.Disposed,"HANDSHAKE_TIMEOUT");
robot.Server.TimeInUtc=now.AddSeconds(16);Run("ConnectBridge");var second=(WebSocketClient)Get("_bridge");
first.EmitDisconnect();Check(object.ReferenceEquals(second,Get("_bridge")),"OLD_CALLBACK_FENCED");
second.EmitText("{\"type\":\"error\",\"code\":\"LEASE_BUSY\"}");Check(!state.Quarantined&&second.Disposed,"LEASE_BUSY_RETRY_NO_QUARANTINE");
robot.Server.TimeInUtc=now.AddSeconds(32);Run("ConnectBridge");var third=(WebSocketClient)Get("_bridge");
third.EmitText("{\"type\":\"ready\",\"revision\":0,\"state\":null}");Check((bool)Get("_bridgeReady")&&(bool)Get("_saveInFlight"),"READY_PERSISTS_STATE");
Set("_lastBridgeAck",robot.Server.TimeInUtc);Set("_saveDeadline",robot.Server.TimeInUtc.AddSeconds(-1));Run("ServiceBridge",robot.Server.TimeInUtc);
Check(!(bool)Get("_bridgeReady")&&third.Disposed&&!state.Quarantined,"ACK_TIMEOUT_DESPITE_FRESH_HEARTBEAT");
robot.Server.TimeInUtc=now.AddSeconds(48);Run("ConnectBridge");var fourth=(WebSocketClient)Get("_bridge");
fourth.EmitText("{\"type\":\"ready\",\"revision\":0,\"state\":null}");
fourth.EmitText(JsonSerializer.Serialize(new{type="ack",revision=1,client_revision=state.Revision}));Check(!(bool)Get("_saveInFlight"),"MATCHING_ACK");
Set("_lastBridgeAck",robot.Server.TimeInUtc.AddSeconds(-31));Run("ServiceBridge",robot.Server.TimeInUtc);
Check(!(bool)Get("_bridgeReady")&&!state.Quarantined,"HEARTBEAT_TIMEOUT_RECONNECT");
robot.Server.TimeInUtc=now.AddSeconds(64);Run("ConnectBridge");var fifth=(WebSocketClient)Get("_bridge");
fifth.EmitText("{\"type\":\"ready\",\"revision\":0,\"state\":null}");
fifth.ThrowSend=true;Set("_nextPing",robot.Server.TimeInUtc);Run("ServiceBridge",robot.Server.TimeInUtc);
Check(!(bool)Get("_bridgeReady")&&!state.Quarantined,"SEND_FAILURE_NO_RUNTIME_QUARANTINE");
var at=robot.Server.TimeInUtc;var signal=new Signal(at,1,.001);
var snapshot=new ExternalSnapshot{ProducedUtc=at,CoverageFromUtc=at.AddHours(-1),CoverageToUtc=at.AddDays(1),ForexFactoryOk=true,BlsOk=true,Dfii10=new(){Delta=-.1,AvailableUtc=at.AddDays(-1)},Dgs10=new(){Delta=.1,AvailableUtc=at.AddDays(-1)}};
Set("_snapshot",snapshot);Check((bool)Run("ExternalOk",signal,at),"HEALTHY_SNAPSHOT");
#if TEST_XAU
snapshot.ForexFactoryOk=false;Check(!(bool)Run("ExternalOk",signal,at),"FF_FAIL_CLOSED");snapshot.ForexFactoryOk=true;
snapshot.BlsOk=false;Check(!(bool)Run("ExternalOk",signal,at),"BLS_FAIL_CLOSED");snapshot.BlsOk=true;
snapshot.ProducedUtc=at.AddSeconds(-181);Check(!(bool)Run("ExternalOk",signal,at),"SNAPSHOT_STALE");snapshot.ProducedUtc=at;
snapshot.Dfii10.AvailableUtc=at.AddDays(-8);Check(!(bool)Run("ExternalOk",signal,at),"MACRO_STALE");snapshot.Dfii10.AvailableUtc=at.AddSeconds(1);Check(!(bool)Run("ExternalOk",signal,at),"MACRO_FUTURE");snapshot.Dfii10.AvailableUtc=at.AddDays(-1);
snapshot.Dfii10.Delta=.1;Check(!(bool)Run("ExternalOk",signal,at),"BUY_DIRECTION_BLOCK");snapshot.Dfii10.Delta=-.1;
foreach(var category in new[]{"NFP","CPI","PPI","JOLTS","ECI","FOMC"})foreach(int minute in new[]{-31,-30,495,496}){snapshot.Events=new(){new(){AtUtc=at.AddMinutes(minute),Category=category}};Check((bool)Run("ExternalOk",signal,at)==(minute==-31||minute==496),"EVENT_WINDOW_BOUNDARY");}
snapshot.Events.Clear();Check((bool)Run("ExternalOk",new Signal(at,-1,.001),at),"SELL_DGS10_ALLOW");snapshot.Dgs10.Delta=-.1;Check(!(bool)Run("ExternalOk",new Signal(at,-1,.001),at),"SELL_DGS10_BLOCK");
#else
snapshot.BlsOk=false;snapshot.ForexFactoryOk=false;snapshot.Dfii10.Delta=double.NaN;Set("_snapshot",null!);Check((bool)Run("ExternalOk",signal,at),"EUR_HAS_NO_MACRO_DEPENDENCY");
#endif
Check(robot.Requests==0,"NO_BROKER_ORDER_IN_TRANSPORT_TEST");
Console.WriteLine(JsonSerializer.Serialize(new{Pass=true,Assertions=assertions,Symbol=TestRobot.C.Symbol,Scope="Patched transport and unchanged macro gate against synthetic API; no native Cloud"}));
object Get(string name)=>typeof(RizanRobot).GetField(name,BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(robot)!;
void Set(string name,object value)=>typeof(RizanRobot).GetField(name,BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(robot,value);
object Run(string name,params object[] args){try{return typeof(RizanRobot).GetMethod(name,BindingFlags.NonPublic|BindingFlags.Instance)!.Invoke(robot,args)!;}catch(TargetInvocationException e){throw e.InnerException!;}}
void Check(bool value,string name){assertions++;if(!value)throw new Exception(name);}
class TestRobot:RizanRobot {
#if TEST_XAU
public static FrozenContract C=>FrozenContract.Xau;protected override string Prefix=>"RZXA1";
#else
public static FrozenContract C=>FrozenContract.Eur;protected override string Prefix=>"RZEU4B";
#endif
protected override FrozenContract Contract=>C;protected override string LoginSuffix=>"synthetic";}
