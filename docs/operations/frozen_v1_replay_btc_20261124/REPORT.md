# Frozen V1 uploaded algo — replay readiness and BTC live audit
Observation: 24 November 2026, 13:07:53 WIB (06:07:53 UTC).
Uploaded algo SHA-256: 7f58f6839c21785cdcce2c629acd5a2b009593f47dabb6effd8a1b0225a22619.
Release reference: 90172c2fba345e4221ca822c8e7d1d760a98c6b1.
Evidence run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45338143592

## Results
- VPS read-only collection succeeded; no live checkpoint, lease, service, order or configuration mutation.
- Bridge active, four connected peers, all four role leases active at observation.
- BTC checkpoint present, identity valid, storage version 7, stored client revision 8. These are different counters and unequal values alone are not a persistence failure.
- BTC fault=false, pending_intent=false, exit_pending=false; retained weekend lock expired 16 November.
- BTC minute extension: 56,520 rows from 16 October 00:00 UTC through 24 November 05:59 UTC. Expected completed-hour minute count matched; no timestamp gaps.
- Bridge reports BTC READY. This does not establish native FeedReady, in-memory acked revision, PortfolioReady, broker market hours, or absence of foreign exposure at the instance.
- Released functional checks PASS 86 assertions, real_orders=0. This uses API stubs and is not a historical profit replay.
- Source manifest check FAILED: source/GlobalAliases.cs and source/RizanXauEurPortfolio.cs differ from their manifest hashes. The uploaded binary still matches the recorded binary hash. This is a source provenance issue, not evidence the uploaded algo is corrupt.

## Historical replay status
| Window | Status |
|---|---|
| 2019–24 November 2026 | NOT EXECUTED. Requires isolated point-in-time replay adapter, verified matched historical three-instrument market and macro inputs, broker contract/cost assumptions, and source/binary provenance reconciliation. |
| 2012–24 November 2026 | NOT EXECUTED. In addition, production BTC validator requires history beginning 2019-01-01 and fixed seed through 2026-10-16; added XAU/BTC setup gates reject pre-2019 timestamps. A date-range change alone is not a valid full-strategy replay. |

Production BTC feed cannot accept an early-2019 point-in-time prefix because its pinned production seed includes data through October 2026. A replay must not inject that future history or touch live bridge state. Extending admission to pre-2019 is a separately labelled research variant, not the unchanged binary.

The limited VPS filename inventory found BTC seed packets but no replay csproj or named original growth ZIP under the inspected roots/depth. This is not proof no historical data exists elsewhere. VPS has Docker but no dotnet executable on PATH; GitHub functional tests used .NET 8 matching the test project.

No new ending balance, profit factor, drawdown, win rate or trade count is reported. Archived synthetic results must not be represented as a newly executed replay of this binary.
