# Afiq behavioral case ledger

This directory is the labeled evidence ledger used to refine V376 while trading continues.

For every new Afiq forecast supplied by the user, store a case before outcome labels are added whenever possible. Preserve the original forecast timestamp, visible timeframes, quoted/annotated levels, zone roles, expected path, liquidity expectation, confirmation requirement, entry/invalidation/targets, wait/no-trade reasoning, and later outcome.

Evidence classes:

- `USER_CAPTURED_AFIQ_CASES`: screenshots/messages supplied by the user.
- `PUBLIC_AFIQ_ARCHIVE`: public timestamped forecasts with source URL.

Do not calibrate from testimonials, after-the-fact wins without the original forecast, or uncited performance claims.

The engine should learn both positive and negative examples: successful forecasts, failed forecasts, no-trade calls, plan changes, and zones Afiq explicitly ignores. Behavioral fidelity is measured separately from trading P&L.

Production policy:

- V376 may improve dashboard decision support continuously.
- V376 may veto DEMO candidates only on explicit causal failure states.
- V376 does not create LIVE orders. LIVE remains manual.
- New screenshot-derived rules must be expressed as objective causal features before they affect DEMO execution.
