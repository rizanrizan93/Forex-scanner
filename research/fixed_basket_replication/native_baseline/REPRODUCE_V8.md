# V8 isolated native research

Target remains USD100 to at least USD10 billion, continuous shared wallet,
maximum peak-to-trough floating equity DD strictly below 60%, leverage 1:200.
No LIVE, production VPS, checkpoint, broker connection, or order is authorized.

The 34 original source files were verified as Git blobs against commit
26bf8396b6e703d650e703fca48d556252782f03 under
research/r11_profitable_addon_alpha/native_original/. All matched.
The three exact CSV hashes also match the mandate. BTC begins in 2019.

Rebuild from a copy of that verified original source tree:

```bash
patch -d native -p1 < native_v8_from_verified_original.patch
dotnet build native/native_replay/NovemberReplay.csproj -c Release -o build -p:DefineConstants=REPLAY
dotnet build/NovemberReplay.dll --early-risk-selftest
```

The patch includes the previous Work research adapter, BTC filter, V5 native
parameter wiring, causal early sizing, observational diagnostics, and indexed
history lookups. It changes only the isolated research copy. It is not a LIVE
deployment patch. Check all original hashes before applying.

Use the R11 restore_native_inputs.py with the four existing private archives if
the exact recovered inputs are unavailable. Never commit price CSVs or private
archive URLs. Restored workspace locations are configurable with RIZAN_INPUTS,
RIZAN_SEED, RIZAN_DOTNET, RIZAN_DLL, and RIZAN_RESTORED_WORK. Seed tape layout is
40 bytes per row; control bootstrap needs base3_symbol0.bin. Seed tapes for other
profiles must be causally generated from the same inputs, never fabricated.

The legacy V7 runner wrote an empty macro object, although MacroDirection reads
an array even in off mode. V8 writes [] instead. This is an input-format fix.

No changed sizing can be approved from fixed-ledger PnL scaling. The locked V5
reference stays native_approved=false until actual replay evidence is attached.
Each native receipt must have zero accounting errors, no quarantines, no open
positions or BTC pending state, USD100 total initial contributions and no
additional capital, and a cash ledger residual below USD0.05.

Baseline gate: B1 balance 1662133293.0811067, floating DD
56.67209330213908%, 1047 baskets, 187560 requests. Indexed/diagnostic engine must
pass its own identical gate before batch workers use it.

Every scenario writes a compressed full receipt containing equity marks,
order and basket ledgers, accounting, costs, and diagnostic data. Batch workers
load price inputs once and publish verified receipts as each case completes.
45 priority challengers are configured; configured profiles are not completed
replays. The target is not declared reached from an intermediate balance.

The model uses original strategy C# plus research API stubs and synthetic M1
price paths, not the original .algo running on cTrader broker ticks. Admission
macro snapshots and reliable bridge heartbeats are synthetic inherited model
assumptions. They are not historical macro-vintage or live execution evidence.
Fees, slippage and funding scale with cost factor; historical spreads do not.
Broker stop-out and nonlinear market impact are not implemented. Observed
margin ratios and per-order volume limits must be reported; multi-billion
model balances do not certify real broker capacity.

Only same-path/same-cost comparisons are valid. Validate A1/B1/A2/B2, then
explicit spread and execution stresses, start-date and subperiod sensitivity.
2012-2018 is not validated merely by loading older price rows: inherited entry
and seed gates must be audited before any separate extended-period claim.
