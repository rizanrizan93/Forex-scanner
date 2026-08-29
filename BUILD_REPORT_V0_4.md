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
