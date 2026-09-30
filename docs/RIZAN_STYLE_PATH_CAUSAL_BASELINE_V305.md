# V305 — Causal Reference-Time Baseline for V304

V304 originally compared a frozen public forecast reference with the latest moving RIZAN path. That is not a stable imitation test because the RIZAN map can legitimately remap after new market information arrives.

V305 changes the comparison basis.

## Rule

For every active public reference:

1. read `available_from`;
2. reconstruct V182 using only bars completed by that timestamp;
3. use neutral strategic bias so a later regime snapshot cannot leak backward;
4. reconstruct the M5 path using only M5 bars completed by that timestamp;
5. build V303 from that reconstructed atlas;
6. freeze that reconstructed V303 geometry as the V304 alignment baseline;
7. evaluate future outcome only with completed M15 bars after `available_from`.

The current live V303 path remains separate and continues to remap normally.

## Why this matters

The calibration now answers:

> “Given the information RIZAN could causally have had when the external forecast became available, how similar was its map?”

It no longer answers the misleading question:

> “How similar is today's latest RIZAN map to an older frozen forecast?”

## Runtime metadata

V304 now receives a `baseline` payload with:

- `mode=RECONSTRUCTED_AT_REFERENCE_AVAILABLE_FROM`;
- baseline timestamp;
- `causal=true`;
- neutral-bias marker;
- number of completed M5 bars used.

If reconstruction is impossible, it falls back explicitly to `CURRENT_PATH_FALLBACK` with `causal=false`; this state must not be treated as a clean prospective comparison.

## Execution

No execution authority or influence is added. This remains research-only.
