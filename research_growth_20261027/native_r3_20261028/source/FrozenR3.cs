using System.Text.Json;
namespace Rizan.Portfolio;
public static class FrozenR3 {
 public const string ProfileId="R3_I100_W060";
 public const string ConfigSha256="fe015394258bf1407ddb90c7d28f3a4e3a2c821a0f019c3c70d487d161c57cbf";
#if REPLAY
 public const string XauPrefix="RZXRC1",EurPrefix="RZEF245",BtcPrefix="RZBTC8500283";
 public static string PortfolioStorageKey(long account)=>"RIZAN THREE 7D130 "+account;
 public static string BtcStorageKey(long account)=>"RIZAN BTC 7D130 "+account;
 public static string BtcRemoteKey(long account)=>"RZBTC7D130:"+account+":BTCUSD";
#else
 public const string XauPrefix="R3X_fe015394",EurPrefix="R3E_fe015394",BtcPrefix="R3B_fe015394";
 public static string PortfolioStorageKey(long account)=>NativeStorageKey("PORT",account);
 public static string BtcStorageKey(long account)=>NativeStorageKey("BTC",account);
 public static string BtcRemoteKey(long account)=>"R3BTC:"+ConfigSha256+":"+account+":BTCUSD";
#endif
 public static string NativeStorageKey(string role,long account)=>"R3"+role+" "+System.Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(ConfigSha256+":"+role+":"+account))).Substring(0,32);
 public static ResearchCase Create()=>new(){Id="R3_I100_W060",SafetyFraction=0.9,XauRisk=1.5,XauWindow=180,XauZone=0.8,XauPause=true,XauStep=51.25,EurWindow=60,EurPause=true,EurInitial=1,EurBE=3,BtcBatchOrders=32,BtcBatchRisk=0.025,BtcBatchMargin=0.1,BtcBatchSeconds=180};
 public static bool Matches()=>JsonSerializer.Serialize(RP.C)==JsonSerializer.Serialize(Create());
}
