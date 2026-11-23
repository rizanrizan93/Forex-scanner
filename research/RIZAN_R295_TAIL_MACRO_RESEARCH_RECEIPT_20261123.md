# RIZAN R29.5 — H1/H4 SELL tail-risk and D1 conservative-lag macro research

**23 November 2026 (WIB).** Research only. No deployment of any R29.5 candidate to ForexScanner, cTrader, or Frozen V1.

## Reproducible evidence

- [GitHub Actions run 45176455650](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45176455650): anti-leakage/no-order tests and six H1/H4/D1 experiments, all completed **successfully**.
- Code: `scripts/r295_tailrisk_macro.py`; isolated branch `research/r295-tailrisk-macro-direction-20261123`.
- Original historical source: R10 intraday 2019–2026, R9.8 daily 2012–2026.
- Full annual/side metrics and selection provenance: artifacts `r295-tail_guard-1h`, `r295-coverage_guard-1h`, `r295-tail_guard-4h`, `r295-coverage_guard-4h`, `r295-tail_guard-1D`, `r295-coverage_guard-1D` on the Actions run.

## Actual results

| TF | Variant | BUY correct / n | BUY acc | SELL correct / n | SELL acc | Combined coverage | New success? |
|---|---|---:|---:|---:|---:|---:|---|
| H1 | tail_guard | 215/424 | 50.71% | 250/507 | 49.31% | 5.74% | NO |
| H1 | coverage_guard | 1706/3241 | 52.64% | 221/475 | 46.53% | 22.92% | NO |
| H4 | tail_guard | **79/126** | **62.70%** | 127/226 | 56.19% | 8.59% | NO (same frozen reference) |
| H4 | coverage_guard | 175/309 | 56.63% | 165/303 | 54.46% | 14.93% | NO |
| D1 | tail_guard | 101/215 | 46.98% | 27/59 | 45.76% | 31.53% | NO |
| D1 | coverage_guard | 106/208 | 50.96% | 50/118 | 42.37% | 37.51% | NO |

H4 tail_guard reproduces **exactly** the R29.2 H4 precision aggregate, not an independent new winning candidate. No new side gained a valid >60% historical net-positive result.

H4 SELL 2026 from R29.2 remains a cautionary example: 60/93 = 64.52% next-candle direction, but average net signed close-to-close **−$1.7863/oz** after the assumed $0.70/oz cost. Do NOT promote.

## Macro input provenance and limitations

In the R29.5 D1 run, all four FRED graph CSV requests (DGS2, DGS10, DFII10, DTWEXBGS) hit 20s HTTP read timeouts. The script invoked the existing **official U.S. Treasury yield XML** fallback (DGS2, DGS10, DFII10). The source manifest is archived with each D1 artifact. There was no verified DXY dataset; DTWEXBGS would be a broad-dollar proxy rather than DXY even if available. Historical **current-vintage** yields delayed by two business days are not genuine historical point-in-time vintages; the outcomes are exploratory and not suitable for live adoption.

Both BUY/SELL are selected on previous-year validation with label-maturity embargo. However, earlier years 2023–2026 were repeatedly inspected in R1–R29.5; these are NOT independent pristine out-of-sample data. All $/oz expectancy figures assume $0.70 cost, not a measured executable FP Markets bid/ask plus slippage.

## Frozen promotion decision

- Keep **R29.2 H4 BUY** frozen and separately shown in ForexScanner via [PR #921](https://github.com/rizanrizan93/Forex-scanner/pull/921). Its actual 2026 selected head is 14/23 (60.87%) retrospectively, and the pooled 2024–26 aggregate 79/126 (62.70%) combines different yearly policies. Live source is read-only and a trigger requires score >=0.54 AND trend_impulse gate.
- Reject R29.5 H1, H4 SELL, D1 from ForexScanner until fresh prospective and cost-aware evidence passes both accuracy and sample support.
- Next useful step is prospectively tracking frozen model predictions without reselecting on observed performance, preserving exact broker timestamp/closed-candle receipts and outcomes. For D1, acquire true release-calendar historical vintages (US2Y/US10Y, real yields, actual DXY/USDX and FOMC/CPI/NFP surprises) before retesting macro alpha.
- Never overwrite Frozen V1 or cTrader LIVE; no automated orders.

## Workflow IDs

- R29.2 original: run 45170505333.
- R29.3 historical extension: run 45171144710.
- R29.4 frozen H4 live-shadow proof: run 45174744359.
- R29.4 production publisher verified: run 45175563668.
- R29.5 risk/macro research: run 45176455650.
