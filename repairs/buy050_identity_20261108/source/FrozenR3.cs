using System.Text.Json;
namespace Rizan.Portfolio;
public static class FrozenR3 {
 public const string ProfileId="RIZAN_BUY050_FROZEN_20261107";
 public const string ConfigSha256="13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6";
#if REPLAY
 public const string XauPrefix="RZXRC1",EurPrefix="RZEF245",BtcPrefix="RZBTC8500283";
 public static string PortfolioStorageKey(long account)=>"RIZAN THREE 7D130 "+account;
 public static string BtcStorageKey(long account)=>"RIZAN BTC 7D130 "+account;
 public static string BtcRemoteKey(long account)=>"RZBTC7D130:"+account+":BTCUSD";
#else
 public const string XauPrefix="TPX_13bfa137",EurPrefix="TPE_13bfa137",BtcPrefix="TPB_13bfa137";
 public static string PortfolioStorageKey(long account)=>NativeStorageKey("PORT",account);
 public static string BtcStorageKey(long account)=>NativeStorageKey("BTC",account);
 public static string BtcRemoteKey(long account)=>"TPBTC:"+ConfigSha256+":"+account+":BTCUSD";
#endif
 public static string NativeStorageKey(string role,long account)=>"R3"+role+" "+System.Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(ConfigSha256+":"+role+":"+account))).Substring(0,32);
 public static ResearchCase Create()=>new(){Id="BUY050",SafetyFraction=0.9,XauRisk=1.65,EurRisk=0.8,BtcRisk=1,XauWindow=180,XauZone=0.8,XauPause=true,XauStep=51.25,XauTarget=4.5,XauCooldown=3,EurWindow=60,EurPause=true,EurInitial=1,EurTarget=10,EurBE=3,EurStop=0.845,EurDepth=1,PlanningCost=1,BtcBuyTarget=12,BtcSellTarget=2,BtcBuyStop=2,BtcSellStop=1.5,BtcBatchOrders=32,BtcBatchSeconds=180,BtcBatchRisk=0.025,BtcBatchMargin=0.1,BtcBatchZone=0.5,BtcBuyHours=128,BtcSellHours=8,XauStop=2.4};
 public static bool Matches()=>JsonSerializer.Serialize(RP.C)==JsonSerializer.Serialize(Create());
}
