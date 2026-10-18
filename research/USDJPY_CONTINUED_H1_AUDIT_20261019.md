# USDJPY continued research — 19 Oct 2026

Status: **NOT FROZEN · TARGET NOT ACHIEVED · RESEARCH ONLY**.

### Target
$100 to $100,000, leverage 1:200, equity compounding, total equity DD <50%.

### New executed work
- Dukascopy H1 full-span acquisition attempted through GitHub Actions; file returned zero bytes, then HTTP 202. **No full continuous data acquired.**
- Verified H1 archives: 2016–Mar 2022, Jan 2024–Apr 2025, Mar–Sep 2026. These datasets have significant unfilled gaps; DO NOT represent as 10 continuous years.
- **600,000 unique H1 parameter trials** across 1,200 causal signal rules, SL/TP and compounding; no valid $100k candidate with DD <50% on the available training sample.
- **200,000 sampled pyramiding/layering parameter trials**, with additive positions only when profitable, aggregate risk cap, equity compounding and DD throttle. No valid $100k candidate with DD <50%.
- Parameter-transplant checks against F0245-style 0.845 ATR stop, 10R TP, 20.75% risk, BE 2R and holding four hours do NOT reproduce original F0245 source/settlement M1 engine.

### Example research candidates (not live-validated)
- C26721: USDJPY SELL-only H1 EMA5/EMA200 crossover, New York (12:00–21:00 UTC), 0.845 ATR SL, 10R TP, risk 8%, BE2R, 24h max hold; calibration 2016–Mar 2022 **$1,424.76 / DD 37.17% / 118 trades**. On independent partial feed 2024–Apr 2025 **$149.23**, 2026 Mar–Sep **$108.93** from separate $100 resets. At 6-pip costs: **$435.18 / DD 44.23%**. Only **6 trades** in 2026 partial test. No add-on layers actually occurred in this candidate.
- C148128: Calibration **$2,263.53 / DD 44.44%**, but 6-pip stress causes DD **56.92%**; reject for robustness.

### Integrity / execution
Data source and exact code/csv/JSON results included in downloadable ZIP in the ChatGPT task outputs. Past EURUSD F0245 frozen cBot not changed. Main branch and broker untouched. Do not compare noncontinuous H1 calibration to 2016–2026 M1 native-tick replay.
