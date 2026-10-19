# Model validity and compact archive notes

These are historical M1 model results, not native broker or real bid/ask tick validation. BTC leverage10 remains an unverified research assumption; leverage2 sensitivity is separate. USDJPY model leverage200 is likewise not historical account certification.

The common engine has a permanent capital-floor stop after a completed trade: cash<=0, or positive cash below minUnit*signalBid/(2*leverage) forBTC, and minUnit/(2*leverage) forUSDJPY. This is an assumed account-deactivation policy. It does not model reactivation if later crypto prices make a minimum lot affordable. Therefore the negative target finding is conditional on this policy; it is not a proof that no possible strategy or recovery policy can reach100k. The main nominal selected leaders are separately checked below against the maximum floor over the actual data.

Drawdown is the chosen OHLC stress/envelope statistic. STOP_FIRST does not prove the true intraminute path or actual maximum drawdown. Snapshot prices, quote spread, financing, slippage, leverage tiers, execution hours, rejection/ACK/recovery and broker minimum-stop/grid rounding remain model assumptions.

This compact archive retains all3million configuration rows per instrument, actual source/parameters, canonical full-period M1 input, every selected raw transaction ledger and stress table, selected equity curves/charts, monthly/yearly summaries and provenance. Large redundant intermediate equity-curve CSVs and March-control data are omitted by file type, not by performance. The original complete archives remain unchanged in GitHub Actions39217369074 and the recorded VPS folder.

Non-applicable NaN report fields are normalized to JSONnull. Financial results and configuration rows are unchanged. Every retained compact file has a fresh complete SHA256 manifest.
