# cTrader adapter v0.4

## Decision

cTrader Open API is the preferred execution backend. MT5 remains an explicit
compatibility fallback; automatic cross-broker failover is prohibited.

## Why

The scanner can run on a VPS/cloud host and connect directly to cTrader Open
API. The phone is a control/monitoring surface, not the 24/5 execution host.

```text
Phone / cTrader mobile / future control dashboard
                    |
                    v
              VPS / cloud
                    |
          FX scanner + runtime
                    |
              BrokerGateway
              /           \
      cTrader primary     MT5 fallback
```

## Official API flow

1. Register a cTrader Open API application.
2. Obtain client ID / client secret.
3. Authorize the user's cTID through OAuth 2.0 with `trading` scope.
4. Store access token only in VPS secrets.
5. Authenticate the application and selected ctidTraderAccountId.
6. Load broker symbol IDs/specifications.
7. Subscribe to spot events.
8. Use expected-margin request as broker preflight.
9. Submit `ProtoOANewOrderReq` only after scanner guards pass.

## Market data

`ProtoOASubscribeSpotsReq` is used for event-driven quotes. Bid/Ask protocol
prices are divided by 100000. Partial quote events are merged in-memory and a
trade is blocked unless a complete fresh Bid/Ask pair exists.

## Volume

The scanner keeps canonical order volume in lots. cTrader uses volume in
hundredths of a unit. Conversion uses the broker-provided `lotSize`,
`minVolume`, `maxVolume`, and `stepVolume` fields. No hard-coded 100,000-lot
assumption is used.

## Protection

For cTrader MARKET orders, absolute SL/TP is not supported in the new-order
request. v0.4 converts the scanner's absolute levels to protocol
`relativeStopLoss` and `relativeTakeProfit`, preserving server-side protection.
Pending LIMIT/STOP orders use absolute SL/TP.

## Deployment status

The adapter and protocol conversion are unit-tested with deterministic fake
sessions. A real network smoke test still requires:

- Pepperstone cTrader demo account
- approved cTrader Open API app
- OAuth access token with trading scope
- ctidTraderAccountId

Until then, execution remains `DISABLED`.
