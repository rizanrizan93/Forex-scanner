"""Prove strategy, execution and contract source remains byte-identical."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
original=ROOT/'cbot_sources/archive/xau-batch-v1.1.0'
fixed=Path(__file__).resolve().parent
manifest=json.loads((original/'SHA256.json').read_text())
for name,digest in manifest.items():
    assert hashlib.sha256((original/name).read_bytes()).hexdigest()==digest,name
for name in ('Common/FrozenCore.cs','Common/XauBatchExecution.cs',
             'RizanXAUBatch/RizanXAUBatch/RizanXAUBatch.cs',
             'RizanXAUBatch/RizanXAUBatch/RizanXAUBatch.csproj'):
    assert (original/'source'/name).read_bytes()==(fixed/'source'/name).read_bytes(),name
old=(original/'source/Common/RizanRobot.cs').read_text()
new=(fixed/'source/Common/RizanRobot.cs').read_text()
# Source blocks (including comments) ending at the next method declaration.
def block(text,name):
    match=re.search(r'^    (?:private|protected)[^\n]*\b'+re.escape(name)+r'\(',text,re.M)
    assert match,name
    end=re.search(r'^    (?:private|protected) ',text[match.end():],re.M)
    return text[match.start():match.end()+end.start()] if end else text[match.start():]
methods=('FreshState','ValidateState','Changed','Quarantine','ClosedM1','OnTimer',
         'ExternalOk','PrepareBasket','QueueStage','ProcessQueue','ClearPending',
         'CancelQueue','RecoverAttempt','ReconcileExposure','RecoverExposureForExitOnly','ManagePositions','Telemetry')
for name in methods:
    assert block(old,name)==block(new,name),name
# Cycle changes only its transport service block.
a=old.index('        if(UsesBridge)\n        {',old.index('    private void Cycle()'))
b=old.index('        ManagePositions(now);',a)
expected=old[:a]+'        if(UsesBridge)ServiceBridge(now);\n'+old[b:]
assert block(expected,'Cycle')==block(new,'Cycle'),'Cycle trading body changed'
# Parameters/account binding and frozen converter unchanged.
a=old.index('    [Parameter(');b=old.index('    private const string XauExecutionModel')
assert old[a:b]==new[new.index('    [Parameter('):new.index('    private const string XauExecutionModel')]
for line in old.splitlines():
    if 'private bool BindingOk =>' in line:assert line in new
print(json.dumps({'Pass':True,'OriginalManifestFiles':len(manifest),'StrategyExecutionMethodsUnchanged':list(methods),
                  'ContractHash':'7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf'}))
