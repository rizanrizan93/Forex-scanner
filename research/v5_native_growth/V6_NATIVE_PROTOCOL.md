# V6 joint native growth search — 201,553,920 parameter configurations
Research only. Preserve V5_EARLY_2091M_LOCK.json unchanged, a fixed-ledger sensitivity reference (not a native or live result).
Use the original native Work source and V5 research adapters, no standalone substitution.
Search index is mixed-radix and does not claim that all configurations are economically distinct. Early sizing, seed universe, BTC target/hold/batch/filter, XAU target/SL and EUR target/BE/SL vary jointly. No increases to frozen nominal risk caps. 201,553,920 parameter tuples, not executed replays. Full enumeration at native speed is not a realistic first step; screen by deterministic pilot, use staged search and retain independent controls. 
Pilot: 256 sampled configurations, three control/reference profiles. 2019–13 November 2026, $100, continuous, B1 initial. Then verify A/B 1x/2x on shortlisted candidates; no new funds. For 2012–26, separately verify pre-2019 EUR/XAU seed and entry gates and BTC availability; never fabricate early data.
 
Run inside exact restored Work workspace:
1. Rebuild source pinned at 26bf8396b6e703d650e703fca48d556252782f03 using Work native_changes.patch, BtcResearchFilter.cs, extend_native.py, extend_early_native.py; then dotnet build.
2. python research/v5_native_growth/v6_search_space.py --pilot 256 --out v6_pilot.json
3. python research/v5_native_growth/run_v6_native.py --inputs /actual/restored/inputs --seed /actual/restored/seed --dll /actual/build/NovemberReplay.dll --work /actual/isolated/v6_pilot --profiles v6_pilot.json
Exact SHA256 of all three prices required. Control must reproduce B1 $1,662,133,293.0811067 / 56.67209330213908% / 1047 baskets / 187560 orders or halt. Seed tapes required for all selected instruments, generated from exact archived source. Archive completed economic receipts with cash, max floating DD, orders/baskets, observed risk/margin and accounting. No financial result from a software/index check. No LIVE or main changes.