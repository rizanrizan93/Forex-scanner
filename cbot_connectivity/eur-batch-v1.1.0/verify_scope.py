"""Prove strategy, execution and contract source remains byte-identical."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
original=ROOT/'cbot_sources/archive/eur-releases/v1.1.0'
fixed=Path(__file__).resolve().parent
manifest=json.loads((fixed/'SOURCE_SHA256.json').read_text())
verified=0
for name,digest in manifest.items():
    verified+=1
    assert hashlib.sha256((original/name).read_bytes()).hexdigest()==digest,name
for name in ('Common/FrozenCore.cs','Common/EurBatchExecution.cs',
             'RizanEURBatch/RizanEURBatch/RizanEURBatch.cs',
             'RizanEURBatch/RizanEURBatch/RizanEURBatch.csproj'):
    assert (original/name).read_bytes()==(fixed/'source'/name).read_bytes(),name
for name in ('PlannerTests.cs','RuntimeTests.cs','ApiStubs.cs'):
    assert (original/'tests'/name).read_bytes()==(fixed/'tests'/name).read_bytes(),name
old=(original/'Common/RizanRobot.cs').read_text()
new=(fixed/'source/Common/RizanRobot.cs').read_text()
# Source blocks (including comments) ending at the next method declaration.
def block(text,name):
    match=re.search(r'^    (?:private|protected)[^\n]*\b'+re.escape(name)+r'\(',text,re.M)
    assert match,name
    end=re.search(r'^    (?:private|protected) ',text[match.end():],re.M)
    return text[match.start():match.end()+end.start()] if end else text[match.start():]
methods=('FreshState','ValidateState','Changed','Quarantine','ClosedM1','OnTimer',
         'NoForeignExposure','Quote','GeometryOk','Label','Comment','ExternalOk','PrepareBasket','QueueStage','ProcessQueue','ProcessBatchQueue','ProcessChildQueue','ClearPending',
         'CancelQueue','RecoverAttempt','ReconcileExposure','RecoverExposureForExitOnly','ManagePositions','Telemetry')
for name in methods:
    assert block(old,name)==block(new,name),name
# Cycle changes only its transport service block.
a=old.index('        if(UsesBridge)\n        {',old.index('    private void Cycle()'))
b=old.index('        ManagePositions(now);',a)
expected=old[:a]+'        if(UsesBridge)ServiceBridge(now);\n'+old[b:]
assert block(expected,'Cycle')==block(new,'Cycle'),'Cycle trading body changed'
# Latest ACK filtering is preserved byte-for-byte, including stale ACK ignore.
a=old.index('            else if(type=="ack")');b=old.index('            else if(type=="snapshot")',a)
x=new.index('            else if(type=="ack")');y=new.index('            else if(type=="snapshot")',x)
assert old[a:b]==new[x:y]
# Checkpoint schema, pending signal and cooldown are identical.
assert old[:old.index('public abstract class RizanRobot')]==new[:new.index('public abstract class RizanRobot')]
# Parameters and execution mode/rate are immutable.
a=old.index('    [Parameter(');b=old.index('    private static readonly JsonSerializerOptions')
assert old[a:b]==new[new.index('    [Parameter('):new.index('    private static readonly JsonSerializerOptions')]
for line in old.splitlines():
    if any(name in line for name in ('private bool Batch =>','private string ExecutionModel =>','private int OrderRate =>')):assert line in new
for line in old.splitlines():
    if 'private bool BindingOk =>' in line:assert line in new
print(json.dumps({'Pass':True,'ManifestEntries':len(manifest),'VerifiedArchivedFiles':verified,'StrategyExecutionMethodsUnchanged':list(methods),
                  'ContractHash':'4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976'}))
