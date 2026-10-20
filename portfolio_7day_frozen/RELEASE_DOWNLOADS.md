# Frozen seven-day V1.3.0

Source freeze: `787ac228837175f9c07c4e13070e2794ebc7a7fe`.

Final CI audit: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39402108661

Native bundle, failure tests and read-only VPS evidence:
https://github.com/rizanrizan93/Forex-scanner/actions/runs/39402108661/artifacts/12255635264

The final CI_NATIVE_REBUILD.algo is promoted as the release binary. The exact binary is also preserved as `RizanXauEurBtcPortfolio_FROZEN_7DAY_WEEKEND_V1_3_0.algo.b64` here; base64-decode it to `RizanXauEurBtcPortfolio_FROZEN_7DAY_WEEKEND_V1_3_0.algo` and verify its SHA256 before import.

- ZIP: `RIZAN_XAU_EUR_BTC_FROZEN_7DAY_WEEKEND_V130.zip`
- ZIP bytes: 11470550
- ZIP SHA256: `003d96f56b74c0a8d7a98582dd60d06685646d2d3cdab79b32f8430daf3e7890`
- Binary SHA256: `a3d00f27ebe1f4f9eec2ede99fe56ef581556c42492e6e04817be19b19003b9c`
- ZIP members: 142

Default trading OFF. No live deployment. Current production bridge inspected read-only and left unchanged. New BTC seven-day bridge tested in isolation, NOT installed in production.

The last completed full replay predates only two final null-safe ownership predicates. Their equivalence for the non-null model labels is documented in checks/FINAL_GUARD_EQUIVALENCE.json. No completed full replay of the final guard source is claimed. Native final source build and 1087 C# assertions plus 6 Python tests passed. DD56 and USD90m portfolio targets remain unqualified.

The complete release ZIP and standalone binary are delivered with the accompanying report; the report includes full provenance and remaining validation limits.
