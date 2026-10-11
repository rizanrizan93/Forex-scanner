# Original EUR cBot release archive

This folder contains byte-for-byte copies of existing original `.cs`, `.csproj`, and `.algo` files. It is an archive, not a deployment or strategy change. No file was rebuilt, repaired, reconfigured or reconstructed for this archive.

## Releases

- `v1.0.1/`: original pre-fix RizanEUR release from the existing migration workspace/ZIP. Common, EUR project, parity project and original binary are preserved.
- `v1.0.2/`: original fill-budget fix release from `release_eur102`; includes original tests and replay source. `Assembly.cs` is an existing source file, not newly generated.
- `v1.1.0/`: original RizanEURBatch release from `release_eur110` and its delivered `.algo`; includes original tests and replay source.
- `snapshots/fixed-workspace/`: original historical `fixed/` files. The project and binary still identify as v1.0.1; no correction was made to that snapshot. Do not assume its replay is a verified release build.
- `research/workspace/`: original EUR investigation, replay, batch prototype and AMD experiment source. These files are not additional compiled cBot releases.

## Provenance and verification

`MANIFEST.json` records SHA256, byte length, selected original and all matching workspace/ZIP provenance aliases for every archived original. ZIP containers are identified by SHA256. Every distinct readable eligible original byte sequence is covered. XAU-only files and generated bin/obj C# intermediates are excluded and listed. One evidence ZIP was invalid/truncated and is reported without reconstruction. No earlier release than v1.0.1 was found in the inspected inputs.

`SHA256SUMS` also covers the manifest, this README and secret audit. Use `sha256sum -c SHA256SUMS` from this folder. Git commit verification is performed externally so that the archive does not have a self-referential commit hash.

## Secret audit and scope

Credential signatures, private key headers, named literal credential assignments, Bearer values, URL credentials, readable binary strings and decompressible `.algo` metadata were scanned without printing credential values. No credential finding was detected. Compiled payloads were not fully decompiled; audit scope and limits are in `SECRET_AUDIT.json`. Source was not redacted because that would alter the original; any credential finding would block its upload.

No VPS, broker account, running cBot, trading setting, source strategy or execution logic was changed. `cbot_sources/archive/migration-20261010` belongs to a separate archive task and is not changed here.
