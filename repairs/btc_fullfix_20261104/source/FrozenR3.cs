using System.Text.Json;
namespace Rizan.Portfolio;
public static class FrozenR3 {
 public const string ProfileId="F005_BTC10_FROZEN_20261102";
 public const string ConfigSha256="e4ebbc111db1c40a261483181f5d6aad1c71c49dfd8e53fbc77d043a5504e22f";
#if REPLAY
 public const string XauPrefix="RZXRC1",EurPrefix="RZEF245",BtcPrefix="RZBTC8500283";
 public static string PortfolioStorageKey(long account)=>"RIZAN THREE 7D130 "+account;
 public static string BtcStorageKey(long account)=>"RIZAN BTC 7D130 "+account;
 public static string BtcRemoteKey(long account)=>"RZBTC7D130:"+account+":BTCUSD";
#else
 public const string XauPrefix="TPX_e4ebbc11",EurPrefix="TPE_e4ebbc11",BtcPrefix="TPB_e4ebbc11";
 public static string PortfolioStorageKey(long account)=>NativeStorageKey("PORT",account);
 public static string BtcStorageKey(long account)=>NativeStorageKey("BTC",account);
 public static string BtcRemoteKey(long account)=>"TPBTC:"+ConfigSha256+":"+account+":BTCUSD";
#endif
 public static string NativeStorageKey(string role,long account)=>"R3"+role+" "+System.Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(ConfigSha256+":"+role+":"+account))).Substring(0,32);
 public static ResearchCase Create()=>new(){Id="F005_BTC10",SafetyFraction=0.9,XauRisk=1.5,EurRisk=1,BtcRisk=1,XauWindow=180,XauZone=0.8,XauPause=true,XauStep=51.25,XauTarget=5.0,XauCooldown=3,EurWindow=60,EurPause=true,EurInitial=1,EurTarget=10,EurBE=3,EurStop=0.845,EurDepth=1,PlanningCost=1,BtcBuyTarget=12,BtcSellTarget=2,BtcBuyStop=2,BtcSellStop=1.5,BtcBatchOrders=32,BtcBatchSeconds=180,BtcBatchRisk=0.025,BtcBatchMargin=0.1,BtcBatchZone=0.5,BtcBuyHours=128,BtcSellHours=8,XauStop=2.8};
 public static bool Matches()=>JsonSerializer.Serialize(RP.C)==JsonSerializer.Serialize(Create());
}
