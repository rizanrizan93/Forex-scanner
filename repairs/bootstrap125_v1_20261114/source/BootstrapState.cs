using System;
using System.Collections.Generic;
namespace Rizan.Portfolio;
public sealed class SeedIntent {
 public string Label{get;set;}="";public int Stage{get;set;}=1;public DateTime AtUtc{get;set;}public DateTime DeadlineUtc{get;set;}
 public double Units{get;set;}public double Stop{get;set;}public double Target{get;set;}public double Reference{get;set;}
}
public sealed class BootstrapState {
 public int Schema{get;set;}=1;public string ContractHash{get;set;}=FrozenR3.ConfigSha256;public long AccountNumber{get;set;}public string Symbol{get;set;}="BOOTSTRAP";public long Revision{get;set;}
 public string Phase{get;set;}="SEED";public bool Fault{get;set;}public string Reason{get;set;}="";public bool Halted{get;set;}
 public double Peak{get;set;}=100;public double MaxDD{get;set;}public DateTime LastSignalUtc{get;set;}public DateTime NextEntryUtc{get;set;}public DateTime DayUtc{get;set;}public int DayAttempts{get;set;}
 public string OpenLabel{get;set;}="";public double OpenUnits{get;set;}public DateTime DeadlineUtc{get;set;}public SeedIntent? Intent{get;set;}
 public List<long> Settled{get;set;}=new();public DateTime GraduatedUtc{get;set;}public double GraduationBalance{get;set;}
 public void Validate(long account,DateTime now){
  if(Schema!=1||ContractHash!=FrozenR3.ConfigSha256||AccountNumber!=account||Symbol!="BOOTSTRAP"||Revision<0||Phase is not("SEED" or "GROWTH")||!double.IsFinite(Peak)||Peak<=0||!double.IsFinite(MaxDD)||MaxDD<0||MaxDD>2||DayAttempts<0||DayAttempts>2||Settled==null||Settled.Count>10000||LastSignalUtc>now.AddSeconds(5)||DayUtc>now.Date||GraduatedUtc>now.AddSeconds(5))throw new Exception("BOOTSTRAP_STATE_IDENTITY_OR_CLOCK");
  if(Phase=="GROWTH"&&(GraduatedUtc==default||GraduationBalance<125||Intent!=null||OpenLabel!=""))throw new Exception("BOOTSTRAP_PHASE_INVALID");
  if(OpenLabel!=""&&(!OpenLabel.StartsWith(BootstrapEngine.Prefix+"|",StringComparison.Ordinal)||OpenUnits<=0||DeadlineUtc==default))throw new Exception("BOOTSTRAP_OPEN_INVALID");
  if(Intent is {} i && (Phase!="SEED"||OpenLabel!=""||i.Stage is not(1 or 2)||!i.Label.StartsWith(BootstrapEngine.Prefix+"|",StringComparison.Ordinal)||!double.IsFinite(i.Units)||i.Units<=0||!double.IsFinite(i.Stop)||!double.IsFinite(i.Target)||i.Target<=i.Stop||i.Reference<=0||i.AtUtc>now.AddSeconds(5)||i.DeadlineUtc<=i.AtUtc))throw new Exception("BOOTSTRAP_INTENT_INVALID");
 }
}
