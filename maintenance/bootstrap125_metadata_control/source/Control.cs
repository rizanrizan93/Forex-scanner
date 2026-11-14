using cAlgo.API;
namespace cAlgo.Robots;
[Robot(TimeZone=TimeZones.UTC,AccessRights=AccessRights.None)]
public sealed class BootstrapMetadataControl:Robot
{
 [Parameter("Control",DefaultValue=false)]public bool Control{get;set;}
 protected override void OnStart(){}
}
