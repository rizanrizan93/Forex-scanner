using cAlgo.API;
using Rizan.Frozen;
namespace cAlgo.Robots;
[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public class RizanEURBatch : RizanRobot
{
    protected override FrozenContract Contract => FrozenContract.Eur;
    protected override string Prefix => "RZEU4B";
    protected override string LoginSuffix => "7903";
}
