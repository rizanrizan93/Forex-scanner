# BUY050 identity bridge hotfix — 2026-11-08

Scope: isolated bridge and transport-only cBot defaults/quarantine recovery. Frozen strategy unaffected.

**No cTrader deployment is completed by pushing source.** GitHub Actions must compile and publish the patched `.algo`; bridge deployment to VPS must be audited separately before using that build.

Live account suffix: 7903. Never include account credentials or bridge token in logs. Do not start duplicate cBots; do not erase checkpoints or quarantine by hand.
