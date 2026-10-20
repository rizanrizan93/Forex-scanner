using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Microsoft.Build.Framework;
using Microsoft.Build.Utilities;

var root=Path.GetFullPath(args[0]);
var assembly=Assembly.LoadFrom(Path.Combine(root,"builder/cTrader.Automate.Sdk.Tasks.dll"));
var extract=assembly.GetTypes().Single(t=>t.Name=="ExtractMetadataTask");
var bundle=assembly.GetTypes().Single(t=>t.Name=="BundleAlgoTask");
if(args.Length>1){foreach(var t in new[]{extract,bundle})foreach(var p in t.GetProperties())Console.WriteLine(t.Name+" "+p.Name+" "+p.PropertyType);return;}
var engine=new BuildLog();
var metadata=Path.Combine(root,"native/RizanXauEurPortfolio.algo.metadata");
var dll=Path.Combine(root,"native/RizanXauEurBtcPortfolio.dll");
var task=(ITask)Activator.CreateInstance(extract)!;task.BuildEngine=engine;
Set(task,"AssemblyPath",dll);
var refs=Directory.GetFiles(Path.Combine(root,"vendor/net6ref/ref/net6.0"),"*.dll").Append(Path.Combine(root,"vendor/automate/lib/net6.0/cAlgo.API.dll")).ToArray();
Set(task,"ReferencePath",refs.Select(p=>(ITaskItem)new TaskItem(p)).ToArray());
Set(task,"AlgoSetFiles",Array.Empty<ITaskItem>());Set(task,"OutputPath",metadata);
if(!task.Execute())throw new Exception("METADATA_FAILED");
var b=(ITask)Activator.CreateInstance(bundle)!;b.BuildEngine=engine;
var file=new TaskItem(dll);file.SetMetadata("RelativePath",Path.GetFileName(dll));
Set(b,"FilesToBundle",new ITaskItem[]{file});Set(b,"MetadataPath",metadata);Set(b,"ProjectDir",Path.Combine(root,"source"));
Set(b,"TargetFramework","net6.0");Set(b,"AlgoLanguage","CSharp");Set(b,"IncludeSource",true);Set(b,"IsExported",true);Set(b,"IncludeSymbols",false);
Set(b,"OutputPath",Path.Combine(root,"native/RizanXauEurBtcPortfolio_FROZEN_7DAY_WEEKEND_V1_3_0.algo"));
if(!b.Execute())throw new Exception("BUNDLE_FAILED");
Console.WriteLine("OFFICIAL_SDK_NATIVE_ALGO_BUILD_PASS");
void Set(object obj,string name,object value)=>obj.GetType().GetProperty(name)!.SetValue(obj,value);
class BuildLog:IBuildEngine
{
 public bool ContinueOnError=>false;public int LineNumberOfTaskNode=>0;public int ColumnNumberOfTaskNode=>0;public string ProjectFileOfTaskNode=>"Continuity";
 public void LogErrorEvent(BuildErrorEventArgs e)=>Console.Error.WriteLine(e.Message);
 public void LogWarningEvent(BuildWarningEventArgs e)=>Console.Error.WriteLine(e.Message);
 public void LogMessageEvent(BuildMessageEventArgs e)=>Console.WriteLine(e.Message);
 public void LogCustomEvent(CustomBuildEventArgs e)=>Console.WriteLine(e.Message);
 public bool BuildProjectFile(string p,string[] t,System.Collections.IDictionary g,System.Collections.IDictionary o)=>throw new NotSupportedException();
}
