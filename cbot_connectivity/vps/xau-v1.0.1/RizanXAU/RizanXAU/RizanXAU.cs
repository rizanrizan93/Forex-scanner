using cAlgo.API;
using Rizan.Frozen;
namespace cAlgo.Robots;
[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public class RizanXAU : RizanRobot
{
    protected override FrozenContract Contract => FrozenContract.Xau;
    protected override string Prefix => "RZXA1";
    protected override string LoginSuffix => "4480";
}
