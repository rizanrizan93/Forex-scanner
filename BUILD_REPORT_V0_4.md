# FX Institutional Scanner v0.4 build report

- Preferred backend: cTrader Open API
- Explicit fallback: MT5
- Automatic cross-broker failover: forbidden
- Execution mode: DISABLED
- Broker-agnostic router: implemented
- cTrader event-driven quote session: implemented
- cTrader lot/volume conversion: implemented
- cTrader expected-margin preflight: implemented
- cTrader server-side market SL/TP conversion: implemented
- Runtime hardening v0.3: incorporated
- Database/control-plane schema: extended
- Unit/regression suite: 48/48 PASS
- Deterministic 24h runtime smoke: PASS
- cTrader live network test: pending Pepperstone demo credentials/Open API approval
- Real-money readiness: NOT CLAIMED

- Dedicated Supabase project: Forex scanner / fotzcxjeypmjldhvfskt
- Supabase region: ap-southeast-1
- Supabase schema: 16 public tables, RLS enabled
- Canonical FX universe: 15/15 symbols seeded
- Security advisor: 0 findings after hardening
- Supabase operational adapter: implemented
- Cached control-plane live gate: implemented
- Supabase refresh network I/O isolated from order path
- Bootstrap control state: DISABLED / new orders false / emergency stop true
- Backend secret: intentionally not committed; VPS injection pending
