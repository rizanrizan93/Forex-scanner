using System.Diagnostics;
using System.Security.Cryptography;
using System.Reflection;
// Resource-only launcher. Financial engine bytes and its arguments stay intact.
string here=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)!;
string engine=Path.GetFullPath(File.ReadAllText(Path.Combine(here,"engine_path.txt")).Trim(),here);
string root=Path.GetFullPath(File.ReadAllText(Path.Combine(here,"slot_root.txt")).Trim(),here);
Directory.CreateDirectory(root);
FileStream? TryLock(string file){try{return new FileStream(file,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);}catch(IOException){return null;}}
long Available(){var line=File.ReadLines("/proc/meminfo").First(x=>x.StartsWith("MemAvailable:"));return long.Parse(line.Split((char[]?)null,StringSplitOptions.RemoveEmptyEntries)[1])*1024;}
FileStream? slot=null;
while(slot==null){for(int i=0;i<2;i++){slot=TryLock(Path.Combine(root,$"slot{i}.lock"));if(slot!=null)break;}if(slot==null)Thread.Sleep(1000);}
using(slot){
 FileStream? init=null;
 while(init==null){init=TryLock(Path.Combine(root,"initialization.lock"));if(init==null)Thread.Sleep(1000);}
 while(Available()<4L*1024*1024*1024)Thread.Sleep(1000);
 var releaseLock=new object();
 void ReleaseInit(){lock(releaseLock){init?.Dispose();init=null;}}
 var start=new ProcessStartInfo(Environment.ProcessPath!){UseShellExecute=false,RedirectStandardOutput=true,RedirectStandardError=true};
 start.ArgumentList.Add(engine);foreach(var arg in args)start.ArgumentList.Add(arg);
 using var child=new Process{StartInfo=start};
 child.OutputDataReceived+=(s,e)=>{if(e.Data==null)return;Console.Out.WriteLine(e.Data);if(e.Data.StartsWith("BTC_BULL_COMPRESSION_CANDIDATES"))ReleaseInit();};
 child.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)Console.Error.WriteLine(e.Data);};
 Console.Error.WriteLine("NATIVE_RESOURCE_GATE engine="+engine+" sha256="+Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(engine))).ToLowerInvariant()+" max_active=2 serialized_input_load=true");
 try{child.Start();child.BeginOutputReadLine();child.BeginErrorReadLine();child.WaitForExit();child.WaitForExit();Environment.ExitCode=child.ExitCode;}
 finally{ReleaseInit();}
}
