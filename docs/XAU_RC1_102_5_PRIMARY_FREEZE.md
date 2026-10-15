# XAU RC1 $102.5 — Primary Frozen Research Profile

Status: **FROZEN_PRIMARY_RESEARCH_NOT_LIVE_ACTIVATED**

This profile supersedes the prior XAU configuration **for research/selection purposes only**. It does not change any live execution pointer, cBot binary, bridge authority, or automatic trading setting.

## Frozen contract

- Symbol: XAUUSD
- Account model: RAW
- Strategy ID: `XAUUSD_RC1_102_5_PRIMARY_FROZEN_V1`
- Contract SHA256: `2709c201f7b7854e714ccb1bfe904986b3dfe02cd13d73e6c071b127dd867142`
- Stop: `max($0.50, 2.40 × ATR_M5, structural anchor distance)`
- Target: `5.5R`
- Hold: `480 min`
- Loss cooldown: `3 calendar days`
- Layers: `0 / 0.20R / 0.40R`
- Add confirmation: required
- Add expiry: `90 min`
- Depth weighting power: `0.5`
- Initial fraction: `1.0`
- Balance step: `$102.50 per integer child`
- Child size model: `0.01 lot = 1 oz`
- Runtime risk cap: `12.1%`
- Margin cap: `50%`
- Reference leverage: `1:100`
- Send-reference tolerance: `0.2R`
- ACK stress set: `0 / 2 / 5 sec`
- Signal admission, macro/event gates, and session semantics: unchanged from prior frozen XAU.

## Replay evidence used for selection

2016–2025, initial equity $100, normal cost, ACK 0/adverse path:

- Ending balance: about **$40,128.46**
- Max DD: about **45.98%**
- PF: about **2.832**
- Baskets: **406**

Stress observed through 2025:

- Cost 1.5× worst observed DD: about **48.87%**
- Cost 2× worst observed DD: about **49.35%**

Extended replay through **2026-10-09** materially increases growth but also risk:

- Normal-cost ending balance range across tested ACK/path variants: about **$184,787–$210,099**
- Max DD range: about **51.30–51.35%**
- Baskets: **447**

Therefore this profile **does not satisfy the former strict DD <50% rule once 2026 is included**. It is frozen because the user explicitly selected the higher-growth RC1 $102.5 profile over the lower-DD $120 sizing variant.

## Delta from XAU Stable v1.2.1

- ATR stop multiple: `2.65 -> 2.40`
- TP: `6.6R -> 5.5R`
- Layer count: `4 -> 3`
- Layer depths: `0/.161111/.322222/.483333R -> 0/.20/.40R`
- Add expiry: `45 -> 90 min`
- Balance step: `$100 -> $102.50`

Unchanged:

- signal admission and macro/event gates
- confirmation requirement for adds
- depth weight power 0.5
- 480-minute hold
- runtime risk cap 12.1%
- 50% margin cap
- 3-day loss cooldown
- send-reference / ACK execution semantics

## Activation boundary

This commit is intentionally non-executable. It does not:

- modify the live cBot source used by the current runtime;
- replace the current `.algo` artifact;
- change an active strategy pointer;
- enable trading;
- place or schedule any order.

Any future implementation should be a separately versioned cBot release and should preserve the prior stable release for rollback and parity comparison.
