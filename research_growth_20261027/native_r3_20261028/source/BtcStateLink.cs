using System;
using System.Text.Json;
using cAlgo.API;
namespace Rizan.Portfolio;
// Research bridge endpoint: data and durable state only. It cannot request trades.
internal sealed class BtcStateLink : IDisposable
{
    readonly RizanPortfolio host;readonly string key;readonly Action<JsonElement> recover;readonly Action<JsonElement> feed;
    readonly string lease=Guid.NewGuid().ToString("N");
    WebSocketClient? socket;int generation;bool connecting,connected,stopped,inFlight;int failures;
    DateTime deadline,nextConnect,nextPing,lastAck;long remote,acked=-1,sent,revision;string current="";
    internal bool Fatal {get;private set;}
    internal bool FeedReady {get;private set;}
    internal bool Healthy=>connected&&!Fatal&&(host.Server.TimeInUtc-lastAck).TotalSeconds<25;
    internal bool Persisted(long r)=>Healthy&&acked>=r&&!inFlight;
    internal BtcStateLink(RizanPortfolio h,Action<JsonElement> recovery,Action<JsonElement> data)
    {host=h;key=FrozenR3.BtcRemoteKey(h.Account.Number);recover=recovery;feed=data;}
    internal static bool ValidUrl(string value)=>Uri.TryCreate(value,UriKind.Absolute,out var u)&&u.Port==25345&&string.IsNullOrEmpty(u.UserInfo)&&string.IsNullOrEmpty(u.Query)&&string.IsNullOrEmpty(u.Fragment)&&(u.Scheme=="wss"||u.Scheme=="ws"&&u.IsLoopback);
    internal void Changed(long r,string state){revision=r;current=state;Flush();}
    internal void Tick()
    {
        var now=host.Server.TimeInUtc;
        if(stopped||Fatal)return;
        if(connecting&&now>=deadline||connected&&((now-lastAck).TotalSeconds>=25||inFlight&&now>=deadline))Offline();
        if(!connecting&&!connected&&now>=nextConnect)Connect();
        if(Healthy&&now>=nextPing){try{socket!.Send("{\"type\":\"ping\"}");nextPing=now.AddSeconds(10);}catch{Offline();}}
        Flush();
    }
    void Connect()
    {
        if(!ValidUrl(host.BtcBridgeUrl)||host.BtcBridgeToken.Length<32){Fatal=true;host.Log("BTC_BRIDGE_CONFIG_INVALID");return;}
        try{connecting=true;deadline=host.Server.TimeInUtc.AddSeconds(10);int g=++generation;socket=new WebSocketClient();
            socket.TextReceived+=e=>host.Dispatch(()=>{if(!stopped&&g==generation)Receive(e.Text);});
            socket.Disconnected+=_=>host.Dispatch(()=>{if(!stopped&&g==generation)Offline();});
            socket.Connect(new Uri(host.BtcBridgeUrl));socket.Send(JsonSerializer.Serialize(new{type="hello",key,lease,contract=BtcSevenDayFeed.Contract,token=host.BtcBridgeToken}));}
        catch{Offline();}
    }
    void Offline(){++generation;connected=false;connecting=false;inFlight=false;acked=-1;FeedReady=false;var old=socket;socket=null;try{old?.Dispose();}catch{}nextConnect=host.Server.TimeInUtc.AddSeconds(Math.Min(30,1<<Math.Min(5,failures++)));host.Log("BTC_BRIDGE_OFFLINE entry_blocked=True");}
    void Flush()
    {
        if(!Healthy||inFlight||current.Length==0||acked>=revision)return;
        try{sent=revision;inFlight=true;deadline=host.Server.TimeInUtc.AddSeconds(5);
            socket!.Send("{\"type\":\"save\",\"base_revision\":"+remote+",\"client_revision\":"+sent+",\"state\":"+current+"}");}
        catch{Offline();}
    }
    internal void Receive(string text)
    {
        try{
            if(text.Length>16000000)throw new Exception("FRAME_SIZE");using var doc=JsonDocument.Parse(text);var root=doc.RootElement;
            switch(root.GetProperty("type").GetString()){
                case "ready":
                    if(!connecting||connected)throw new Exception("READY_UNEXPECTED");
                    remote=root.GetProperty("revision").GetInt64();if(remote<0)throw new Exception("REVISION_INVALID");
                    recover(root.GetProperty("state"));connected=true;connecting=false;acked=-1;inFlight=false;lastAck=host.Server.TimeInUtc;nextPing=lastAck;Flush();break;
                case "ack":
                    if(!connected||!inFlight||root.GetProperty("client_revision").GetInt64()!=sent||root.GetProperty("revision").GetInt64()!=remote+1)throw new Exception("ACK_CONFLICT");
                    remote++;acked=sent;inFlight=false;lastAck=host.Server.TimeInUtc;Flush();break;
                case "pong":if(!connected)throw new Exception("PONG_BEFORE_READY");lastAck=host.Server.TimeInUtc;failures=0;break;
                case "feed":if(!connected)throw new Exception("FEED_BEFORE_READY");try{feed(root);FeedReady=true;}catch{FeedReady=false;host.Log("BTC_FEED_REJECTED entry_blocked=True");}break;
                case "feed_unavailable":FeedReady=false;host.Log("BTC_FEED_UNAVAILABLE entry_blocked=True");break;
                case "error":
                    var code=root.GetProperty("code").GetString();if(code!="LEASE_BUSY"&&code!="LEASE_EXPIRED")Fatal=true;Offline();host.Log("BTC_BRIDGE_REJECTED entry_blocked=True");break;
                default:throw new Exception("MESSAGE_INVALID");}
        }catch{Fatal=true;Offline();host.Log("BTC_BRIDGE_SAFETY_FAULT entry_blocked=True");}
    }
    public void Dispose(){stopped=true;++generation;try{socket?.Dispose();}catch{}socket=null;connected=false;}
}
