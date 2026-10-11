using cAlgo.API;
using Rizan.Frozen;
namespace cAlgo.Robots;
[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public class RizanEUR : RizanRobot
{
    protected override FrozenContract Contract => FrozenContract.Eur;
    protected override string Prefix => "RZEU3";
    protected override string LoginSuffix => "7903";
}
