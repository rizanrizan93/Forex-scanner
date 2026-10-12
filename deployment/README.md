# Bridge-only SSH deployment

Workflow: **Deploy cBot bridge via SSH**. The VPS target is `Rizanrizan@202.74.74.172:22`, service `rizan-cbot-bridge.service`, repository `/home/Rizanrizan/Forex-scanner`.

## One-time setup

Create these repository Actions secrets at:
https://github.com/rizanrizan93/Forex-scanner/settings/secrets/actions

- `VPS_SSH_KEY`: the complete private key from the user's existing `rizan-key.pem`. Do not add this file or its contents to Git, an issue, a log, or a workflow YAML.
- `VPS_KNOWN_HOSTS`: the SSH host public-key entry obtained through the already authenticated VPS console/ConnectBot session. On that VPS run:

```bash
awk '{print "202.74.74.172 "$1" "$2}' /etc/ssh/ssh_host_ed25519_key.pub
```

Copy its single output line into `VPS_KNOWN_HOSTS`. This is the VPS host public key, not the user's private key. The workflow uses StrictHostKeyChecking=yes and does not trust an unauthenticated ssh-keyscan from the runner.

The connected GitHub API tools in this session cannot create Actions secrets or dispatch workflows, so the one-time secret setup must be completed through GitHub settings. There is no embedded SSH key in this repository.

## Run

Pushes to main affecting `deployment/`, `cbot_bridge/`, or this workflow run validation and then deploy. Manual runs support `audit` (default; no service or checkpoint modification) and `deploy`. Only main in this repository, triggered by the owner, can execute the workflow. Credentials are not used on pull requests. Concurrent deployments are serialized.

After adding missing secrets, rerun the failed deployment job, or choose Actions → Deploy cBot bridge via SSH → Run workflow → main → deploy. A prior missing-secret failure performs no SSH deployment.

## What happens on the VPS

1. Verify the existing working directory, Python interpreter, service ExecStart, private EnvironmentFile, existing token and checkpoint database. Do not change account, token, broker credentials, strategy or scanner execution configuration.
2. Build a private candidate copy of current VPS bridge source. Apply the audited connectivity patch without fuzz or forced conflicts; preserve unrelated local source edits. Abort on conflicting local bridge changes before stopping the service.
3. Run all bridge tests against the candidate with the existing VPS venv. The local `src/fx_scanner/execution/models.py` modification shown on the VPS is untouched.
4. Back up bridge source and SQLite checkpoints privately under `state/bridge-backup-*`. Stop only the bridge unit. Normalize only proven UTC legacy timestamps in XAU checkpoint models 1.1.0/1.2.1; preserve model, revision, pending label, LastSignalUtc and cooldown.
5. Atomically install the four production bridge Python files and start the same unit. Preserve local EnvironmentFiles and database paths.
6. Verify service activity, public WSS authentication, offset-aware snapshot and heartbeat, plus reconnect using synthetic identities without checkpoint saves or broker orders.

The script handles neither cTrader Cloud deployment nor changing Kirim order. The patched RizanXAUStable v1.2.1 algo must also be imported/restarted in cTrader with preserved parameters and checkpoint. Full cBot runtime acceptance still needs its Journal.

## Failure and rollback

On a post-stop failure, restore previous bridge code and try starting the same service. Restore the database backup only if no service start has yet been attempted. Once clients may have reconnected, keep current checkpoints; never rewind their order watermark. Failures print sanitized codes, not raw exception messages, env values, tokens or checkpoint bodies. Backups stay on the VPS and are not uploaded to Actions artifacts.

Tests cover patch conflict, scope restrictions, idempotency, preservation of unrelated local edits, safe env parsing and no checkpoint rewind after restart/probe failure. An Actions success must include DEPLOY_PASS and WSS_AUTH_TIMESTAMP_HEARTBEAT_RECONNECT_PASS. A workflow created or validation passed is not a completed deployment.
