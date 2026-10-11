# Recovery checkpoint — authoritative SQLite

Source audit: Turso `mirror_turso` upserts only `runtime_heartbeats`. A Turso PASS is not checkpoint backup coverage. SQLite remains authoritative; changing that would require a separate sequencing proof.

| Failure | Current protection | Required evidence |
| --- | --- | --- |
| Bridge process restart | WAL/FULL checkpoint + durable receipt/lease; local integration passed | Same persistent DB path on deployed service |
| VPS reboot | Same design if disk and path survive | Actual reboot and reconnect verification, not yet performed |
| Total VPS/disk loss | Not covered by a local SQLite DB or snapshot JSON | Verified off-host backup, restore drill and explicit stale-state reconciliation |

## Off-host backup design (not deployed)

1. A separate read-only support worker uses SQLite's online backup API into a private directory (0700), produces a consistent standalone database (0600), runs `PRAGMA integrity_check`, and records SHA256, schema versions, namespaces, server/client revisions and UTC time. Do not copy only the live `.sqlite` file while WAL writes continue.
2. Encrypt before upload to a separate host/storage account. Credentials remain outside the backup and source. Checkpoints contain private account/state data even though they do not contain broker credentials. Manifests shared with users must mask accounts.
3. Each object key is immutable/idempotent (encrypted digest + timestamp). Upload an integrity manifest only after successful object upload. Retain multiple generations; alert on age and failed uploads. Backup errors never reorder ACKs or broker operations.
4. SQLite save/receipt/CAS and lease ACK sequencing stay authoritative. An asynchronous mirror has a nonzero RPO: fills after the latest uploaded checkpoint may be absent. Do not call this exactly-once disaster recovery.
5. A fresh VPS is restored privately from a verified backup, with token/certificate configured separately and its clock synchronized. Ensure the old host cannot still serve the same identity. Wait for lease expiry; do not bypass it. Reconcile positions, history, pending labels/children and actual batch anchor against the broker before considering any new intent. Preserve budget, peak, sequence and virtual feedback. Unresolved state must remain quarantined; never silently reset a stale backup to a fresh basket.
6. Run a synthetic restore drill and record RPO/RTO before claiming disk-loss protection. Do not test by deleting a live trading database.

A Turso checkpoint mirror can be a future off-host store keyed by namespace + client revision, with contract/schema/model, digest, UTC time and opaque state. It must reject revision reuse with different bytes. It remains a backup until a separately tested authority/lease/receipt protocol proves synchronous durability and broker reconciliation. No such mirror is implemented or claimed here.
