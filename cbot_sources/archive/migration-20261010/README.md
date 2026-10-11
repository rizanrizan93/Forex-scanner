# Original cBot migration archive

This is an archival copy only. Nothing here was rebuilt, activated or changed.

- `initial-unversioned/`: original migration package without an explicit project release version.
- `v1.0.1/`: distinct original migration package declaring version 1.0.1.

Each version preserves Common, XAU/EUR projects, Parity, contracts, bridge source, reference code, build script and tests. Generated validation output is omitted and recorded in manifest.json. Compiled .algo files are the original supplied bytes.

Use manifest.json for SHA256, artifact/member provenance, duplicate aliases, scope exclusions and audit limitations. Shared bytes at required project paths are naturally deduplicated by Git. EUR follow-up releases are intentionally left to the separate eur-releases archive task. No claim of strategy parity or live readiness is made by archiving.
