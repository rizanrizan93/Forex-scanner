# RIZAN CROSS-ASSET LEAD–LAG ENGINE

**Verdict: RESEARCH ONLY. Tidak ada model disetujui untuk production atau order.**

108 file tahunan; 37,372,600 bar M1; 11 instrumen; 45 kandidat asset/target/timeframe; 7049 pengujian train lintas fold/lag, dikoreksi BH-FDR bersama.

## Dataset dan validitas

HistData public bid OHLC 2016–2025: XAUUSD, EURUSD, GBPUSD, USDCHF, USDJPY, XAGUSD, EURGBP, UDXUSD (DXY CFD), SPXUSD (SPX CFD), NSXUSD (Nasdaq CFD). WTIUSD hanya 2016–2023; request 2024/2025 gagal/empty response. WTI memakai holdout eksploratif 2023, tidak sebanding langsung dengan holdout umum 2025. Tiap file memiliki SHA256, jumlah bar, waktu UTC pertama/terakhir, gap dan persentase unchanged quotes dalam JSON.

Timestamp sumber adalah OPEN fixed EST UTC−5, diubah ke completed UTC; session London/NY mengikuti DST, overlap terpisah, display scanner WIB. Tidak ada interpolasi, forward-fill, atau penggunaan bucket parsial. Gap termasuk penutupan pasar dan tidak dianggap seluruhnya sebagai error feed. HistData bukan rekaman broker FP Markets/tick ASK.

US2Y, US10Y, TIPS/real yield, DE2Y, DE10Y, spread yields, VIX, copper intraday sejajar belum tersedia. Daily yields tidak diinterpolasi menjadi data intraday. Urutan US2Y → yields → DXY → EURUSD → XAU tidak dapat divalidasi. Kalender macro historis lengkap juga tidak tersedia; NFP/CPI/PCE/FOMC/Powell/JOLTS/Claims/ISM/Retail/GDP/UoM event-versus-normal tidak dapat diukur secara sah. UNKNOWN event state memblokir execution.

## Metode

M1/M5/M15. Lag 0 sebagai kontrol contemporaneous; grid 1–30 menit serta 45/60/90/120 disesuaikan resolusi timeframe. Lagged-return CCF dibedakan dari cumulative future response. Pearson rolling, Spearman, partial correlation mengontrol return target diketahui/current+previous, shock conditional probability (2 sigma train), directional hit rate, divergence/horizon 5/10/15/30/60, mutual information deskriptif, ADF/Granger pada segmen contiguous stationer, bootstrap block confidence interval dan daily wild-sign null.

Train expanding annual, walk-forward 2017–2024, holdout lead–lag 2025; purge 120 menit + timeframe. Parameter dipilih hanya train; bootstrap 500 draws, null 199 draws (resolusi p=.005), satu family BH-FDR 7.049 tests. M1 training satu observasi seeded per blok 15 menit; OOS seluruh event eligible; Spearman train chronological thinning ~50k. Events dide-overlap berdasarkan elapsed time. Hasil session/regime/horizon adalah deskriptif dan tidak menjadi optimizer OOS. DXY–EURUSD ditandai structural dependency, bukan independent alpha.

Bull/bear/range dan high/low volatility dihitung causal dari return/trend/realized volatility. Risk-on/off dan high-yield volatility tidak dapat divalidasi lengkap; ADX/ATR bukan seluruh regime yang diimplementasikan. Ini keterbatasan eksplisit. Dynamic lag tidak diaktifkan karena kandidat gagal; konsistensi fold lag tersedia di bawah.

## Ranking seluruh kandidat dan alasan penolakan

Ranking deskriptif berdasarkan lower confidence bound, common holdout dahulu. Bukan pemilihan winner untuk trading. Predictive score/confidence 0–100 tidak dibuat karena belum ada kalibrasi probability yang lolos.

|#|Target|Leader|TF|Holdout|Lag min|Train Pearson|OOS partial corr|OOS P arah + CI95|Train q|WF pass|Verdict|
|---|---|---|---|---|---|---|---|---|---|---|---|
|1|XAUUSD|USDJPY|M5|2025|5|-0.0005|-0.0120|51.17% [49.7156, 52.6451] N=3516|0.2842|0.0000|RESEARCH ONLY|
|2|XAUUSD|EURUSD|M1|2025|1|0.0097|0.0093|49.79% [48.9732, 50.5739] N=14122|0.5874|0.0000|RESEARCH ONLY|
|3|XAUUSD|USDCHF|M1|2025|1|-0.0085|-0.0127|49.78% [48.9441, 50.6548] N=13595|0.2842|0.0000|RESEARCH ONLY|
|4|EURUSD|USDJPY|M1|2025|27|0.0088|0.0015|50.09% [48.9066, 51.1871] N=6912|0.2842|0.0000|RESEARCH ONLY|
|5|XAUUSD|USDJPY|M1|2025|28|-0.0084|-0.0013|50.05% [48.8611, 51.1842] N=6629|0.5133|0.0000|RESEARCH ONLY|
|6|EURUSD|EURGBP|M5|2025|5|-0.0152|-0.0005|50.16% [48.7732, 51.5969] N=4039|0.2842|0.0000|RESEARCH ONLY|
|7|EURUSD|DXY|M15|2025|60|0.0054|-0.0049|52.46% [48.6752, 56.2544] N=568|0.9518|0.2500|RESEARCH ONLY|
|8|XAUUSD|DXY|M1|2025|1|-0.0062|-0.0079|49.54% [48.6467, 50.5042] N=11311|0.5133|0.3750|RESEARCH ONLY|
|9|XAUUSD|GBPUSD|M15|2025|60|-0.0107|-0.0007|52.28% [48.5820, 55.7337] N=811|0.5133|0.0000|RESEARCH ONLY|
|10|XAUUSD|GBPUSD|M1|2025|10|0.0099|0.0045|49.43% [48.4905, 50.3818] N=11131|0.4272|0.0000|RESEARCH ONLY|
|11|XAUUSD|SPX|M1|2025|1|0.0130|0.0044|49.31% [48.4606, 50.1161] N=13349|0.9212|0.0000|RESEARCH ONLY|
|12|XAUUSD|USDCHF|M5|2025|5|0.0018|-0.0126|49.78% [48.3381, 51.4571] N=3881|0.2842|0.0000|RESEARCH ONLY|
|13|XAUUSD|XAGUSD|M1|2025|1|0.0043|0.0150|49.12% [48.3244, 50.0827] N=13368|0.2842|0.0000|RESEARCH ONLY|
|14|XAUUSD|DXY|M5|2025|5|-0.0019|-0.0097|50.03% [48.3040, 51.9048] N=3100|0.2842|0.0000|RESEARCH ONLY|
|15|XAUUSD|GBPUSD|M5|2025|60|-0.0043|-0.0006|50.54% [48.2933, 53.0749] N=1935|0.5133|0.0000|RESEARCH ONLY|
|16|XAUUSD|USDCHF|M15|2025|15|-0.0106|-0.0145|51.04% [48.2424, 54.1295] N=1054|0.2842|0.0000|RESEARCH ONLY|
|17|EURUSD|GBPUSD|M1|2025|1|0.0061|0.0144|48.94% [48.2245, 49.8096] N=14447|0.2842|0.0000|RESEARCH ONLY|
|18|EURUSD|USDJPY|M5|2025|5|-0.0043|-0.0103|49.86% [48.1851, 51.7011] N=3558|0.2842|0.0000|RESEARCH ONLY|
|19|XAUUSD|XAGUSD|M5|2025|5|-0.0133|0.0151|49.78% [48.1047, 51.3885] N=3853|0.2842|0.2500|RESEARCH ONLY|
|20|EURUSD|USDCHF|M5|2025|5|0.0147|-0.0055|49.74% [48.0943, 51.3567] N=4017|0.4272|0.0000|RESEARCH ONLY|
|21|XAUUSD|NQ|M5|2025|120|-0.0040|0.0015|50.44% [47.9518, 53.2530] N=1245|0.8081|0.0000|RESEARCH ONLY|
|22|EURUSD|USDCHF|M1|2025|1|0.0005|-0.0143|48.66% [47.9186, 49.4108] N=14418|0.6249|0.1250|RESEARCH ONLY|
|23|XAUUSD|NQ|M1|2025|120|-0.0139|0.0040|49.84% [47.8180, 52.0449] N=2225|0.5133|0.0000|RESEARCH ONLY|
|24|EURUSD|SPX|M1|2025|3|0.0097|-0.0060|48.60% [47.7566, 49.4113] N=13330|0.7343|0.0000|RESEARCH ONLY|
|25|EURUSD|SPX|M5|2025|5|0.0061|-0.0233|49.12% [47.5200, 50.7134] N=4135|0.2842|0.0000|RESEARCH ONLY|
|26|XAUUSD|EURUSD|M5|2025|5|-0.0033|0.0066|49.06% [47.5119, 50.6248] N=4005|0.5133|0.0000|RESEARCH ONLY|
|27|EURUSD|GBPUSD|M5|2025|5|-0.0078|0.0031|48.90% [47.4292, 50.3893] N=3988|0.2842|0.0000|RESEARCH ONLY|
|28|EURUSD|EURGBP|M15|2025|15|-0.0156|-0.0157|50.23% [47.4208, 53.1697] N=1105|0.7769|0.1250|RESEARCH ONLY|
|29|XAUUSD|SPX|M5|2025|5|0.0022|-0.0135|48.92% [47.4105, 50.6297] N=4133|0.9963|0.0000|RESEARCH ONLY|
|30|EURUSD|EURGBP|M1|2025|2|-0.0159|-0.0013|48.04% [47.2137, 48.8463] N=14252|0.7069|0.1250|RESEARCH ONLY|
|31|XAUUSD|NQ|M15|2025|60|-0.0081|0.0098|50.80% [47.1095, 54.3081] N=813|0.8775|0.0000|RESEARCH ONLY|
|32|EURUSD|USDJPY|M15|2025|15|0.0012|-0.0133|49.60% [46.8127, 52.5896] N=1004|0.8089|0.0000|RESEARCH ONLY|
|33|EURUSD|DXY|M1|2025|29|-0.0055|0.0008|48.01% [46.7246, 49.3101] N=5649|0.7695|0.0000|RESEARCH ONLY|
|34|XAUUSD|XAGUSD|M15|2025|15|-0.0021|0.0085|49.12% [46.6977, 51.8628] N=1075|0.5133|0.1250|RESEARCH ONLY|
|35|EURUSD|DXY|M5|2025|15|-0.0033|-0.0046|48.64% [46.5839, 50.5435] N=2576|0.8089|0.0000|RESEARCH ONLY|
|36|XAUUSD|SPX|M15|2025|60|-0.0092|0.0138|50.40% [46.3398, 54.3251] N=752|0.8991|0.0000|RESEARCH ONLY|
|37|XAUUSD|USDJPY|M15|2025|15|-0.0116|-0.0114|49.00% [46.0080, 51.8488] N=1002|0.2842|0.0000|RESEARCH ONLY|
|38|XAUUSD|DXY|M15|2025|15|-0.0096|-0.0141|48.60% [44.9580, 52.1008] N=714|0.2842|0.0000|RESEARCH ONLY|
|39|EURUSD|GBPUSD|M15|2025|15|-0.0040|0.0139|47.57% [44.4860, 50.4673] N=1070|0.7069|0.0000|RESEARCH ONLY|
|40|EURUSD|SPX|M15|2025|90|-0.0098|0.0165|47.77% [43.7062, 51.2739] N=628|0.7343|0.0000|RESEARCH ONLY|
|41|XAUUSD|EURUSD|M15|2025|15|0.0025|0.0020|46.43% [43.3873, 49.3815] N=1051|0.7343|0.1250|RESEARCH ONLY|
|42|EURUSD|USDCHF|M15|2025|15|0.0098|-0.0315|45.97% [42.6829, 48.9681] N=1066|0.8684|0.0000|RESEARCH ONLY|
|43|XAUUSD|WTI|M1|2023|5|-0.0116|0.0035|49.97% [48.9761, 50.9591] N=9916|1.0000|0.0000|RESEARCH ONLY|
|44|XAUUSD|WTI|M5|2023|45|0.0041|-0.0237|48.63% [46.2649, 50.8707] N=1674|0.8089|0.0000|RESEARCH ONLY|
|45|XAUUSD|WTI|M15|2023|30|0.0070|-0.0246|47.58% [43.4850, 51.2521] N=599|0.9415|0.0000|RESEARCH ONLY|

Tidak ada BEST XAU/EURUSD LEADER atau BEST LAG yang terverifikasi. Semua rejection reasons lengkap, train grids, rolling quantiles, Granger/MI status dan dataset quality ada di `research/results/rizan_cross_asset_2016_2025.json`.

### DXY → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [5, 5, 5, 5, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 5]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.63% [46.7523, 55.3153] N=555|
|LONDON|50.98% [48.1764, 54.0288] N=1179|
|LONDON_NEW_YORK_OVERLAP|48.19% [45.3110, 51.2094] N=1077|
|NEW_YORK|52.31% [45.9075, 58.1940] N=281|
|OFF_SESSION|45.45% [N/A, N/A] N=11|
|RANGE|49.89% [48.0278, 51.6801] N=2738|
|BULL_TREND|52.24% [47.0149, 58.5821] N=268|
|BEAR_TREND|50.00% [40.6618, 58.8235] N=102|
|LOW_VOLATILITY|50.09% [47.9973, 52.2135] N=1649|
|HIGH_VOLATILITY|50.17% [47.6190, 52.9929] N=1471|

Horizon/divergence detail: {"5": {"events": 3100, "probability": 0.5003225806451613, "ci_low": 0.48304032258064517, "ci_high": 0.5190483870967741, "mean_signed_return": 8.610037663188913e-06, "divergence": {"events": 943, "probability": 0.47932131495228, "ci_low": 0.4442735949098622, "ci_high": 0.5153764581124072, "mean_signed_return": -4.237867662685076e-06}}, "10": {"events": 2790, "probability": 0.503584229390681, "ci_low": 0.48494623655913977, "ci_high": 0.522410394265233, "mean_signed_return": 4.7421890410572164e-05, "divergence": {"events": 914, "probability": 0.49671772428884026, "ci_low": 0.46332056892778994, "ci_high": 0.5306345733041575, "mean_signed_return": 6.821227319462949e-05}}, "15": {"events": 2570, "probability": 0.5249027237354086, "ci_low": 0.5066147859922179, "ci_high": 0.5430058365758754, "mean_signed_return": 6.549559520532773e-05, "divergence": {"events": 886, "probability": 0.5270880361173815, "ci_low": 0.49435665914221216, "ci_high": 0.5581546275395034, "mean_signed_return": 9.049707673660515e-05}}, "30": {"events": 2096, "probability": 0.5143129770992366, "ci_low": 0.4923425572519084, "ci_high": 0.5360329198473283, "mean_signed_return": 4.766531677523416e-05, "divergence": {"events": 812, "probability": 0.5086206896551724, "ci_low": 0.47783251231527096, "ci_high": 0.5443349753694581, "mean_signed_return": 9.496209195664489e-06}}, "60": {"events": 1579, "probability": 0.5098163394553515, "ci_low": 0.4844838505383154, "ci_high": 0.5370804306523116, "mean_signed_return": 9.414604253134482e-05, "divergence": {"events": 704, "probability": 0.5340909090909091, "ci_low": 0.4978338068181818, "ci_high": 0.5738636363636364, "mean_signed_return": 0.0002121931198920571}}}

### EURUSD → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [45, 20, 20, 20, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 45]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|47.50% [44.1600, 50.4456] N=1122|
|LONDON|50.69% [48.3516, 53.1628] N=1456|
|LONDON_NEW_YORK_OVERLAP|48.39% [45.8219, 51.2397] N=1089|
|NEW_YORK|50.89% [44.2972, 57.2954] N=281|
|OFF_SESSION|44.07% [35.5932, 52.5424] N=59|
|RANGE|48.98% [47.3331, 50.6606] N=3565|
|BULL_TREND|49.08% [44.1718, 54.4555] N=326|
|BEAR_TREND|53.72% [43.8017, 62.8099] N=121|
|LOW_VOLATILITY|49.29% [47.4014, 51.2479] N=2408|
|HIGH_VOLATILITY|48.82% [46.4064, 51.4870] N=1614|

Horizon/divergence detail: {"5": {"events": 4005, "probability": 0.49063670411985016, "ci_low": 0.47511860174781523, "ci_high": 0.5062484394506866, "mean_signed_return": -9.651455706418118e-06, "divergence": {"events": 1272, "probability": 0.4772012578616352, "ci_low": 0.4473270440251572, "ci_high": 0.5055031446540881, "mean_signed_return": -3.2846219356605915e-05}}, "10": {"events": 3586, "probability": 0.48968209704406024, "ci_low": 0.47209983268265476, "ci_high": 0.5069854991634132, "mean_signed_return": 1.4163906388325683e-05, "divergence": {"events": 1220, "probability": 0.489344262295082, "ci_low": 0.4589754098360656, "ci_high": 0.5204918032786885, "mean_signed_return": 2.2684003632628698e-05}}, "15": {"events": 3291, "probability": 0.5025828015800669, "ci_low": 0.48495897903372837, "ci_high": 0.5214220601640839, "mean_signed_return": 3.07206510185011e-05, "divergence": {"events": 1181, "probability": 0.5131244707874683, "ci_low": 0.48179508890770534, "ci_high": 0.5457451312447078, "mean_signed_return": 4.705356507370805e-05}}, "30": {"events": 2658, "probability": 0.4969902182091798, "ci_low": 0.4776053423626787, "ci_high": 0.5158013544018059, "mean_signed_return": 8.124626536798033e-06, "divergence": {"events": 1076, "probability": 0.4962825278810409, "ci_low": 0.46654275092936803, "ci_high": 0.5251394052044609, "mean_signed_return": -3.1727000374931324e-05}}, "60": {"events": 1981, "probability": 0.49873801110550225, "ci_low": 0.4767667844522968, "ci_high": 0.5232332155477032, "mean_signed_return": 3.776180085790188e-05, "divergence": {"events": 917, "probability": 0.5332606324972737, "ci_low": 0.4983642311886587, "ci_high": 0.5670665212649946, "mean_signed_return": 0.00010690258302642977}}}

### USDJPY → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [5, 5, 5, 5, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 5]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.81% [47.0008, 52.5835] N=1317|
|LONDON|51.90% [48.4772, 54.9492] N=788|
|LONDON_NEW_YORK_OVERLAP|52.38% [49.4530, 55.5446] N=1010|
|NEW_YORK|52.03% [46.4945, 57.0203] N=271|
|OFF_SESSION|50.38% [42.8571, 57.5376] N=133|
|RANGE|51.41% [49.7946, 53.0821] N=3165|
|BULL_TREND|48.18% [42.3175, 54.3796] N=274|
|BEAR_TREND|55.56% [44.4444, 65.4321] N=81|
|LOW_VOLATILITY|50.05% [47.9742, 52.2802] N=2172|
|HIGH_VOLATILITY|53.08% [50.4405, 55.8388] N=1362|

Horizon/divergence detail: {"5": {"events": 3516, "probability": 0.5116609783845278, "ci_low": 0.49715585893060293, "ci_high": 0.5264505119453925, "mean_signed_return": 2.8058761606628036e-05, "divergence": {"events": 1221, "probability": 0.5102375102375102, "ci_low": 0.48157248157248156, "ci_high": 0.5405405405405406, "mean_signed_return": 7.095754576933638e-06}}, "10": {"events": 3172, "probability": 0.5091424968474149, "ci_low": 0.4921185372005044, "ci_high": 0.5257172131147541, "mean_signed_return": 3.9817546689987417e-05, "divergence": {"events": 1171, "probability": 0.5183603757472246, "ci_low": 0.4910333048676345, "ci_high": 0.5482493595217762, "mean_signed_return": 4.3343770951119535e-05}}, "15": {"events": 2905, "probability": 0.5101549053356282, "ci_low": 0.493631669535284, "ci_high": 0.5263339070567986, "mean_signed_return": 5.093589211360756e-05, "divergence": {"events": 1132, "probability": 0.515017667844523, "ci_low": 0.4871687279151944, "ci_high": 0.5397526501766784, "mean_signed_return": 5.683743097906913e-05}}, "30": {"events": 2433, "probability": 0.5129469790382244, "ci_low": 0.49423551171393343, "ci_high": 0.5328914919852035, "mean_signed_return": 7.90511500337354e-05, "divergence": {"events": 1035, "probability": 0.49468599033816424, "ci_low": 0.4622946859903382, "ci_high": 0.523671497584541, "mean_signed_return": 4.316562265287598e-06}}, "60": {"events": 1852, "probability": 0.5043196544276458, "ci_low": 0.48056155507559395, "ci_high": 0.5269978401727862, "mean_signed_return": 1.1558403549118889e-05, "divergence": {"events": 888, "probability": 0.5056306306306306, "ci_low": 0.47742117117117117, "ci_high": 0.5371621621621622, "mean_signed_return": 8.72675812296792e-06}}}

### GBPUSD → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 30, 30, 30, 60, 60, 60, 60], 'oos_selected_lag': 60, 'range_minutes': [30, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.09% [45.4262, 54.6573] N=569|
|LONDON|50.20% [47.0034, 53.6054] N=735|
|LONDON_NEW_YORK_OVERLAP|50.00% [45.4023, 54.5977] N=522|
|NEW_YORK|48.54% [40.6287, 55.5556] N=171|
|OFF_SESSION|46.34% [36.5854, 56.0976] N=41|
|RANGE|51.56% [49.1775, 54.0286] N=1763|
|BULL_TREND|43.60% [36.0465, 50.5814] N=172|
|BEAR_TREND|44.12% [32.3529, 55.8824] N=68|
|LOW_VOLATILITY|50.58% [47.7252, 53.4711] N=1210|
|HIGH_VOLATILITY|49.88% [45.9330, 53.4121] N=836|

Horizon/divergence detail: {"5": {"events": 3950, "probability": 0.5025316455696203, "ci_low": 0.4882215189873418, "ci_high": 0.5192405063291139, "mean_signed_return": 6.534267774827957e-06, "divergence": {"events": 2882, "probability": 0.49722414989590563, "ci_low": 0.4803868841082582, "ci_high": 0.5154493407356003, "mean_signed_return": -6.111763760261586e-06}}, "10": {"events": 3549, "probability": 0.5018315018315018, "ci_low": 0.48520710059171596, "ci_high": 0.5183220625528318, "mean_signed_return": -2.4599497427346315e-05, "divergence": {"events": 2654, "probability": 0.5, "ci_low": 0.4813394875659382, "ci_high": 0.517709118311982, "mean_signed_return": -3.268356874394117e-05}}, "15": {"events": 3231, "probability": 0.49613122872175797, "ci_low": 0.4775611265861962, "ci_high": 0.5139353141442278, "mean_signed_return": -2.4578852150506375e-05, "divergence": {"events": 2458, "probability": 0.49755899104963386, "ci_low": 0.47843775427176566, "ci_high": 0.5181143205858422, "mean_signed_return": -3.0092538651808523e-05}}, "30": {"events": 2618, "probability": 0.4912146676852559, "ci_low": 0.4722975553857907, "ci_high": 0.5086038961038961, "mean_signed_return": -6.123683894263949e-06, "divergence": {"events": 2088, "probability": 0.5009578544061303, "ci_low": 0.4798611111111111, "ci_high": 0.5229885057471264, "mean_signed_return": -4.005346418652028e-06}}, "60": {"events": 1935, "probability": 0.5054263565891473, "ci_low": 0.48293281653746767, "ci_high": 0.530749354005168, "mean_signed_return": 5.7663147445630785e-05, "divergence": {"events": 1604, "probability": 0.5024937655860349, "ci_low": 0.4763092269326683, "ci_high": 0.5280548628428927, "mean_signed_return": 6.755408227876751e-05}}}

### USDCHF → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [120, 5, 5, 5, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 120]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.29% [47.0175, 53.0994] N=855|
|LONDON|50.88% [48.3761, 53.5707] N=1541|
|LONDON_NEW_YORK_OVERLAP|47.71% [45.0764, 50.7640] N=1178|
|NEW_YORK|53.09% [45.6790, 59.2593] N=243|
|OFF_SESSION|45.83% [36.1111, 56.2847] N=72|
|RANGE|50.28% [48.5905, 52.2675] N=3441|
|BULL_TREND|46.81% [41.3374, 52.1353] N=329|
|BEAR_TREND|43.48% [33.9130, 53.0435] N=115|
|LOW_VOLATILITY|49.87% [48.1675, 52.2273] N=2292|
|HIGH_VOLATILITY|49.72% [47.3326, 51.8909] N=1613|

Horizon/divergence detail: {"5": {"events": 3881, "probability": 0.4978098428240144, "ci_low": 0.48338057201752127, "ci_high": 0.5145709868590569, "mean_signed_return": -9.136940259017195e-06, "divergence": {"events": 1297, "probability": 0.48959136468774095, "ci_low": 0.4633770239013107, "ci_high": 0.5173477255204317, "mean_signed_return": -3.57355581766994e-05}}, "10": {"events": 3482, "probability": 0.5040206777713957, "ci_low": 0.48907237219988514, "ci_high": 0.5204049396898334, "mean_signed_return": 1.359936168824809e-05, "divergence": {"events": 1244, "probability": 0.4895498392282958, "ci_low": 0.4569734726688103, "ci_high": 0.5192926045016077, "mean_signed_return": -1.6940777260793224e-05}}, "15": {"events": 3167, "probability": 0.5026839280075781, "ci_low": 0.4859172718661193, "ci_high": 0.5197505525734133, "mean_signed_return": 2.2674017559029904e-05, "divergence": {"events": 1185, "probability": 0.4919831223628692, "ci_low": 0.4620042194092827, "ci_high": 0.5198312236286919, "mean_signed_return": -1.8075804497153718e-05}}, "30": {"events": 2549, "probability": 0.504119262455865, "ci_low": 0.4831012161632013, "ci_high": 0.5225578658297372, "mean_signed_return": 4.66951454482628e-05, "divergence": {"events": 1068, "probability": 0.48782771535580527, "ci_low": 0.4615168539325843, "ci_high": 0.5159176029962547, "mean_signed_return": -2.8889013125518637e-05}}, "60": {"events": 1883, "probability": 0.49389272437599574, "ci_low": 0.470246946362188, "ci_high": 0.5199150292087095, "mean_signed_return": 3.357630021097458e-05, "divergence": {"events": 900, "probability": 0.48444444444444446, "ci_low": 0.45222222222222225, "ci_high": 0.5205833333333333, "mean_signed_return": -9.211001157359868e-05}}}

### XAGUSD → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [45, 25, 5, 5, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 45]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|47.76% [45.1786, 50.5814] N=1204|
|LONDON|50.58% [47.2901, 53.8789] N=941|
|LONDON_NEW_YORK_OVERLAP|50.21% [47.2521, 52.8905] N=1402|
|NEW_YORK|51.55% [46.1240, 57.7519] N=258|
|OFF_SESSION|58.82% [47.0588, 72.5490] N=51|
|RANGE|49.81% [48.1663, 51.4984] N=3437|
|BULL_TREND|47.39% [41.0049, 53.5948] N=306|
|BEAR_TREND|57.38% [48.3607, 65.5738] N=122|
|LOW_VOLATILITY|50.50% [48.1461, 52.6615] N=2105|
|HIGH_VOLATILITY|49.01% [46.7476, 51.2436] N=1771|

Horizon/divergence detail: {"5": {"events": 3853, "probability": 0.49779392681027773, "ci_low": 0.48104723592006227, "ci_high": 0.5138852841941345, "mean_signed_return": 3.9104090313202314e-05, "divergence": {"events": 329, "probability": 0.5075987841945289, "ci_low": 0.45592705167173253, "ci_high": 0.5531914893617021, "mean_signed_return": 3.548098519834016e-05}}, "10": {"events": 3417, "probability": 0.48053848405033656, "ci_low": 0.4634108867427568, "ci_high": 0.4964954638571847, "mean_signed_return": 3.459188986288697e-06, "divergence": {"events": 323, "probability": 0.49226006191950467, "ci_low": 0.43962848297213625, "ci_high": 0.5386996904024768, "mean_signed_return": 2.0098831501130526e-05}}, "15": {"events": 3110, "probability": 0.4813504823151125, "ci_low": 0.46527331189710613, "ci_high": 0.49903536977491963, "mean_signed_return": 1.64446004093595e-05, "divergence": {"events": 318, "probability": 0.5377358490566038, "ci_low": 0.48427672955974843, "ci_high": 0.5880503144654088, "mean_signed_return": 2.6793507182588485e-06}}, "30": {"events": 2475, "probability": 0.4860606060606061, "ci_low": 0.4684747474747475, "ci_high": 0.5066666666666667, "mean_signed_return": 1.3279304444501706e-06, "divergence": {"events": 303, "probability": 0.5247524752475248, "ci_low": 0.4752475247524752, "ci_high": 0.5775577557755776, "mean_signed_return": 2.921702865128849e-05}}, "60": {"events": 1885, "probability": 0.47851458885941645, "ci_low": 0.45517241379310347, "ci_high": 0.5021352785145888, "mean_signed_return": -5.429950247621033e-05, "divergence": {"events": 284, "probability": 0.5070422535211268, "ci_low": 0.45422535211267606, "ci_high": 0.5563380281690141, "mean_signed_return": -0.00010874227240348188}}}

### SPX → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [5, 5, 5, 5, 15, 45, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 45]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.33% [43.4447, 52.4422] N=389|
|LONDON|49.60% [46.5761, 52.5765] N=1242|
|LONDON_NEW_YORK_OVERLAP|47.65% [45.2169, 49.8515] N=1683|
|NEW_YORK|50.19% [46.2548, 53.8065] N=775|
|OFF_SESSION|54.24% [38.9831, 67.7966] N=59|
|RANGE|48.75% [47.2222, 50.3611] N=3600|
|BULL_TREND|51.89% [46.9710, 56.5554] N=397|
|BEAR_TREND|50.00% [43.3333, 57.6833] N=150|
|LOW_VOLATILITY|49.70% [47.3856, 51.8578] N=1857|
|HIGH_VOLATILITY|48.17% [46.4493, 50.5226] N=2296|

Horizon/divergence detail: {"5": {"events": 4133, "probability": 0.48923300266150493, "ci_low": 0.4741047665134285, "ci_high": 0.5062968787805467, "mean_signed_return": -9.380370155677792e-06, "divergence": {"events": 2064, "probability": 0.4806201550387597, "ci_low": 0.46027131782945735, "ci_high": 0.5033914728682171, "mean_signed_return": -3.572016469321242e-05}}, "10": {"events": 3663, "probability": 0.49385749385749383, "ci_low": 0.4776071526071526, "ci_high": 0.5092888342888343, "mean_signed_return": -1.5851059709274818e-05, "divergence": {"events": 1938, "probability": 0.49277605779153766, "ci_low": 0.4698013415892673, "ci_high": 0.5149638802889577, "mean_signed_return": -2.244236945961764e-05}}, "15": {"events": 3279, "probability": 0.5080817322354376, "ci_low": 0.4906983836535529, "ci_high": 0.5273101555352241, "mean_signed_return": -1.7483826040050206e-05, "divergence": {"events": 1815, "probability": 0.5201101928374655, "ci_low": 0.4944765840220386, "ci_high": 0.5415977961432507, "mean_signed_return": -3.0119134414348227e-05}}, "30": {"events": 2598, "probability": 0.50846805234796, "ci_low": 0.48902040030792915, "ci_high": 0.529455350269438, "mean_signed_return": -1.1391351892059372e-05, "divergence": {"events": 1568, "probability": 0.5102040816326531, "ci_low": 0.4846938775510204, "ci_high": 0.5309470663265307, "mean_signed_return": -5.709092409310901e-05}}, "60": {"events": 1918, "probability": 0.4848800834202294, "ci_low": 0.46558915537017725, "ci_high": 0.50757299270073, "mean_signed_return": -8.666420601100613e-06, "divergence": {"events": 1269, "probability": 0.4925137903861308, "ci_low": 0.46373128447596534, "ci_high": 0.5177304964539007, "mean_signed_return": -6.851904924142422e-05}}}

### DXY → EURUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, DXY_EURUSD_STRUCTURAL_DEPENDENCE_REQUIRES_INDEPENDENT_CONFIRMATION, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 30, 25, 25, 25, 25, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 30]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|51.80% [47.7707, 56.2633] N=471|
|LONDON|46.89% [44.1386, 49.7452] N=981|
|LONDON_NEW_YORK_OVERLAP|46.83% [43.8914, 50.1725] N=884|
|NEW_YORK|54.00% [48.4000, 60.0000] N=250|
|OFF_SESSION|30.00% [N/A, N/A] N=10|
|RANGE|48.93% [47.0366, 50.9279] N=2379|
|BULL_TREND|43.44% [34.4262, 51.6393] N=122|
|BEAR_TREND|49.46% [41.3710, 59.1398] N=93|
|LOW_VOLATILITY|48.49% [45.8843, 51.1430] N=1227|
|HIGH_VOLATILITY|48.97% [46.3683, 51.4253] N=1405|

Horizon/divergence detail: {"5": {"events": 3106, "probability": 0.4816484224082421, "ci_low": 0.4653815196394076, "ci_high": 0.49984707018673535, "mean_signed_return": -7.554560409759495e-06, "divergence": {"events": 8, "probability": 0.5, "ci_low": null, "ci_high": null, "mean_signed_return": -0.0007316408460159709}}, "10": {"events": 2796, "probability": 0.47138769670958514, "ci_low": 0.4534871244635193, "ci_high": 0.4892703862660944, "mean_signed_return": -7.00758571322605e-06, "divergence": {"events": 8, "probability": 0.75, "ci_low": null, "ci_high": null, "mean_signed_return": -0.00024592685819021615}}, "15": {"events": 2576, "probability": 0.48641304347826086, "ci_low": 0.4658385093167702, "ci_high": 0.5054347826086957, "mean_signed_return": -1.2562776397197482e-05, "divergence": {"events": 8, "probability": 0.625, "ci_low": null, "ci_high": null, "mean_signed_return": -0.0004314010846293827}}, "30": {"events": 2099, "probability": 0.4878513577894235, "ci_low": 0.46736541210100047, "ci_high": 0.508587422582182, "mean_signed_return": 4.025731070202033e-06, "divergence": {"events": 8, "probability": 0.75, "ci_low": null, "ci_high": null, "mean_signed_return": -0.0007573928024634205}}, "60": {"events": 1581, "probability": 0.47881087919038584, "ci_low": 0.4560404807084124, "ci_high": 0.5035104364326376, "mean_signed_return": -2.2125056065374435e-06, "divergence": {"events": 8, "probability": 0.375, "ci_low": null, "ci_high": null, "mean_signed_return": -0.0012266016969132653}}}

### GBPUSD → EURUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [15, 20, 20, 20, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 20]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|47.68% [44.4694, 51.0365] N=1013|
|LONDON|50.03% [47.5722, 52.5538] N=1627|
|LONDON_NEW_YORK_OVERLAP|48.02% [44.6485, 51.3911] N=1010|
|NEW_YORK|52.16% [46.6667, 58.0392] N=255|
|OFF_SESSION|47.25% [38.4615, 56.0440] N=91|
|RANGE|48.82% [47.1725, 50.4628] N=3679|
|BULL_TREND|51.67% [43.8889, 58.8889] N=180|
|BEAR_TREND|48.57% [38.5714, 57.8571] N=140|
|LOW_VOLATILITY|49.26% [47.4989, 51.3043] N=2300|
|HIGH_VOLATILITY|48.24% [45.6367, 50.4098] N=1708|

Horizon/divergence detail: {"5": {"events": 3988, "probability": 0.4889669007021063, "ci_low": 0.4742916248746239, "ci_high": 0.503892928786359, "mean_signed_return": -4.260548370790183e-06, "divergence": {"events": 178, "probability": 0.5224719101123596, "ci_low": 0.449438202247191, "ci_high": 0.5955056179775281, "mean_signed_return": -1.4551688225217864e-05}}, "10": {"events": 3583, "probability": 0.47362545353056096, "ci_low": 0.45660061401060564, "ci_high": 0.4907968183086799, "mean_signed_return": -1.0646403868479645e-05, "divergence": {"events": 175, "probability": 0.46285714285714286, "ci_low": 0.38285714285714284, "ci_high": 0.5344285714285714, "mean_signed_return": -2.625341652144079e-05}}, "15": {"events": 3264, "probability": 0.4849877450980392, "ci_low": 0.4681372549019608, "ci_high": 0.5024816176470588, "mean_signed_return": -1.559355309437588e-05, "divergence": {"events": 171, "probability": 0.45614035087719296, "ci_low": 0.38596491228070173, "ci_high": 0.5235380116959063, "mean_signed_return": 4.245602141592508e-06}}, "30": {"events": 2633, "probability": 0.4781617926319787, "ci_low": 0.4602924420812761, "ci_high": 0.49639194834789213, "mean_signed_return": -4.197262222139989e-05, "divergence": {"events": 169, "probability": 0.47928994082840237, "ci_low": 0.4260355029585799, "ci_high": 0.5384615384615384, "mean_signed_return": -6.491002082258016e-05}}, "60": {"events": 1930, "probability": 0.4689119170984456, "ci_low": 0.4458419689119171, "ci_high": 0.49015544041450776, "mean_signed_return": -6.0534159225287184e-05, "divergence": {"events": 154, "probability": 0.5, "ci_low": 0.44155844155844154, "ci_high": 0.5584415584415584, "mean_signed_return": -8.296574626396806e-05}}}

### USDCHF → EURUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [90, 90, 90, 90, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.01% [45.5630, 52.5088] N=857|
|LONDON|51.75% [49.3499, 54.2044] N=1546|
|LONDON_NEW_YORK_OVERLAP|48.10% [45.3487, 50.7629] N=1183|
|NEW_YORK|49.59% [43.4959, 55.2846] N=246|
|OFF_SESSION|47.67% [40.4145, 54.4041] N=193|
|RANGE|49.39% [47.8178, 50.8539] N=3689|
|BULL_TREND|55.22% [48.7562, 61.6915] N=201|
|BEAR_TREND|50.37% [41.4815, 59.6481] N=135|
|LOW_VOLATILITY|50.69% [48.7282, 52.8570] N=2241|
|HIGH_VOLATILITY|48.50% [45.9911, 50.8087] N=1796|

Horizon/divergence detail: {"5": {"events": 4017, "probability": 0.49738610903659447, "ci_low": 0.48094349016679117, "ci_high": 0.5135673388100572, "mean_signed_return": 3.1032848487370314e-06, "divergence": {"events": 285, "probability": 0.5578947368421052, "ci_low": 0.5017543859649123, "ci_high": 0.6140350877192983, "mean_signed_return": 1.7693590345743225e-05}}, "10": {"events": 3596, "probability": 0.4924916573971079, "ci_low": 0.4771968854282536, "ci_high": 0.508912680756396, "mean_signed_return": 6.3902375688811e-06, "divergence": {"events": 273, "probability": 0.5604395604395604, "ci_low": 0.5072344322344322, "ci_high": 0.608058608058608, "mean_signed_return": 3.571188450175337e-05}}, "15": {"events": 3265, "probability": 0.5022970903522205, "ci_low": 0.485145482388974, "ci_high": 0.5196094946401225, "mean_signed_return": -6.098667567871933e-07, "divergence": {"events": 256, "probability": 0.57421875, "ci_low": 0.51953125, "ci_high": 0.62890625, "mean_signed_return": 4.447289463357918e-05}}, "30": {"events": 2607, "probability": 0.4902186421173763, "ci_low": 0.4700709627924818, "ci_high": 0.5101649405446874, "mean_signed_return": 2.357126484133863e-06, "divergence": {"events": 230, "probability": 0.5173913043478261, "ci_low": 0.4542391304347826, "ci_high": 0.5805434782608695, "mean_signed_return": 4.446228617890088e-05}}, "60": {"events": 1907, "probability": 0.502884111169376, "ci_low": 0.4792606187729418, "ci_high": 0.5259832197168327, "mean_signed_return": 3.456060509675551e-05, "divergence": {"events": 207, "probability": 0.5265700483091788, "ci_low": 0.4564009661835749, "ci_high": 0.6015700483091786, "mean_signed_return": 7.267569887157799e-05}}}

### EURGBP → EURUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [15, 20, 20, 20, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 20]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.26% [46.5608, 53.7037] N=756|
|LONDON|49.16% [47.0094, 51.4717] N=1906|
|LONDON_NEW_YORK_OVERLAP|53.76% [50.5613, 56.4907] N=971|
|NEW_YORK|50.47% [44.8598, 55.8528] N=214|
|OFF_SESSION|42.65% [35.2941, 49.5098] N=204|
|RANGE|50.14% [48.6216, 51.6216] N=3700|
|BULL_TREND|51.50% [46.0000, 56.7625] N=200|
|BEAR_TREND|50.68% [40.7363, 60.9589] N=146|
|LOW_VOLATILITY|49.83% [47.6552, 51.9246] N=2368|
|HIGH_VOLATILITY|50.53% [47.9828, 52.7844] N=1688|

Horizon/divergence detail: {"5": {"events": 4039, "probability": 0.5016093092349592, "ci_low": 0.4877321119088883, "ci_high": 0.5159692993315177, "mean_signed_return": 4.152220853639238e-06, "divergence": {"events": 3049, "probability": 0.5037717284355526, "ci_low": 0.48588881600524764, "ci_high": 0.5223105936372581, "mean_signed_return": 5.609211466465976e-06}}, "10": {"events": 3588, "probability": 0.49052396878483834, "ci_low": 0.4721293199554069, "ci_high": 0.5069676700111483, "mean_signed_return": 7.972761133436598e-06, "divergence": {"events": 2762, "probability": 0.501810282404055, "ci_low": 0.4822592324402607, "ci_high": 0.5203113685734975, "mean_signed_return": 1.8894363065083506e-05}}, "15": {"events": 3239, "probability": 0.49521457239888855, "ci_low": 0.47591077493053413, "ci_high": 0.5109601728928682, "mean_signed_return": 1.790125051464235e-05, "divergence": {"events": 2561, "probability": 0.5052713783678251, "ci_low": 0.4847618117922687, "ci_high": 0.523438110113237, "mean_signed_return": 2.8541885258542022e-05}}, "30": {"events": 2550, "probability": 0.5031372549019608, "ci_low": 0.48214705882352943, "ci_high": 0.5227450980392156, "mean_signed_return": 2.7911164964455833e-05, "divergence": {"events": 2079, "probability": 0.5165945165945166, "ci_low": 0.4946969696969697, "ci_high": 0.5365680615680616, "mean_signed_return": 4.337276993733709e-05}}, "60": {"events": 1845, "probability": 0.5121951219512195, "ci_low": 0.4913143631436314, "ci_high": 0.5365853658536586, "mean_signed_return": 2.8365108810349223e-05, "divergence": {"events": 1565, "probability": 0.5028753993610223, "ci_low": 0.4776198083067093, "ci_high": 0.5262140575079872, "mean_signed_return": -9.347298167681023e-08}}}

### USDJPY → EURUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [5, 5, 5, 5, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 5]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.43% [46.6870, 52.2468] N=1313|
|LONDON|51.78% [48.3503, 55.3299] N=788|
|LONDON_NEW_YORK_OVERLAP|49.31% [46.1489, 52.6627] N=1014|
|NEW_YORK|50.36% [45.2899, 55.4348] N=276|
|OFF_SESSION|48.24% [40.0000, 56.1912] N=170|
|RANGE|50.03% [48.3547, 51.7660] N=3314|
|BULL_TREND|44.30% [36.3766, 53.1646] N=158|
|BEAR_TREND|53.85% [43.9560, 62.6374] N=91|
|LOW_VOLATILITY|50.16% [48.0489, 52.1638] N=2127|
|HIGH_VOLATILITY|49.62% [46.9778, 52.1895] N=1441|

Horizon/divergence detail: {"5": {"events": 3558, "probability": 0.4985947161326588, "ci_low": 0.4818507588532884, "ci_high": 0.5170109612141653, "mean_signed_return": 9.685184977865307e-06, "divergence": {"events": 545, "probability": 0.5247706422018349, "ci_low": 0.48440366972477067, "ci_high": 0.5669724770642202, "mean_signed_return": 3.083414929927564e-05}}, "10": {"events": 3197, "probability": 0.4782608695652174, "ci_low": 0.46151861119799814, "ci_high": 0.49406474820143886, "mean_signed_return": -2.676117993139026e-08, "divergence": {"events": 521, "probability": 0.4971209213051823, "ci_low": 0.45489443378119004, "ci_high": 0.5422744721689059, "mean_signed_return": 1.0608685286745055e-05}}, "15": {"events": 2925, "probability": 0.5107692307692308, "ci_low": 0.4934957264957265, "ci_high": 0.528042735042735, "mean_signed_return": 2.1741589318881516e-05, "divergence": {"events": 502, "probability": 0.5119521912350598, "ci_low": 0.4690737051792829, "ci_high": 0.5568227091633465, "mean_signed_return": 3.7878484974714785e-05}}, "30": {"events": 2432, "probability": 0.49506578947368424, "ci_low": 0.4755037006578947, "ci_high": 0.515625, "mean_signed_return": 2.8614940736132447e-05, "divergence": {"events": 469, "probability": 0.4840085287846482, "ci_low": 0.43710021321961623, "ci_high": 0.5266524520255863, "mean_signed_return": 4.747910346765367e-05}}, "60": {"events": 1835, "probability": 0.4948228882833787, "ci_low": 0.4708446866485014, "ci_high": 0.5185422343324251, "mean_signed_return": 7.881020211288743e-06, "divergence": {"events": 427, "probability": 0.5058548009367682, "ci_low": 0.46604215456674475, "ci_high": 0.5456674473067916, "mean_signed_return": 3.390985501061973e-05}}}

### SPX → EURUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 30, 90, 90, 5, 5, 5, 5], 'oos_selected_lag': 5, 'range_minutes': [5, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.10% [44.0810, 54.2416] N=389|
|LONDON|50.64% [47.6610, 53.1824] N=1242|
|LONDON_NEW_YORK_OVERLAP|47.74% [45.7245, 50.2405] N=1684|
|NEW_YORK|49.55% [46.3320, 53.1532] N=777|
|OFF_SESSION|55.17% [44.8276, 65.5172] N=58|
|RANGE|48.75% [47.2342, 50.2924] N=3762|
|BULL_TREND|52.11% [46.2324, 57.7465] N=213|
|BEAR_TREND|52.02% [43.9306, 58.3815] N=173|
|LOW_VOLATILITY|50.42% [48.0192, 52.9157] N=1666|
|HIGH_VOLATILITY|48.41% [46.1822, 50.6458] N=2489|

Horizon/divergence detail: {"5": {"events": 4135, "probability": 0.4911729141475212, "ci_low": 0.4751995163240629, "ci_high": 0.5071342200725514, "mean_signed_return": -2.354495085777773e-06, "divergence": {"events": 2091, "probability": 0.5002391200382592, "ci_low": 0.47703252032520327, "ci_high": 0.5196197991391679, "mean_signed_return": 5.194662795789438e-06}}, "10": {"events": 3665, "probability": 0.4908594815825375, "ci_low": 0.47489085948158255, "ci_high": 0.5061391541609823, "mean_signed_return": -1.2321164976059502e-05, "divergence": {"events": 1949, "probability": 0.5053873781426372, "ci_low": 0.4835684966649564, "ci_high": 0.526693175987686, "mean_signed_return": 4.198663243018845e-06}}, "15": {"events": 3276, "probability": 0.4877899877899878, "ci_low": 0.4723672161172161, "ci_high": 0.5051892551892552, "mean_signed_return": -2.1071595246442965e-05, "divergence": {"events": 1816, "probability": 0.5060572687224669, "ci_low": 0.4820897577092511, "ci_high": 0.5275330396475771, "mean_signed_return": 4.7207625417948084e-06}}, "30": {"events": 2586, "probability": 0.5015467904098995, "ci_low": 0.4839423820572312, "ci_high": 0.5204949729311679, "mean_signed_return": -6.648914067563986e-06, "divergence": {"events": 1557, "probability": 0.5028901734104047, "ci_low": 0.481053307642903, "ci_high": 0.5247270391779062, "mean_signed_return": -1.706606683119846e-05}}, "60": {"events": 1893, "probability": 0.48758584257791865, "ci_low": 0.46642894875858426, "ci_high": 0.5121632329635499, "mean_signed_return": -5.332271573841792e-05, "divergence": {"events": 1245, "probability": 0.4923694779116466, "ci_low": 0.46303212851405623, "ci_high": 0.5220883534136547, "mean_signed_return": -1.5013313883974493e-05}}}

### DXY → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 15, 15, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|45.45% [35.0649, 55.8442] N=77|
|LONDON|49.36% [41.3301, 57.0513] N=156|
|LONDON_NEW_YORK_OVERLAP|50.49% [45.3074, 55.8333] N=309|
|NEW_YORK|45.35% [38.3721, 52.0494] N=172|
|OFF_SESSION|60.00% [N/A, N/A] N=5|
|RANGE|49.00% [44.6841, 53.0046] N=649|
|BULL_TREND|45.83% [31.2500, 60.4167] N=48|
|BEAR_TREND|47.37% [N/A, N/A] N=19|
|LOW_VOLATILITY|49.57% [44.9947, 54.5798] N=470|
|HIGH_VOLATILITY|47.62% [41.2698, 53.3829] N=252|

Horizon/divergence detail: {"15": {"events": 714, "probability": 0.48599439775910364, "ci_low": 0.4495798319327731, "ci_high": 0.5210084033613446, "mean_signed_return": -3.100155046468595e-05, "divergence": {"events": 203, "probability": 0.49261083743842365, "ci_low": 0.4236453201970443, "ci_high": 0.5665024630541872, "mean_signed_return": -7.29615609602572e-05}}, "30": {"events": 649, "probability": 0.5084745762711864, "ci_low": 0.4699537750385208, "ci_high": 0.5439137134052389, "mean_signed_return": 2.3138192287164155e-05, "divergence": {"events": 194, "probability": 0.4329896907216495, "ci_low": 0.36597938144329895, "ci_high": 0.5, "mean_signed_return": -0.00013710228188489412}}, "60": {"events": 568, "probability": 0.5088028169014085, "ci_low": 0.47183098591549294, "ci_high": 0.5563380281690141, "mean_signed_return": 7.668808722255586e-06, "divergence": {"events": 186, "probability": 0.4946236559139785, "ci_low": 0.41935483870967744, "ci_high": 0.5591397849462365, "mean_signed_return": -0.00011746256285720302}}}

### EURUSD → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [90, 90, 90, 60, 60, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|45.37% [37.9630, 52.7778] N=108|
|LONDON|46.01% [40.3042, 52.8517] N=263|
|LONDON_NEW_YORK_OVERLAP|49.89% [44.9664, 54.7036] N=447|
|NEW_YORK|41.82% [34.5455, 49.0909] N=220|
|OFF_SESSION|39.13% [26.0870, 52.1739] N=23|
|RANGE|46.70% [43.6649, 50.1571] N=955|
|BULL_TREND|43.42% [31.5789, 55.2632] N=76|
|BEAR_TREND|45.83% [25.0000, 62.5000] N=24|
|LOW_VOLATILITY|46.80% [42.9631, 50.6302] N=718|
|HIGH_VOLATILITY|46.18% [40.0000, 52.0588] N=340|

Horizon/divergence detail: {"15": {"events": 1051, "probability": 0.4643196955280685, "ci_low": 0.43387250237868696, "ci_high": 0.4938154138915319, "mean_signed_return": -7.967796601085871e-05, "divergence": {"events": 338, "probability": 0.45857988165680474, "ci_low": 0.40673076923076923, "ci_high": 0.5059171597633136, "mean_signed_return": -0.00014775354180423752}}, "30": {"events": 939, "probability": 0.48136315228966986, "ci_low": 0.45260915867944623, "ci_high": 0.5085463258785943, "mean_signed_return": 7.477706797892668e-06, "divergence": {"events": 319, "probability": 0.45768025078369906, "ci_low": 0.4106583072100313, "ci_high": 0.5078369905956113, "mean_signed_return": -0.00011725492079672802}}, "60": {"events": 814, "probability": 0.48894348894348894, "ci_low": 0.45881449631449633, "ci_high": 0.5178439803439803, "mean_signed_return": -1.3097725017248273e-05, "divergence": {"events": 302, "probability": 0.5165562913907285, "ci_low": 0.4519039735099338, "ci_high": 0.5794701986754967, "mean_signed_return": -0.00010087301678785387}}}

### USDJPY → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 15, 15, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|46.64% [40.9396, 52.3490] N=298|
|LONDON|51.52% [44.1793, 58.3460] N=198|
|LONDON_NEW_YORK_OVERLAP|50.87% [45.3757, 56.2211] N=346|
|NEW_YORK|45.71% [37.8571, 54.2857] N=140|
|OFF_SESSION|50.00% [33.3333, 66.6667] N=24|
|RANGE|49.63% [46.4400, 52.6594] N=941|
|BULL_TREND|37.50% [29.1667, 45.8333] N=48|
|BEAR_TREND|50.00% [N/A, N/A] N=14|
|LOW_VOLATILITY|50.39% [47.2585, 53.2637] N=766|
|HIGH_VOLATILITY|44.72% [37.8049, 51.6260] N=246|

Horizon/divergence detail: {"15": {"events": 1002, "probability": 0.49001996007984033, "ci_low": 0.4600798403193613, "ci_high": 0.5184880239520958, "mean_signed_return": -1.512470292258328e-05, "divergence": {"events": 342, "probability": 0.4853801169590643, "ci_low": 0.4444444444444444, "ci_high": 0.5263157894736842, "mean_signed_return": -3.3577373853184644e-05}}, "30": {"events": 910, "probability": 0.46153846153846156, "ci_low": 0.432967032967033, "ci_high": 0.49340659340659343, "mean_signed_return": -2.5088509017561954e-05, "divergence": {"events": 327, "probability": 0.46788990825688076, "ci_low": 0.41429663608562695, "ci_high": 0.5214831804281345, "mean_signed_return": -4.91951337268103e-05}}, "60": {"events": 794, "probability": 0.5050377833753149, "ci_low": 0.4691120906801008, "ci_high": 0.5371851385390428, "mean_signed_return": 2.2273918094153604e-05, "divergence": {"events": 309, "probability": 0.4854368932038835, "ci_low": 0.4336569579288026, "ci_high": 0.540453074433657, "mean_signed_return": -8.661635891835391e-05}}}

### GBPUSD → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [90, 90, 90, 90, 60, 60, 60, 60], 'oos_selected_lag': 60, 'range_minutes': [60, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.78% [37.8049, 59.7561] N=82|
|LONDON|53.36% [47.4790, 59.4643] N=238|
|LONDON_NEW_YORK_OVERLAP|50.43% [44.4444, 56.2749] N=351|
|NEW_YORK|56.41% [50.0000, 63.1571] N=156|
|OFF_SESSION|62.50% [N/A, N/A] N=8|
|RANGE|52.43% [48.5135, 56.2872] N=740|
|BULL_TREND|50.82% [39.3443, 62.2951] N=61|
|BEAR_TREND|62.50% [N/A, N/A] N=16|
|LOW_VOLATILITY|51.37% [47.0790, 56.1040] N=582|
|HIGH_VOLATILITY|53.06% [46.9388, 59.1837] N=245|

Horizon/divergence detail: {"15": {"events": 1066, "probability": 0.524390243902439, "ci_low": 0.49575515947467164, "ci_high": 0.5535178236397749, "mean_signed_return": 7.31534368609333e-05, "divergence": {"events": 792, "probability": 0.5214646464646465, "ci_low": 0.4930239898989899, "ci_high": 0.5562184343434343, "mean_signed_return": 8.536558671581958e-05}}, "30": {"events": 953, "probability": 0.5246589716684156, "ci_low": 0.49367785939139563, "ci_high": 0.559286463798531, "mean_signed_return": 2.7788199618082788e-05, "divergence": {"events": 715, "probability": 0.5174825174825175, "ci_low": 0.4845804195804196, "ci_high": 0.5503846153846154, "mean_signed_return": 1.1617161632307911e-05}}, "60": {"events": 811, "probability": 0.5228113440197287, "ci_low": 0.48581997533908755, "ci_high": 0.5573366214549939, "mean_signed_return": 0.00017900400285976854, "divergence": {"events": 635, "probability": 0.5149606299212598, "ci_low": 0.4755905511811024, "ci_high": 0.5567322834645669, "mean_signed_return": 7.366924391343866e-05}}}

### USDCHF → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [90, 90, 90, 15, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|43.88% [35.7143, 52.0408] N=98|
|LONDON|53.53% [47.9554, 58.3643] N=269|
|LONDON_NEW_YORK_OVERLAP|51.78% [46.9602, 56.3941] N=477|
|NEW_YORK|49.74% [42.8077, 56.9231] N=195|
|OFF_SESSION|55.00% [40.0000, 70.0000] N=20|
|RANGE|50.83% [47.6091, 53.7422] N=962|
|BULL_TREND|48.53% [32.3529, 61.7647] N=68|
|BEAR_TREND|69.23% [53.8462, 84.6154] N=26|
|LOW_VOLATILITY|50.42% [46.9274, 53.8443] N=716|
|HIGH_VOLATILITY|51.72% [45.9626, 58.0460] N=348|

Horizon/divergence detail: {"15": {"events": 1054, "probability": 0.5104364326375711, "ci_low": 0.48242409867172675, "ci_high": 0.5412950664136622, "mean_signed_return": -3.060036493577765e-06, "divergence": {"events": 360, "probability": 0.5222222222222223, "ci_low": 0.4722222222222222, "ci_high": 0.575, "mean_signed_return": 3.6749632980977376e-05}}, "30": {"events": 946, "probability": 0.49682875264270615, "ci_low": 0.46723044397463004, "ci_high": 0.5269820295983086, "mean_signed_return": 2.48655357278618e-05, "divergence": {"events": 343, "probability": 0.43731778425655976, "ci_low": 0.3862244897959184, "ci_high": 0.48104956268221577, "mean_signed_return": -7.192249697746742e-05}}, "60": {"events": 806, "probability": 0.533498759305211, "ci_low": 0.5, "ci_high": 0.5669975186104218, "mean_signed_return": 0.00014051297486133188, "divergence": {"events": 314, "probability": 0.5159235668789809, "ci_low": 0.46011146496815286, "ci_high": 0.5781050955414012, "mean_signed_return": -0.00010811221231327284}}}

### XAGUSD → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [45, 45, 45, 45, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 45]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.74% [42.5641, 57.4359] N=195|
|LONDON|54.64% [49.2139, 60.5799] N=194|
|LONDON_NEW_YORK_OVERLAP|46.83% [43.0556, 50.9921] N=504|
|NEW_YORK|48.84% [40.9738, 55.2326] N=172|
|OFF_SESSION|43.75% [N/A, N/A] N=16|
|RANGE|49.38% [46.5768, 52.0747] N=964|
|BULL_TREND|48.28% [40.2299, 57.4713] N=87|
|BEAR_TREND|46.15% [32.5962, 61.5385] N=26|
|LOW_VOLATILITY|51.46% [47.6982, 55.3547] N=719|
|HIGH_VOLATILITY|44.59% [39.4595, 49.4595] N=370|

Horizon/divergence detail: {"15": {"events": 1075, "probability": 0.49116279069767443, "ci_low": 0.4669767441860465, "ci_high": 0.5186279069767442, "mean_signed_return": -1.3116698572160763e-05, "divergence": {"events": 78, "probability": 0.5769230769230769, "ci_low": 0.5, "ci_high": 0.6666666666666666, "mean_signed_return": 6.783545961084932e-05}}, "30": {"events": 956, "probability": 0.497907949790795, "ci_low": 0.46702405857740587, "ci_high": 0.5298378661087866, "mean_signed_return": 5.877803931179039e-05, "divergence": {"events": 78, "probability": 0.5769230769230769, "ci_low": 0.47435897435897434, "ci_high": 0.6923076923076923, "mean_signed_return": 0.00033407592803401983}}, "60": {"events": 803, "probability": 0.5155666251556662, "ci_low": 0.48194271481942713, "ci_high": 0.5510896637608966, "mean_signed_return": 3.0371060502236045e-05, "divergence": {"events": 74, "probability": 0.5540540540540541, "ci_low": 0.44594594594594594, "ci_high": 0.6486486486486487, "mean_signed_return": 4.773709725763309e-05}}}

### SPX → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 60, 15, 60, 60, 60, 60], 'oos_selected_lag': 60, 'range_minutes': [15, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|41.46% [31.7073, 51.2195] N=41|
|LONDON|53.12% [43.7500, 64.0625] N=64|
|LONDON_NEW_YORK_OVERLAP|49.84% [43.7700, 55.4393] N=313|
|NEW_YORK|51.23% [46.0123, 57.0552] N=326|
|OFF_SESSION|62.22% [48.8889, 77.7778] N=45|
|RANGE|51.06% [47.0417, 55.6061] N=660|
|BULL_TREND|48.68% [36.8421, 61.2171] N=76|
|BEAR_TREND|37.50% [20.8333, 50.0000] N=24|
|LOW_VOLATILITY|50.61% [45.9459, 55.7740] N=407|
|HIGH_VOLATILITY|50.82% [46.2843, 55.7692] N=364|

Horizon/divergence detail: {"15": {"events": 1054, "probability": 0.4819734345351044, "ci_low": 0.452561669829222, "ci_high": 0.5104364326375711, "mean_signed_return": -1.649012130109169e-05, "divergence": {"events": 664, "probability": 0.48042168674698793, "ci_low": 0.44047439759036144, "ci_high": 0.5188629518072289, "mean_signed_return": -3.9522529663605604e-05}}, "30": {"events": 929, "probability": 0.5026910656620022, "ci_low": 0.4714747039827772, "ci_high": 0.5344725511302475, "mean_signed_return": 2.892638702369946e-05, "divergence": {"events": 608, "probability": 0.5049342105263158, "ci_low": 0.46710526315789475, "ci_high": 0.5444078947368421, "mean_signed_return": -7.518117663006075e-05}}, "60": {"events": 752, "probability": 0.5039893617021277, "ci_low": 0.4633976063829787, "ci_high": 0.543251329787234, "mean_signed_return": -0.00017820027160069852, "divergence": {"events": 508, "probability": 0.5216535433070866, "ci_low": 0.4773129921259842, "ci_high": 0.5640255905511811, "mean_signed_return": -0.00016992053292707183}}}

### DXY → EURUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, DXY_EURUSD_STRUCTURAL_DEPENDENCE_REQUIRES_INDEPENDENT_CONFIRMATION, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 30, 60, 60, 60, 60, 60, 60], 'oos_selected_lag': 60, 'range_minutes': [30, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.72% [40.5797, 62.3188] N=69|
|LONDON|46.62% [38.3459, 54.8872] N=133|
|LONDON_NEW_YORK_OVERLAP|50.42% [45.3390, 56.3559] N=236|
|NEW_YORK|59.44% [48.9510, 69.9301] N=143|
|OFF_SESSION|100.00% [N/A, N/A] N=3|
|RANGE|52.50% [48.4230, 56.7718] N=539|
|BEAR_TREND|61.54% [N/A, N/A] N=13|
|BULL_TREND|54.55% [45.4545, 68.1818] N=22|
|LOW_VOLATILITY|52.40% [47.9507, 57.2115] N=416|
|HIGH_VOLATILITY|51.81% [43.9759, 60.2410] N=166|

Horizon/divergence detail: {"15": {"events": 715, "probability": 0.5314685314685315, "ci_low": 0.49083916083916085, "ci_high": 0.5720279720279721, "mean_signed_return": 4.8532552015510656e-05, "divergence": {"events": 714, "probability": 0.5322128851540616, "ci_low": 0.49019607843137253, "ci_high": 0.5742296918767507, "mean_signed_return": 3.729710568895764e-05}}, "30": {"events": 650, "probability": 0.5153846153846153, "ci_low": 0.47765384615384615, "ci_high": 0.5592692307692307, "mean_signed_return": 4.4048729914146115e-05, "divergence": {"events": 649, "probability": 0.514637904468413, "ci_low": 0.4776579352850539, "ci_high": 0.5563174114021571, "mean_signed_return": 3.3757933658785446e-05}}, "60": {"events": 568, "probability": 0.5246478873239436, "ci_low": 0.4867517605633803, "ci_high": 0.562544014084507, "mean_signed_return": 6.547481196758409e-05, "divergence": {"events": 568, "probability": 0.5246478873239436, "ci_low": 0.4867517605633803, "ci_high": 0.562544014084507, "mean_signed_return": 6.124480698729659e-05}}}

### GBPUSD → EURUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [90, 90, 15, 15, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|41.76% [29.6703, 53.8462] N=91|
|LONDON|46.00% [41.3167, 50.6667] N=300|
|LONDON_NEW_YORK_OVERLAP|48.29% [43.9049, 52.7778] N=468|
|NEW_YORK|51.23% [45.3202, 58.6207] N=203|
|OFF_SESSION|30.77% [N/A, N/A] N=13|
|RANGE|47.53% [44.4255, 50.4980] N=1014|
|BEAR_TREND|43.48% [17.3913, 65.2174] N=23|
|BULL_TREND|50.00% [32.3529, 64.7059] N=34|
|LOW_VOLATILITY|47.52% [44.1212, 51.0939] N=825|
|HIGH_VOLATILITY|48.00% [42.8000, 52.8000] N=250|

Horizon/divergence detail: {"15": {"events": 1070, "probability": 0.47570093457943924, "ci_low": 0.44485981308411215, "ci_high": 0.5046728971962616, "mean_signed_return": -3.1182053813846656e-05, "divergence": {"events": 41, "probability": 0.4878048780487805, "ci_low": 0.34146341463414637, "ci_high": 0.6341463414634146, "mean_signed_return": -2.9489226280396525e-05}}, "30": {"events": 956, "probability": 0.47175732217573224, "ci_low": 0.43564330543933055, "ci_high": 0.5068253138075314, "mean_signed_return": -4.0460611690008604e-05, "divergence": {"events": 41, "probability": 0.4146341463414634, "ci_low": 0.3286585365853659, "ci_high": 0.4878048780487805, "mean_signed_return": 1.5860423137972557e-05}}, "60": {"events": 812, "probability": 0.47783251231527096, "ci_low": 0.4414716748768473, "ci_high": 0.5136083743842365, "mean_signed_return": -4.358730632236024e-05, "divergence": {"events": 39, "probability": 0.5128205128205128, "ci_low": 0.38461538461538464, "ci_high": 0.6666666666666666, "mean_signed_return": -0.00013632440145003115}}}

### USDCHF → EURUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 30, 30, 30, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 30]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|40.82% [31.6327, 49.5153] N=98|
|LONDON|47.78% [41.4815, 54.8148] N=270|
|LONDON_NEW_YORK_OVERLAP|45.19% [41.0042, 49.7908] N=478|
|NEW_YORK|49.49% [41.3265, 57.6531] N=196|
|OFF_SESSION|41.38% [20.6897, 62.0690] N=29|
|RANGE|45.92% [42.7764, 49.1559] N=1004|
|BEAR_TREND|37.50% [N/A, N/A] N=16|
|BULL_TREND|50.00% [36.9565, 60.8696] N=46|
|LOW_VOLATILITY|46.18% [42.6667, 49.7606] N=825|
|HIGH_VOLATILITY|47.15% [40.2439, 52.6524] N=246|

Horizon/divergence detail: {"15": {"events": 1066, "probability": 0.4596622889305816, "ci_low": 0.4268292682926829, "ci_high": 0.4896810506566604, "mean_signed_return": -4.737755745946222e-05, "divergence": {"events": 46, "probability": 0.5434782608695652, "ci_low": 0.41304347826086957, "ci_high": 0.6635869565217386, "mean_signed_return": -1.707976925824657e-05}}, "30": {"events": 956, "probability": 0.46338912133891214, "ci_low": 0.4314592050209205, "ci_high": 0.4989539748953975, "mean_signed_return": -4.869069897474655e-05, "divergence": {"events": 46, "probability": 0.5, "ci_low": 0.391304347826087, "ci_high": 0.6086956521739131, "mean_signed_return": -6.148392745236234e-06}}, "60": {"events": 810, "probability": 0.48518518518518516, "ci_low": 0.45185185185185184, "ci_high": 0.5209876543209877, "mean_signed_return": -3.0693580794797705e-05, "divergence": {"events": 45, "probability": 0.5777777777777777, "ci_low": 0.4888888888888889, "ci_high": 0.6666666666666666, "mean_signed_return": 0.0002951877001063101}}}

### EURGBP → EURUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [90, 90, 15, 15, 15, 15, 15, 15], 'oos_selected_lag': 15, 'range_minutes': [15, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|43.06% [29.1667, 56.9444] N=72|
|LONDON|50.69% [45.9834, 55.9557] N=361|
|LONDON_NEW_YORK_OVERLAP|50.52% [46.4897, 54.6392] N=485|
|NEW_YORK|49.36% [41.6667, 57.6923] N=156|
|OFF_SESSION|60.53% [50.0000, 71.0526] N=38|
|RANGE|50.87% [48.0769, 54.3269] N=1040|
|BEAR_TREND|42.86% [28.5714, 57.1429] N=21|
|BULL_TREND|40.43% [29.7872, 48.9362] N=47|
|LOW_VOLATILITY|51.25% [48.1179, 54.2739] N=878|
|HIGH_VOLATILITY|46.98% [40.5172, 53.6746] N=232|

Horizon/divergence detail: {"15": {"events": 1105, "probability": 0.502262443438914, "ci_low": 0.47420814479638007, "ci_high": 0.5316968325791855, "mean_signed_return": 2.2005801417235468e-05, "divergence": {"events": 833, "probability": 0.5042016806722689, "ci_low": 0.47058823529411764, "ci_high": 0.5366746698679471, "mean_signed_return": 3.268907347891055e-05}}, "30": {"events": 993, "probability": 0.5105740181268882, "ci_low": 0.4762839879154079, "ci_high": 0.5413141993957704, "mean_signed_return": 4.077857758292541e-05, "divergence": {"events": 762, "probability": 0.5223097112860893, "ci_low": 0.4921259842519685, "ci_high": 0.5551181102362205, "mean_signed_return": 8.251463067731894e-05}}, "60": {"events": 824, "probability": 0.4963592233009709, "ci_low": 0.46295509708737864, "ci_high": 0.5309769417475728, "mean_signed_return": 2.1886759578174986e-05, "divergence": {"events": 663, "probability": 0.5203619909502263, "ci_low": 0.4818627450980392, "ci_high": 0.5580693815987934, "mean_signed_return": 6.89268570278583e-05}}}

### USDJPY → EURUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 60, 60, 60, 15, 120, 120], 'oos_selected_lag': 15, 'range_minutes': [15, 120]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|46.62% [41.5541, 51.6892] N=296|
|LONDON|52.53% [45.4545, 60.3662] N=198|
|LONDON_NEW_YORK_OVERLAP|48.99% [44.6686, 53.8905] N=347|
|NEW_YORK|52.86% [43.9107, 60.0000] N=140|
|OFF_SESSION|44.44% [33.3333, 55.5556] N=27|
|RANGE|49.74% [47.1503, 52.4352] N=965|
|BEAR_TREND|46.67% [N/A, N/A] N=15|
|BULL_TREND|45.83% [29.1667, 62.5000] N=24|
|LOW_VOLATILITY|49.75% [46.9945, 52.8830] N=816|
|HIGH_VOLATILITY|50.00% [43.7500, 56.7708] N=192|

Horizon/divergence detail: {"15": {"events": 1004, "probability": 0.4960159362549801, "ci_low": 0.4681274900398406, "ci_high": 0.5258964143426295, "mean_signed_return": 9.531482399674616e-06, "divergence": {"events": 122, "probability": 0.5983606557377049, "ci_low": 0.5, "ci_high": 0.6967213114754098, "mean_signed_return": 0.00013733760186779797}}, "30": {"events": 911, "probability": 0.47091108671789245, "ci_low": 0.437403951701427, "ci_high": 0.5005488474204172, "mean_signed_return": -1.803610801637661e-07, "divergence": {"events": 117, "probability": 0.5213675213675214, "ci_low": 0.452991452991453, "ci_high": 0.5982905982905983, "mean_signed_return": 0.00013806371452030372}}, "60": {"events": 793, "probability": 0.49810844892812106, "ci_low": 0.4659205548549811, "ci_high": 0.5308953341740227, "mean_signed_return": 2.7550737603044536e-05, "divergence": {"events": 105, "probability": 0.5523809523809524, "ci_low": 0.45714285714285713, "ci_high": 0.638095238095238, "mean_signed_return": 0.0001087779452739621}}}

### SPX → EURUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 30, 15, 15, 90, 90, 90, 90], 'oos_selected_lag': 90, 'range_minutes': [15, 90]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|51.28% [35.8974, 69.2308] N=39|
|LONDON|46.77% [38.7097, 54.8387] N=62|
|LONDON_NEW_YORK_OVERLAP|47.31% [40.1434, 54.8387] N=279|
|NEW_YORK|48.36% [42.3545, 53.6455] N=275|
|OFF_SESSION|47.62% [33.3333, 64.4048] N=21|
|RANGE|47.71% [42.7844, 51.7827] N=589|
|BEAR_TREND|63.16% [N/A, N/A] N=19|
|BULL_TREND|48.00% [36.0000, 64.0000] N=25|
|LOW_VOLATILITY|46.70% [41.6856, 51.2528] N=439|
|HIGH_VOLATILITY|48.56% [42.3077, 55.7692] N=208|

Horizon/divergence detail: {"15": {"events": 1053, "probability": 0.5023741690408358, "ci_low": 0.47293447293447294, "ci_high": 0.5294634377967711, "mean_signed_return": 2.2421737363709538e-05, "divergence": {"events": 629, "probability": 0.5246422893481717, "ci_low": 0.4864864864864865, "ci_high": 0.5643879173290938, "mean_signed_return": 1.507479198778338e-05}}, "30": {"events": 921, "probability": 0.504885993485342, "ci_low": 0.47174267100977196, "ci_high": 0.5402008686210641, "mean_signed_return": 1.0108062927282007e-05, "divergence": {"events": 579, "probability": 0.5112262521588946, "ci_low": 0.47232297063903284, "ci_high": 0.542314335060449, "mean_signed_return": 1.8983953381747617e-05}}, "60": {"events": 740, "probability": 0.4972972972972973, "ci_low": 0.4608108108108108, "ci_high": 0.5351351351351351, "mean_signed_return": 2.800478058738675e-05, "divergence": {"events": 494, "probability": 0.5161943319838057, "ci_low": 0.4817813765182186, "ci_high": 0.5526315789473685, "mean_signed_return": 5.453027814899943e-05}}}

### DXY → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [13, 13, 13, 13, 13, 13, 1, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 13]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.65% [47.0257, 50.4447] N=3379|
|LONDON|50.34% [48.5858, 52.0077] N=3113|
|LONDON_NEW_YORK_OVERLAP|50.35% [48.4404, 52.0193] N=2725|
|NEW_YORK|49.35% [47.0956, 51.3491] N=1929|
|OFF_SESSION|45.05% [38.1188, 52.4752] N=202|
|RANGE|49.36% [48.4141, 50.3650] N=10152|
|BULL_TREND|50.98% [47.4201, 54.4871] N=814|
|BEAR_TREND|51.98% [47.0862, 56.6434] N=429|
|LOW_VOLATILITY|49.43% [48.0337, 50.7588] N=5143|
|HIGH_VOLATILITY|49.60% [48.4007, 50.8002] N=6317|

Horizon/divergence detail: {"5": {"events": 11311, "probability": 0.49535850057466185, "ci_low": 0.48646671381840684, "ci_high": 0.5050415524710459, "mean_signed_return": -6.962431961732544e-07, "divergence": {"events": 3897, "probability": 0.5178342314600975, "ci_low": 0.5002501924557352, "ci_high": 0.5354182704644599, "mean_signed_return": 2.2489910430797125e-05}}, "10": {"events": 9236, "probability": 0.5037895192724123, "ci_low": 0.4933791684711996, "ci_high": 0.5132660242529233, "mean_signed_return": 2.9249089492315635e-06, "divergence": {"events": 3582, "probability": 0.5153545505304299, "ci_low": 0.4978992183137912, "ci_high": 0.532823841429369, "mean_signed_return": 1.959648071800886e-05}}, "15": {"events": 7879, "probability": 0.4951135930955705, "ci_low": 0.48457926132757967, "ci_high": 0.5066156872699581, "mean_signed_return": -1.2123461926543002e-06, "divergence": {"events": 3342, "probability": 0.504787552363854, "ci_low": 0.4875748055056852, "ci_high": 0.5202049670855775, "mean_signed_return": 2.7483021035540694e-05}}, "30": {"events": 5505, "probability": 0.49627611262488647, "ci_low": 0.48273841961852865, "ci_high": 0.5101771117166213, "mean_signed_return": -2.9660651684063356e-05, "divergence": {"events": 2771, "probability": 0.5135330205701912, "ci_low": 0.4952995308552869, "ci_high": 0.534103211836882, "mean_signed_return": 3.61335401340413e-05}}, "60": {"events": 3512, "probability": 0.5028473804100227, "ci_low": 0.48658883826879273, "ci_high": 0.5192269362186789, "mean_signed_return": 1.2749147136922427e-05, "divergence": {"events": 2108, "probability": 0.5066413662239089, "ci_low": 0.48504506641366224, "ci_high": 0.5291864326375711, "mean_signed_return": 7.308533928750115e-05}}}

### EURUSD → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [19, 19, 19, 19, 1, 1, 1, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 19]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.10% [47.7199, 50.4578] N=5242|
|LONDON|49.89% [48.2159, 51.5669] N=3223|
|LONDON_NEW_YORK_OVERLAP|50.82% [48.9892, 52.5532] N=2822|
|NEW_YORK|49.62% [47.5327, 51.7363] N=1987|
|OFF_SESSION|49.83% [47.0204, 53.0899] N=907|
|RANGE|49.58% [48.6459, 50.4891] N=12706|
|BULL_TREND|52.31% [49.0824, 55.2023] N=1038|
|BEAR_TREND|50.21% [45.4545, 54.9587] N=484|
|LOW_VOLATILITY|49.63% [48.5022, 50.8074] N=6945|
|HIGH_VOLATILITY|50.03% [49.0574, 51.0176] N=7373|

Horizon/divergence detail: {"5": {"events": 14122, "probability": 0.49787565500637304, "ci_low": 0.489732332530803, "ci_high": 0.5057392720577821, "mean_signed_return": 3.9298320918093735e-06, "divergence": {"events": 5212, "probability": 0.510552570990023, "ci_low": 0.4957789716039908, "ci_high": 0.5250527628549501, "mean_signed_return": 1.1187591007193195e-05}}, "10": {"events": 11258, "probability": 0.5020429916503819, "ci_low": 0.4932026114762835, "ci_high": 0.5117338781311067, "mean_signed_return": -5.814666551732322e-07, "divergence": {"events": 4705, "probability": 0.5120085015940489, "ci_low": 0.49861849096705635, "ci_high": 0.5261583421891605, "mean_signed_return": 1.0885505695930038e-05}}, "15": {"events": 9508, "probability": 0.4923222549432057, "ci_low": 0.4817890197728229, "ci_high": 0.5024190155658393, "mean_signed_return": -1.6299824884952693e-05, "divergence": {"events": 4305, "probability": 0.5066202090592334, "ci_low": 0.4930255516840883, "ci_high": 0.5205807200929152, "mean_signed_return": 5.862057358398444e-06}}, "30": {"events": 6565, "probability": 0.4898705255140899, "ci_low": 0.4772277227722772, "ci_high": 0.5022886519421172, "mean_signed_return": -1.685965380951732e-05, "divergence": {"events": 3478, "probability": 0.5011500862564693, "ci_low": 0.4844738355376653, "ci_high": 0.5189764232317424, "mean_signed_return": 7.397949916707128e-06}}, "60": {"events": 4122, "probability": 0.502426006792819, "ci_low": 0.4861717612809316, "ci_high": 0.5178493449781659, "mean_signed_return": 2.570902260437597e-05, "divergence": {"events": 2583, "probability": 0.5164537359659311, "ci_low": 0.4968737901664731, "ci_high": 0.5369918699186992, "mean_signed_return": 5.7260158887794845e-05}}}

### USDJPY → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 13, 13, 10, 10, 10, 28], 'oos_selected_lag': 28, 'range_minutes': [10, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.85% [48.7055, 52.5891] N=2358|
|LONDON|51.38% [48.8845, 53.7746] N=1524|
|LONDON_NEW_YORK_OVERLAP|51.58% [49.0597, 54.2042] N=1332|
|NEW_YORK|48.11% [45.4875, 50.8591] N=1164|
|OFF_SESSION|48.84% [44.3002, 53.2819] N=518|
|RANGE|49.45% [48.0977, 50.7841] N=6128|
|BULL_TREND|50.57% [46.9919, 54.2317] N=615|
|BEAR_TREND|54.39% [48.8091, 59.7973] N=296|
|LOW_VOLATILITY|50.21% [48.6814, 51.6241] N=3756|
|HIGH_VOLATILITY|50.06% [48.4874, 51.7123] N=3504|

Horizon/divergence detail: {"5": {"events": 13469, "probability": 0.5043433068527731, "ci_low": 0.49591098077065854, "ci_high": 0.5122559210037865, "mean_signed_return": 4.256275638981779e-06, "divergence": {"events": 5586, "probability": 0.5173648406731114, "ci_low": 0.5033834586466166, "ci_high": 0.5300751879699248, "mean_signed_return": 2.2529657456061195e-05}}, "10": {"events": 10778, "probability": 0.5050102059751346, "ci_low": 0.4948877342735201, "ci_high": 0.5140146594915569, "mean_signed_return": 1.3457638275379419e-05, "divergence": {"events": 4967, "probability": 0.5242601167706865, "ci_low": 0.5119790618079324, "ci_high": 0.5383531306623717, "mean_signed_return": 2.770669156806653e-05}}, "15": {"events": 9078, "probability": 0.5077109495483587, "ci_low": 0.49607016964089007, "ci_high": 0.5175148711169861, "mean_signed_return": 1.3819709668472295e-05, "divergence": {"events": 4526, "probability": 0.5143614670790986, "ci_low": 0.49954706142288996, "ci_high": 0.5293857711003094, "mean_signed_return": 1.8654163036618692e-05}}, "30": {"events": 6336, "probability": 0.49605429292929293, "ci_low": 0.483660827020202, "ci_high": 0.5086805555555556, "mean_signed_return": -1.5611032820737034e-05, "divergence": {"events": 3626, "probability": 0.5082735797021511, "ci_low": 0.48989933811362385, "ci_high": 0.525096525096525, "mean_signed_return": 1.113742095567483e-05}}, "60": {"events": 3999, "probability": 0.5021255313828457, "ci_low": 0.48534633658414605, "ci_high": 0.5163915978994749, "mean_signed_return": 3.8800027353762824e-05, "divergence": {"events": 2634, "probability": 0.5060744115413819, "ci_low": 0.4880315110098709, "ci_high": 0.526575550493546, "mean_signed_return": 1.568580325637676e-05}}}

### GBPUSD → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [26, 26, 26, 26, 6, 19, 19, 10], 'oos_selected_lag': 10, 'range_minutes': [6, 26]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.84% [47.2980, 50.3042] N=4109|
|LONDON|50.34% [48.6322, 52.0942] N=2674|
|LONDON_NEW_YORK_OVERLAP|47.89% [46.0303, 49.9552] N=2230|
|NEW_YORK|49.68% [47.4083, 52.0093] N=1717|
|OFF_SESSION|53.05% [48.6641, 58.1155] N=524|
|RANGE|49.50% [48.5004, 50.4617] N=10071|
|BULL_TREND|48.10% [45.1190, 51.2530] N=840|
|BEAR_TREND|50.48% [45.3065, 55.0481] N=416|
|LOW_VOLATILITY|49.77% [48.5894, 51.0122] N=5535|
|HIGH_VOLATILITY|48.95% [47.6303, 50.3293] N=5930|

Horizon/divergence detail: {"5": {"events": 13777, "probability": 0.4961167162662408, "ci_low": 0.48816687232343764, "ci_high": 0.5041119256732235, "mean_signed_return": -6.133649758511929e-06, "divergence": {"events": 5078, "probability": 0.5161480897991335, "ci_low": 0.5022499015360378, "ci_high": 0.5298395037416306, "mean_signed_return": 1.7697776705725303e-05}}, "10": {"events": 11131, "probability": 0.4942952115712874, "ci_low": 0.48490477046087505, "ci_high": 0.503818165483784, "mean_signed_return": -1.4409354246583606e-05, "divergence": {"events": 4577, "probability": 0.512999781516277, "ci_low": 0.49901682324666813, "ci_high": 0.5263272886169981, "mean_signed_return": 1.1452856745259963e-05}}, "15": {"events": 9343, "probability": 0.49106282778550786, "ci_low": 0.4808385957401263, "ci_high": 0.501501123836027, "mean_signed_return": -1.649689090323646e-05, "divergence": {"events": 4204, "probability": 0.5059467174119886, "ci_low": 0.49202545195052333, "ci_high": 0.5193922454804948, "mean_signed_return": 1.833948864758878e-05}}, "30": {"events": 6458, "probability": 0.48900588417466706, "ci_low": 0.47536388974914834, "ci_high": 0.5007006813254877, "mean_signed_return": -4.718472287660889e-05, "divergence": {"events": 3400, "probability": 0.49676470588235294, "ci_low": 0.47939705882352945, "ci_high": 0.511625, "mean_signed_return": -2.4093129387956923e-05}}, "60": {"events": 4069, "probability": 0.49422462521504057, "ci_low": 0.478612681248464, "ci_high": 0.5088535266650283, "mean_signed_return": -4.528762611595081e-05, "divergence": {"events": 2530, "probability": 0.5015810276679842, "ci_low": 0.4833794466403162, "ci_high": 0.5189723320158103, "mean_signed_return": -4.603649743900626e-05}}}

### USDCHF → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [1, 19, 1, 1, 1, 1, 1, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 19]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.77% [48.3397, 51.2578] N=4969|
|LONDON|49.77% [48.2062, 51.4320] N=3317|
|LONDON_NEW_YORK_OVERLAP|50.56% [48.6473, 52.1603] N=2848|
|NEW_YORK|49.42% [46.9970, 51.5645] N=1983|
|OFF_SESSION|47.19% [42.3221, 51.4092] N=534|
|RANGE|49.77% [48.8855, 50.6596] N=12205|
|BULL_TREND|50.20% [47.1129, 53.0364] N=988|
|BEAR_TREND|50.60% [46.2151, 54.9801] N=502|
|LOW_VOLATILITY|50.04% [48.7952, 51.2811] N=6559|
|HIGH_VOLATILITY|49.45% [48.3955, 50.6016] N=7231|

Horizon/divergence detail: {"5": {"events": 13595, "probability": 0.4977565281353439, "ci_low": 0.48944097094520045, "ci_high": 0.5065483633688856, "mean_signed_return": 4.433999046577045e-06, "divergence": {"events": 5301, "probability": 0.5112242973023958, "ci_low": 0.49905206564799093, "ci_high": 0.5272684399169968, "mean_signed_return": 2.4548924924073616e-05}}, "10": {"events": 10847, "probability": 0.49617405734304415, "ci_low": 0.4867129160136443, "ci_high": 0.5055337881441874, "mean_signed_return": 1.7612262781131928e-07, "divergence": {"events": 4742, "probability": 0.5086461408688318, "ci_low": 0.49514972585407, "ci_high": 0.522464150147617, "mean_signed_return": 3.785572254294212e-05}}, "15": {"events": 9149, "probability": 0.4949174773199257, "ci_low": 0.4861159689583561, "ci_high": 0.5047546179910373, "mean_signed_return": 8.942303905192e-06, "divergence": {"events": 4313, "probability": 0.5084627869232553, "ci_low": 0.4958207744029678, "ci_high": 0.5222640853234407, "mean_signed_return": 5.506552176989252e-05}}, "30": {"events": 6296, "probability": 0.49841168996188057, "ci_low": 0.4849110546378653, "ci_high": 0.5117534942820838, "mean_signed_return": 4.932006866570861e-06, "divergence": {"events": 3517, "probability": 0.505544498151834, "ci_low": 0.4889038953653682, "ci_high": 0.522035825988058, "mean_signed_return": 6.483740684427407e-05}}, "60": {"events": 3992, "probability": 0.5027555110220441, "ci_low": 0.4880949398797595, "ci_high": 0.5179170841683367, "mean_signed_return": 2.7357522618651575e-08, "divergence": {"events": 2552, "probability": 0.5121473354231975, "ci_low": 0.4898119122257053, "ci_high": 0.5303781347962382, "mean_signed_return": 6.422654424052994e-05}}}

### XAGUSD → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [30, 1, 1, 1, 1, 1, 1, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 30]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.67% [49.3134, 52.0199] N=4879|
|LONDON|48.88% [47.3338, 50.5267] N=3038|
|LONDON_NEW_YORK_OVERLAP|48.67% [46.9934, 50.3465] N=3045|
|NEW_YORK|46.91% [45.0999, 48.9807] N=2102|
|OFF_SESSION|46.78% [41.8129, 52.0468] N=342|
|RANGE|49.08% [48.2604, 50.0212] N=11902|
|BULL_TREND|48.89% [45.8586, 52.0732] N=990|
|BEAR_TREND|51.66% [47.9358, 55.3090] N=631|
|LOW_VOLATILITY|48.67% [47.3491, 50.0504] N=5999|
|HIGH_VOLATILITY|49.34% [48.2988, 50.4374] N=7671|

Horizon/divergence detail: {"5": {"events": 13368, "probability": 0.49124775583482944, "ci_low": 0.4832435667265111, "ci_high": 0.5008266008378216, "mean_signed_return": 1.1256080745030012e-05, "divergence": {"events": 1539, "probability": 0.5035737491877843, "ci_low": 0.47953216374269003, "ci_high": 0.5282651072124757, "mean_signed_return": 9.524897563062844e-06}}, "10": {"events": 10559, "probability": 0.4900085235344256, "ci_low": 0.4801543706790416, "ci_high": 0.49972772042807084, "mean_signed_return": 7.184734388300277e-06, "divergence": {"events": 1453, "probability": 0.4941500344115623, "ci_low": 0.4700619408121129, "ci_high": 0.5224019270474879, "mean_signed_return": -2.252586112228627e-05}}, "15": {"events": 8875, "probability": 0.4868732394366197, "ci_low": 0.4772957746478873, "ci_high": 0.49758309859154926, "mean_signed_return": 7.790029125616195e-06, "divergence": {"events": 1387, "probability": 0.5046863734679163, "ci_low": 0.478352559480894, "ci_high": 0.5295782263878875, "mean_signed_return": -2.226688831559666e-06}}, "30": {"events": 6118, "probability": 0.4941157240928408, "ci_low": 0.4817546583850932, "ci_high": 0.5072777051323961, "mean_signed_return": -1.0081413120435387e-05, "divergence": {"events": 1234, "probability": 0.4886547811993517, "ci_low": 0.4619124797406807, "ci_high": 0.5142017828200973, "mean_signed_return": -8.735579588809869e-05}}, "60": {"events": 3861, "probability": 0.4933954933954934, "ci_low": 0.4772015022015022, "ci_high": 0.5075174825174825, "mean_signed_return": -1.1302900622131215e-05, "divergence": {"events": 1060, "probability": 0.49245283018867925, "ci_low": 0.46226415094339623, "ci_high": 0.519811320754717, "mean_signed_return": -9.575259085988337e-05}}}

### SPX → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [13, 13, 13, 13, 1, 1, 1, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 13]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.13% [47.5869, 50.6890] N=4289|
|LONDON|48.93% [47.1562, 50.6470] N=3323|
|LONDON_NEW_YORK_OVERLAP|51.24% [49.4868, 52.9977] N=3220|
|NEW_YORK|47.54% [45.5417, 49.3135] N=2400|
|OFF_SESSION|49.21% [41.2698, 56.6138] N=189|
|RANGE|49.31% [48.3744, 50.1561] N=11966|
|BULL_TREND|49.56% [46.3005, 52.6626] N=1015|
|BEAR_TREND|48.64% [44.6449, 53.5019] N=514|
|LOW_VOLATILITY|49.22% [48.0250, 50.5141] N=6229|
|HIGH_VOLATILITY|49.77% [48.7408, 51.0156] N=7348|

Horizon/divergence detail: {"5": {"events": 13349, "probability": 0.4930706419956551, "ci_low": 0.48460558843359053, "ci_high": 0.501161135665593, "mean_signed_return": -7.378590863411087e-07, "divergence": {"events": 7398, "probability": 0.5001351716680184, "ci_low": 0.4892504731008381, "ci_high": 0.5113544201135442, "mean_signed_return": -5.484102039863724e-06}}, "10": {"events": 10645, "probability": 0.49995302959135746, "ci_low": 0.489614842649131, "ci_high": 0.5093518083607327, "mean_signed_return": 6.7799616558507275e-06, "divergence": {"events": 6363, "probability": 0.49646393210749645, "ci_low": 0.48451202263083454, "ci_high": 0.5091191261983341, "mean_signed_return": -1.0574308348406842e-05}}, "15": {"events": 8953, "probability": 0.5047470121746901, "ci_low": 0.49424773818831674, "ci_high": 0.5146933988607171, "mean_signed_return": 1.7549493620055807e-06, "divergence": {"events": 5695, "probability": 0.5109745390693591, "ci_low": 0.49673397717295875, "ci_high": 0.5230904302019315, "mean_signed_return": 3.972935099650934e-06}}, "30": {"events": 6213, "probability": 0.4963785610816031, "ci_low": 0.48518831482375663, "ci_high": 0.5092547883470143, "mean_signed_return": -1.4405878573171165e-05, "divergence": {"events": 4370, "probability": 0.4983981693363844, "ci_low": 0.4834038901601831, "ci_high": 0.5125972540045767, "mean_signed_return": -2.137012122790393e-05}}, "60": {"events": 3913, "probability": 0.49041656018400204, "ci_low": 0.47482749808331204, "ci_high": 0.5072834142601584, "mean_signed_return": -2.353237167942782e-05, "divergence": {"events": 3062, "probability": 0.4915088177661659, "ci_low": 0.47419986936642716, "ci_high": 0.5086626387981711, "mean_signed_return": -1.603734255158902e-05}}}

### DXY → EURUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, DXY_EURUSD_STRUCTURAL_DEPENDENCE_REQUIRES_INDEPENDENT_CONFIRMATION, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [7, 5, 29, 29, 29, 29, 29, 29], 'oos_selected_lag': 29, 'range_minutes': [5, 29]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.17% [45.7824, 50.6137] N=1719|
|LONDON|47.67% [45.0820, 50.0662] N=1586|
|LONDON_NEW_YORK_OVERLAP|49.00% [46.3863, 51.7339] N=1302|
|NEW_YORK|48.32% [45.3638, 51.2809] N=1134|
|OFF_SESSION|46.15% [39.3162, 53.8462] N=117|
|RANGE|47.51% [46.2763, 48.8515] N=5224|
|BULL_TREND|49.21% [44.4444, 54.1950] N=441|
|BEAR_TREND|52.65% [47.6190, 57.5463] N=378|
|LOW_VOLATILITY|47.01% [44.8791, 48.9445] N=2461|
|HIGH_VOLATILITY|48.46% [46.9555, 50.1637] N=3696|

Horizon/divergence detail: {"5": {"events": 11366, "probability": 0.4917297202181946, "ci_low": 0.48349683265880694, "ci_high": 0.5016760513813127, "mean_signed_return": 1.954895908957971e-06, "divergence": {"events": 51, "probability": 0.5098039215686274, "ci_low": 0.36225490196078436, "ci_high": 0.6470588235294118, "mean_signed_return": 2.959589535771924e-05}}, "10": {"events": 9279, "probability": 0.48356503933613537, "ci_low": 0.47326489923483134, "ci_high": 0.49413191076624635, "mean_signed_return": -5.832841568911892e-06, "divergence": {"events": 51, "probability": 0.5490196078431373, "ci_low": 0.43137254901960786, "ci_high": 0.6666666666666666, "mean_signed_return": 7.599272266339775e-05}}, "15": {"events": 7922, "probability": 0.47601615753597576, "ci_low": 0.46591769755112344, "ci_high": 0.4866258520575612, "mean_signed_return": -9.942233757092985e-06, "divergence": {"events": 51, "probability": 0.45098039215686275, "ci_low": 0.3137254901960784, "ci_high": 0.5882352941176471, "mean_signed_return": 2.1828381798321707e-06}}, "30": {"events": 5526, "probability": 0.4761129207383279, "ci_low": 0.46308360477741584, "ci_high": 0.4897801302931596, "mean_signed_return": -2.2343739354231334e-05, "divergence": {"events": 44, "probability": 0.5, "ci_low": 0.36363636363636365, "ci_high": 0.6255681818181813, "mean_signed_return": 6.71366090394559e-05}}, "60": {"events": 3519, "probability": 0.49246945154873545, "ci_low": 0.4774083546462063, "ci_high": 0.5080988917306053, "mean_signed_return": 1.4897794482748798e-05, "divergence": {"events": 38, "probability": 0.47368421052631576, "ci_low": 0.3684210526315789, "ci_high": 0.5789473684210527, "mean_signed_return": -8.29058551384952e-05}}}

### GBPUSD → EURUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [26, 26, 26, 26, 1, 1, 1, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 26]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.41% [47.1092, 49.8253] N=5137|
|LONDON|49.40% [47.6607, 50.9958] N=3314|
|LONDON_NEW_YORK_OVERLAP|48.96% [47.1054, 50.8214] N=2800|
|NEW_YORK|49.25% [47.1643, 51.4300] N=2063|
|OFF_SESSION|49.30% [46.1232, 51.9373] N=1213|
|RANGE|48.88% [48.0949, 49.7661] N=13019|
|BULL_TREND|49.42% [46.1538, 52.3922] N=858|
|BEAR_TREND|48.49% [44.6198, 52.1557] N=697|
|LOW_VOLATILITY|49.31% [48.1091, 50.5198] N=6637|
|HIGH_VOLATILITY|48.78% [47.7671, 49.8156] N=8106|

Horizon/divergence detail: {"5": {"events": 14447, "probability": 0.4894441752612999, "ci_low": 0.48224544888212084, "ci_high": 0.4980964906208902, "mean_signed_return": -1.4610569342237884e-06, "divergence": {"events": 1069, "probability": 0.5135640785781104, "ci_low": 0.48175865294667913, "ci_high": 0.5425631431244153, "mean_signed_return": 1.929191355725406e-05}}, "10": {"events": 11606, "probability": 0.48948819576081337, "ci_low": 0.4817335860761675, "ci_high": 0.49866663794589006, "mean_signed_return": 1.3466040156288504e-06, "divergence": {"events": 953, "probability": 0.5036726128016789, "ci_low": 0.47429171038824763, "ci_high": 0.5362539349422875, "mean_signed_return": 1.841460685253213e-05}}, "15": {"events": 9688, "probability": 0.4921552436003303, "ci_low": 0.4817248142031379, "ci_high": 0.5026888934764657, "mean_signed_return": 1.1761791082396973e-06, "divergence": {"events": 883, "probability": 0.49150622876557193, "ci_low": 0.4563986409966025, "ci_high": 0.5232163080407701, "mean_signed_return": 2.9876811156488143e-05}}, "30": {"events": 6639, "probability": 0.4845609278505799, "ci_low": 0.47378746799216753, "ci_high": 0.49571471607169754, "mean_signed_return": -1.8951022219495295e-05, "divergence": {"events": 754, "probability": 0.5053050397877984, "ci_low": 0.473474801061008, "ci_high": 0.5384615384615384, "mean_signed_return": 3.829296205684785e-05}}, "60": {"events": 4115, "probability": 0.49040097205346295, "ci_low": 0.4754374240583232, "ci_high": 0.5041373025516404, "mean_signed_return": -2.752085089073641e-05, "divergence": {"events": 627, "probability": 0.5039872408293461, "ci_low": 0.46730462519936206, "ci_high": 0.5406698564593302, "mean_signed_return": 3.938456192092423e-06}}}

### USDCHF → EURUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [13, 13, 7, 1, 1, 1, 6, 1], 'oos_selected_lag': 1, 'range_minutes': [1, 13]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|49.81% [48.4824, 51.3166] N=4975|
|LONDON|48.21% [46.4889, 49.9850] N=3333|
|LONDON_NEW_YORK_OVERLAP|49.60% [47.8655, 51.4166] N=2859|
|NEW_YORK|46.48% [44.0637, 48.5799] N=2072|
|OFF_SESSION|46.32% [43.6760, 49.3220] N=1250|
|RANGE|48.52% [47.7046, 49.4216] N=12963|
|BULL_TREND|48.90% [45.6954, 52.3234] N=906|
|BEAR_TREND|51.47% [47.8322, 54.9650] N=715|
|LOW_VOLATILITY|47.96% [46.6191, 49.2149] N=6553|
|HIGH_VOLATILITY|49.06% [47.9635, 50.1845] N=8128|

Horizon/divergence detail: {"5": {"events": 14418, "probability": 0.4866139547787488, "ci_low": 0.4791857400471633, "ci_high": 0.49410805937023167, "mean_signed_return": 1.9015730482830638e-06, "divergence": {"events": 1537, "probability": 0.5146389069616135, "ci_low": 0.49183474300585556, "ci_high": 0.5374430709173714, "mean_signed_return": 1.994595506291736e-05}}, "10": {"events": 11421, "probability": 0.4806934594168637, "ci_low": 0.4720252167060678, "ci_high": 0.4894492601348393, "mean_signed_return": -7.43577192788988e-07, "divergence": {"events": 1327, "probability": 0.5139412207987942, "ci_low": 0.4905802562170309, "ci_high": 0.5388093443858327, "mean_signed_return": 2.117651953699337e-05}}, "15": {"events": 9593, "probability": 0.4842072344417805, "ci_low": 0.47450745335140204, "ci_high": 0.4930678619826957, "mean_signed_return": -7.051047506169239e-07, "divergence": {"events": 1222, "probability": 0.5212765957446809, "ci_low": 0.49302373158756135, "ci_high": 0.546644844517185, "mean_signed_return": 3.433782799058289e-05}}, "30": {"events": 6521, "probability": 0.4868885140315902, "ci_low": 0.47492715841128663, "ci_high": 0.49862367735009966, "mean_signed_return": 9.651436426722113e-06, "divergence": {"events": 1009, "probability": 0.5252725470763132, "ci_low": 0.49204658077304264, "ci_high": 0.5550049554013875, "mean_signed_return": 7.340633678387929e-05}}, "60": {"events": 4084, "probability": 0.49951028403525954, "ci_low": 0.4818437806072478, "ci_high": 0.5149363369245837, "mean_signed_return": 2.235457475222921e-05, "divergence": {"events": 815, "probability": 0.5190184049079755, "ci_low": 0.4833742331288343, "ci_high": 0.5552453987730062, "mean_signed_return": 0.00012512590448431204}}}

### EURGBP → EURUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [26, 26, 26, 26, 26, 26, 26, 2], 'oos_selected_lag': 2, 'range_minutes': [2, 26]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.34% [46.8421, 49.9307] N=4940|
|LONDON|47.64% [45.8004, 49.2106] N=3417|
|LONDON_NEW_YORK_OVERLAP|47.81% [45.9360, 49.7260] N=2719|
|NEW_YORK|48.85% [46.7386, 51.0311] N=2039|
|OFF_SESSION|47.11% [44.3018, 49.8816] N=1246|
|RANGE|48.02% [47.1478, 48.9229] N=12764|
|BULL_TREND|48.69% [45.3714, 52.3429] N=875|
|BEAR_TREND|49.21% [45.7672, 52.5132] N=756|
|LOW_VOLATILITY|47.80% [46.5642, 48.9808] N=6623|
|HIGH_VOLATILITY|48.19% [46.9737, 49.2506] N=7866|

Horizon/divergence detail: {"5": {"events": 14252, "probability": 0.48035363457760316, "ci_low": 0.4721372438955936, "ci_high": 0.48846302273365144, "mean_signed_return": -7.4412262744147414e-06, "divergence": {"events": 11351, "probability": 0.4903532728393974, "ci_low": 0.48140472205092066, "ci_high": 0.4993018236278742, "mean_signed_return": -7.5910653607937365e-06}}, "10": {"events": 11308, "probability": 0.49548991864166964, "ci_low": 0.4862420410328971, "ci_high": 0.505221966749204, "mean_signed_return": 3.142831852246657e-06, "divergence": {"events": 9337, "probability": 0.49437720895362536, "ci_low": 0.4831316268608761, "ci_high": 0.5035370033201243, "mean_signed_return": 4.286026866426828e-07}}, "15": {"events": 9488, "probability": 0.5084317032040472, "ci_low": 0.49773134485666104, "ci_high": 0.5189766020236087, "mean_signed_return": 2.951229580950976e-06, "divergence": {"events": 8032, "probability": 0.5109561752988048, "ci_low": 0.5005509213147411, "ci_high": 0.5212307021912351, "mean_signed_return": 6.265259565238731e-06}}, "30": {"events": 6520, "probability": 0.48819018404907977, "ci_low": 0.47607361963190187, "ci_high": 0.49969325153374233, "mean_signed_return": -1.0487265129533865e-05, "divergence": {"events": 5704, "probability": 0.5008765778401122, "ci_low": 0.48807854137447404, "ci_high": 0.5131574333800841, "mean_signed_return": 6.566502850970538e-06}}, "60": {"events": 4085, "probability": 0.5018359853121175, "ci_low": 0.4872643818849449, "ci_high": 0.5165238678090576, "mean_signed_return": 1.904609245850619e-05, "divergence": {"events": 3709, "probability": 0.5171205176597465, "ci_low": 0.4995955783229981, "ci_high": 0.5345173901321111, "mean_signed_return": 4.062298705239933e-05}}}

### USDJPY → EURUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [12, 7, 7, 7, 27, 27, 27, 27], 'oos_selected_lag': 27, 'range_minutes': [7, 27]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|48.46% [46.5234, 50.3803] N=2373|
|LONDON|49.23% [46.4407, 51.5721] N=1560|
|LONDON_NEW_YORK_OVERLAP|50.26% [47.5877, 52.6662] N=1369|
|NEW_YORK|52.03% [49.1708, 54.8387] N=1209|
|OFF_SESSION|51.53% [48.1651, 55.0459] N=654|
|RANGE|49.92% [48.7250, 51.1886] N=6394|
|BULL_TREND|51.89% [46.5047, 57.0802] N=530|
|BEAR_TREND|50.24% [44.5328, 55.3398] N=412|
|LOW_VOLATILITY|50.16% [48.4799, 51.8601] N=3684|
|HIGH_VOLATILITY|50.46% [48.9834, 51.9158] N=3787|

Horizon/divergence detail: {"5": {"events": 14010, "probability": 0.48665239114917913, "ci_low": 0.4786509635974304, "ci_high": 0.49483047822983584, "mean_signed_return": -3.552361466145416e-06, "divergence": {"events": 12592, "probability": 0.4874523506988564, "ci_low": 0.47879209021601016, "ci_high": 0.4958743646759848, "mean_signed_return": -4.0493466981299375e-06}}, "10": {"events": 11148, "probability": 0.4973986365267313, "ci_low": 0.48874013275923933, "ci_high": 0.5056086293505562, "mean_signed_return": -4.223936688954683e-06, "divergence": {"events": 10228, "probability": 0.4964802502933125, "ci_low": 0.4859210011732499, "ci_high": 0.5074305827141181, "mean_signed_return": -4.404280311502637e-06}}, "15": {"events": 9343, "probability": 0.4872096756930322, "ci_low": 0.47789253986942093, "ci_high": 0.4958792679011024, "mean_signed_return": -4.730271417257041e-06, "divergence": {"events": 8679, "probability": 0.4868072358566655, "ci_low": 0.4760312247954834, "ci_high": 0.4983350616430464, "mean_signed_return": -4.937588611979325e-06}}, "30": {"events": 6449, "probability": 0.5020933478058613, "ci_low": 0.4902271670026361, "ci_high": 0.5142696542099551, "mean_signed_return": -3.630693383772925e-06, "divergence": {"events": 6124, "probability": 0.5022860875244938, "ci_low": 0.49052906596995427, "ci_high": 0.5144554212932724, "mean_signed_return": 4.274797027081228e-06}}, "60": {"events": 4030, "probability": 0.49007444168734493, "ci_low": 0.47505583126550865, "ci_high": 0.5044665012406948, "mean_signed_return": -3.0088848169121218e-05, "divergence": {"events": 3870, "probability": 0.4994832041343669, "ci_low": 0.4844961240310077, "ci_high": 0.5142118863049095, "mean_signed_return": -9.303596628453147e-06}}}

### SPX → EURUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [6, 6, 6, 6, 3, 3, 17, 3], 'oos_selected_lag': 3, 'range_minutes': [3, 17]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|47.27% [45.7838, 48.6894] N=4271|
|LONDON|48.81% [47.2307, 50.3762] N=3323|
|LONDON_NEW_YORK_OVERLAP|50.36% [48.4789, 52.1416] N=3223|
|NEW_YORK|48.50% [46.3790, 50.6042] N=2404|
|OFF_SESSION|48.89% [42.7778, 55.2917] N=180|
|RANGE|48.52% [47.5318, 49.3684] N=11953|
|BULL_TREND|47.86% [44.1361, 51.1600] N=819|
|BEAR_TREND|48.75% [45.2135, 52.4300] N=679|
|LOW_VOLATILITY|47.76% [46.4965, 49.0971] N=5867|
|HIGH_VOLATILITY|49.20% [48.0511, 50.3400] N=7648|

Horizon/divergence detail: {"5": {"events": 13330, "probability": 0.48604651162790696, "ci_low": 0.47756564141035257, "ci_high": 0.4941129032258065, "mean_signed_return": -8.726967748799031e-07, "divergence": {"events": 7313, "probability": 0.4894024340216054, "ci_low": 0.4774203473266785, "ci_high": 0.5014426364009298, "mean_signed_return": -2.9521159492576905e-06}}, "10": {"events": 10620, "probability": 0.49171374764595105, "ci_low": 0.48140065913371, "ci_high": 0.5, "mean_signed_return": 1.5337656941168023e-06, "divergence": {"events": 6313, "probability": 0.493743069855853, "ci_low": 0.481229209567559, "ci_high": 0.5065737367337241, "mean_signed_return": 1.5049596877197093e-06}}, "15": {"events": 8918, "probability": 0.4937205651491366, "ci_low": 0.4839594079389998, "ci_high": 0.5034761157210137, "mean_signed_return": -3.517531481988623e-06, "divergence": {"events": 5629, "probability": 0.49902291703677387, "ci_low": 0.4874666903535264, "ci_high": 0.5118138212826434, "mean_signed_return": 5.990773908235572e-06}}, "30": {"events": 6149, "probability": 0.4965034965034965, "ci_low": 0.483818507074321, "ci_high": 0.509932509351114, "mean_signed_return": 4.7497359740462525e-07, "divergence": {"events": 4318, "probability": 0.4981472904122279, "ci_low": 0.48331403427512737, "ci_high": 0.5140169059749884, "mean_signed_return": -4.698905808717314e-07}}, "60": {"events": 3837, "probability": 0.5022152723481886, "ci_low": 0.48918425853531405, "ci_high": 0.5208561376075058, "mean_signed_return": -1.0381234688302627e-05, "divergence": {"events": 2992, "probability": 0.5046791443850267, "ci_low": 0.48763368983957217, "ci_high": 0.5212316176470588, "mean_signed_return": -4.220796526430204e-06}}}

### NQ → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [5, 5, 5, 5, 15, 15, 120, 120], 'oos_selected_lag': 120, 'range_minutes': [5, 120]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.00% [42.8030, 56.8182] N=264|
|LONDON|51.29% [46.1207, 55.7166] N=464|
|LONDON_NEW_YORK_OVERLAP|51.98% [47.5771, 57.2687] N=454|
|NEW_YORK|49.79% [43.4599, 56.5401] N=237|
|OFF_SESSION|55.56% [N/A, N/A] N=9|
|RANGE|49.65% [47.1002, 52.2847] N=1138|
|BULL_TREND|51.77% [43.2624, 60.2837] N=141|
|BEAR_TREND|48.21% [34.7768, 62.5000] N=56|
|LOW_VOLATILITY|48.68% [45.2150, 51.9452] N=721|
|HIGH_VOLATILITY|50.52% [46.7958, 54.3964] N=671|

Horizon/divergence detail: {"5": {"events": 4153, "probability": 0.5145677823260294, "ci_low": 0.49841078738261496, "ci_high": 0.5292559595473152, "mean_signed_return": 1.4176368936462313e-05, "divergence": {"events": 2421, "probability": 0.5022717885171417, "ci_low": 0.4840768277571251, "ci_high": 0.5231412639405204, "mean_signed_return": -3.038224223087183e-06}}, "10": {"events": 3665, "probability": 0.5115961800818554, "ci_low": 0.49495225102319235, "ci_high": 0.5289427012278308, "mean_signed_return": 1.902754553589041e-05, "divergence": {"events": 2224, "probability": 0.5058453237410072, "ci_low": 0.4853754496402877, "ci_high": 0.5274280575539568, "mean_signed_return": -9.236365218565747e-06}}, "15": {"events": 3287, "probability": 0.4968055978095528, "ci_low": 0.48021752357773045, "ci_high": 0.5141770611499847, "mean_signed_return": 9.494495452439462e-06, "divergence": {"events": 2075, "probability": 0.5079518072289156, "ci_low": 0.48793975903614456, "ci_high": 0.5274819277108433, "mean_signed_return": -1.9596074467405773e-05}}, "30": {"events": 2617, "probability": 0.49980894153611005, "ci_low": 0.48299579671379445, "ci_high": 0.5196790217806648, "mean_signed_return": 3.794217552969464e-05, "divergence": {"events": 1739, "probability": 0.4991374353076481, "ci_low": 0.4758338125359402, "ci_high": 0.525316273720529, "mean_signed_return": 2.913319265324455e-05}}, "60": {"events": 1921, "probability": 0.5148360229047371, "ci_low": 0.4932196772514315, "ci_high": 0.53461738677772, "mean_signed_return": 3.979505483792432e-05, "divergence": {"events": 1394, "probability": 0.5007173601147776, "ci_low": 0.47595050215208035, "ci_high": 0.5254842180774749, "mean_signed_return": -5.134041537331264e-05}}}

### NQ → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 15, 15, 60, 60, 60, 60], 'oos_selected_lag': 60, 'range_minutes': [15, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|52.83% [43.3962, 62.2642] N=53|
|LONDON|55.41% [43.2432, 67.5676] N=74|
|LONDON_NEW_YORK_OVERLAP|49.72% [44.2020, 55.0847] N=354|
|NEW_YORK|49.55% [44.1088, 55.2870] N=331|
|OFF_SESSION|69.44% [58.3333, 82.0139] N=36|
|RANGE|50.89% [47.1159, 54.4582] N=729|
|BULL_TREND|48.00% [37.3333, 60.0000] N=75|
|BEAR_TREND|47.62% [33.3333, 61.9048] N=21|
|LOW_VOLATILITY|51.20% [47.0460, 56.2363] N=457|
|HIGH_VOLATILITY|51.73% [46.1333, 57.7400] N=375|

Horizon/divergence detail: {"15": {"events": 1131, "probability": 0.4739168877099912, "ci_low": 0.44562334217506633, "ci_high": 0.5013262599469496, "mean_signed_return": -5.6560073911479016e-05, "divergence": {"events": 697, "probability": 0.47058823529411764, "ci_low": 0.4375896700143472, "ci_high": 0.5086441893830702, "mean_signed_return": -0.00011998494422786804}}, "30": {"events": 999, "probability": 0.4914914914914915, "ci_low": 0.45893393393393395, "ci_high": 0.5245245245245245, "mean_signed_return": -7.407569372553973e-06, "divergence": {"events": 635, "probability": 0.5007874015748032, "ci_low": 0.462992125984252, "ci_high": 0.5385826771653544, "mean_signed_return": -6.724941324230726e-05}}, "60": {"events": 813, "probability": 0.5079950799507995, "ci_low": 0.4710947109471095, "ci_high": 0.543081180811808, "mean_signed_return": -0.00020272400971325653, "divergence": {"events": 538, "probability": 0.5111524163568774, "ci_low": 0.4684014869888476, "ci_high": 0.5530204460966542, "mean_signed_return": -0.0001875800807049486}}}

### NQ → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [8, 8, 60, 12, 27, 27, 1, 1], 'oos_selected_lag': 120, 'range_minutes': [1, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|51.06% [47.8261, 54.1276] N=897|
|LONDON|48.59% [44.5148, 52.2963] N=675|
|LONDON_NEW_YORK_OVERLAP|47.69% [43.2692, 52.5000] N=520|
|NEW_YORK|48.91% [44.5255, 53.5280] N=411|
|OFF_SESSION|41.67% [29.1667, 56.2500] N=48|
|RANGE|50.94% [48.8775, 53.1583] N=2138|
|BULL_TREND|47.03% [41.5842, 53.1002] N=404|
|BEAR_TREND|51.34% [45.7478, 57.1429] N=224|
|LOW_VOLATILITY|49.13% [46.7742, 51.4819] N=1488|
|HIGH_VOLATILITY|50.45% [47.9124, 53.1146] N=1558|

Horizon/divergence detail: {"5": {"events": 13324, "probability": 0.5013509456619634, "ci_low": 0.4928700090063044, "ci_high": 0.5098318823176223, "mean_signed_return": 4.371370496150975e-06, "divergence": {"events": 8465, "probability": 0.5075014766686355, "ci_low": 0.4976166568222091, "ci_high": 0.5177849970466627, "mean_signed_return": 3.040896922273322e-06}}, "10": {"events": 10575, "probability": 0.5017494089834516, "ci_low": 0.49209456264775414, "ci_high": 0.5100709219858156, "mean_signed_return": -5.947405637969546e-06, "divergence": {"events": 7247, "probability": 0.5057265075203532, "ci_low": 0.49454256933903684, "ci_high": 0.5167000137988134, "mean_signed_return": -3.1196419394836045e-06}}, "15": {"events": 8933, "probability": 0.49546624874062467, "ci_low": 0.4854975931937759, "ci_high": 0.5063304600917944, "mean_signed_return": -1.6013372891941648e-06, "divergence": {"events": 6417, "probability": 0.4989870656069815, "ci_low": 0.4855851644070438, "ci_high": 0.5114539504441328, "mean_signed_return": 7.22184195727762e-06}}, "30": {"events": 6183, "probability": 0.5063884845544234, "ci_low": 0.494088630114831, "ci_high": 0.5179645803008248, "mean_signed_return": 3.596830243240901e-05, "divergence": {"events": 4846, "probability": 0.5134131242261659, "ci_low": 0.4997833264548081, "ci_high": 0.5268365662401981, "mean_signed_return": 5.132711550980843e-05}}, "60": {"events": 3936, "probability": 0.5, "ci_low": 0.4823361280487805, "ci_high": 0.5166476117886178, "mean_signed_return": -1.203622032294718e-05, "divergence": {"events": 3301, "probability": 0.5156013329294153, "ci_low": 0.4989397152378067, "ci_high": 0.5294077552256892, "mean_signed_return": 8.888835432008784e-05}}}

### WTI → XAUUSD M5

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, WTI_2024_2025_HISTORICAL_DATA_UNAVAILABLE_2023_HOLDOUT_ONLY, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 5, 5, 10, 10, 45], 'oos_selected_lag': 45, 'range_minutes': [5, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|51.43% [45.7143, 56.1500] N=350|
|LONDON|48.46% [44.9327, 52.0513] N=780|
|LONDON_NEW_YORK_OVERLAP|45.19% [40.7392, 49.8858] N=416|
|NEW_YORK|47.83% [40.2174, 54.8913] N=184|
|OFF_SESSION|N/A|
|RANGE|48.90% [46.5468, 51.6774] N=1550|
|BULL_TREND|41.67% [31.9444, 52.7778] N=72|
|BEAR_TREND|44.30% [34.7785, 54.4304] N=79|
|LOW_VOLATILITY|48.09% [44.7872, 50.9069] N=940|
|HIGH_VOLATILITY|49.37% [45.6736, 52.8822] N=798|

Horizon/divergence detail: {"5": {"events": 3373, "probability": 0.49925882004150607, "ci_low": 0.4826415653720723, "ci_high": 0.5179662021938927, "mean_signed_return": 4.658702596424841e-06, "divergence": {"events": 1439, "probability": 0.5100764419735928, "ci_low": 0.4836692147324531, "ci_high": 0.532314107018763, "mean_signed_return": 3.3343007494395894e-06}}, "10": {"events": 2954, "probability": 0.4983073798239675, "ci_low": 0.4813811780636425, "ci_high": 0.5152335815842924, "mean_signed_return": 5.458123254491566e-06, "divergence": {"events": 1337, "probability": 0.5198204936424832, "ci_low": 0.49364248317127896, "ci_high": 0.5463911742707553, "mean_signed_return": 4.85454132824135e-06}}, "15": {"events": 2653, "probability": 0.5054655107425556, "ci_low": 0.4866189219751225, "ci_high": 0.5247078778741048, "mean_signed_return": -1.8888378348673696e-06, "divergence": {"events": 1262, "probability": 0.5015847860538827, "ci_low": 0.4734350237717908, "ci_high": 0.5273573692551505, "mean_signed_return": -1.560496372150081e-05}}, "30": {"events": 2011, "probability": 0.49676777722526105, "ci_low": 0.4766161113873695, "ci_high": 0.5171556439582298, "mean_signed_return": -1.0192946144579042e-05, "divergence": {"events": 1076, "probability": 0.4972118959107807, "ci_low": 0.46933085501858735, "ci_high": 0.5269516728624535, "mean_signed_return": -2.0356094128885966e-05}}, "60": {"events": 1386, "probability": 0.5043290043290043, "ci_low": 0.47398989898989896, "ci_high": 0.5288600288600288, "mean_signed_return": -3.5015095254872894e-05, "divergence": {"events": 812, "probability": 0.5024630541871922, "ci_low": 0.46921182266009853, "ci_high": 0.5344827586206896, "mean_signed_return": 6.211180792019136e-06}}}

### WTI → XAUUSD M15

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, WTI_2024_2025_HISTORICAL_DATA_UNAVAILABLE_2023_HOLDOUT_ONLY, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [60, 60, 60, 60, 60, 60], 'oos_selected_lag': 30, 'range_minutes': [60, 60]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|56.00% [32.0000, 76.0000] N=25|
|LONDON|48.94% [42.5532, 55.3191] N=141|
|LONDON_NEW_YORK_OVERLAP|46.30% [40.7407, 52.2222] N=270|
|NEW_YORK|47.31% [40.1198, 54.4910] N=167|
|OFF_SESSION|N/A|
|RANGE|47.74% [44.1594, 51.2195] N=574|
|BULL_TREND|60.00% [N/A, N/A] N=10|
|BEAR_TREND|31.25% [N/A, N/A] N=16|
|LOW_VOLATILITY|48.27% [44.1558, 53.1439] N=462|
|HIGH_VOLATILITY|44.60% [38.1295, 51.0791] N=139|

Horizon/divergence detail: {"15": {"events": 692, "probability": 0.5043352601156069, "ci_low": 0.47109826589595377, "ci_high": 0.5390173410404624, "mean_signed_return": -4.393241566111847e-06, "divergence": {"events": 276, "probability": 0.463768115942029, "ci_low": 0.407518115942029, "ci_high": 0.523641304347826, "mean_signed_return": -7.235385734802336e-05}}, "30": {"events": 599, "probability": 0.4757929883138564, "ci_low": 0.4348497495826377, "ci_high": 0.5125208681135225, "mean_signed_return": -3.1282417560462935e-05, "divergence": {"events": 246, "probability": 0.45934959349593496, "ci_low": 0.3983739837398374, "ci_high": 0.5284552845528455, "mean_signed_return": -2.9558385902811467e-05}}, "60": {"events": 458, "probability": 0.44541484716157204, "ci_low": 0.4006004366812227, "ci_high": 0.4868995633187773, "mean_signed_return": -0.00022330114830392477, "divergence": {"events": 215, "probability": 0.48372093023255813, "ci_low": 0.4161627906976744, "ci_high": 0.5534883720930233, "mean_signed_return": -9.873104768780974e-05}}}

### WTI → XAUUSD M1

Penolakan: OOS_PROBABILITY_CI_NOT_ABOVE_50_PERCENT, WALK_FORWARD_UNSTABLE, BASELINE_INCREMENTAL_BENEFIT_NOT_VERIFIED, BROKER_COST_ROBUSTNESS_NOT_VERIFIED, HISTORICAL_EVENT_COVERAGE_MISSING, WTI_2024_2025_HISTORICAL_DATA_UNAVAILABLE_2023_HOLDOUT_ONLY, MULTIPLE_TESTING_FDR_FAILED

Lag per fold: {'fold_lags': [17, 29, 29, 29, 28, 28], 'oos_selected_lag': 5, 'range_minutes': [17, 29]}

|Session/regime|OOS conditional probability, CI95, N|
|---|---|
|ASIA|50.14% [48.4727, 51.5390] N=4061|
|LONDON|49.57% [47.7395, 51.2970] N=3163|
|LONDON_NEW_YORK_OVERLAP|51.31% [48.7842, 53.6126] N=1647|
|NEW_YORK|47.64% [44.3255, 50.9127] N=934|
|OFF_SESSION|49.26% [42.2610, 55.8824] N=136|
|RANGE|49.94% [48.9142, 50.9188] N=8982|
|BULL_TREND|51.31% [46.8165, 55.9925] N=534|
|BEAR_TREND|49.89% [45.7120, 54.3897] N=467|
|LOW_VOLATILITY|48.92% [47.4385, 50.4771] N=3982|
|HIGH_VOLATILITY|50.44% [49.0771, 51.8952] N=6068|

Horizon/divergence detail: {"5": {"events": 9916, "probability": 0.49969745865268256, "ci_low": 0.48976149657119805, "ci_high": 0.5095905607099637, "mean_signed_return": 7.86250857885007e-07, "divergence": {"events": 7094, "probability": 0.5105723146320834, "ci_low": 0.4982344234564421, "ci_high": 0.5222793910346771, "mean_signed_return": 7.730719803977699e-06}}, "10": {"events": 7709, "probability": 0.49137371902970556, "ci_low": 0.48066869892333636, "ci_high": 0.5026592294720457, "mean_signed_return": -9.026160030430627e-06, "divergence": {"events": 5856, "probability": 0.5018784153005464, "ci_low": 0.4891436133879781, "ci_high": 0.5148565573770492, "mean_signed_return": -2.2607103883404516e-06}}, "15": {"events": 6374, "probability": 0.497646689676812, "ci_low": 0.48446030749921554, "ci_high": 0.509570128647631, "mean_signed_return": -1.3091092874455275e-05, "divergence": {"events": 5013, "probability": 0.5074805505685218, "ci_low": 0.4932126471174945, "ci_high": 0.5216537003790145, "mean_signed_return": -9.107138984589004e-06}}, "30": {"events": 4296, "probability": 0.4993016759776536, "ci_low": 0.483350791433892, "ci_high": 0.5164164338919925, "mean_signed_return": 1.3180109982857716e-06, "divergence": {"events": 3587, "probability": 0.49540005575689994, "ci_low": 0.4776902704209646, "ci_high": 0.5107332032339001, "mean_signed_return": -1.8532059764842212e-06}}, "60": {"events": 2626, "probability": 0.49276466108149275, "ci_low": 0.4723819497334349, "ci_high": 0.5127665651180503, "mean_signed_return": -3.10587785254569e-05, "divergence": {"events": 2314, "probability": 0.49178910976663787, "ci_low": 0.4714563526361279, "ci_high": 0.5116897147796025, "mean_signed_return": -1.6736554343274651e-06}}}

## Baseline dan shadow comparison

XAU frozen cautious manifest 2016–2025: PF 1.891902, equity M1 DD 45.56637%, 560 parent setups /4.6667 per bulan, balance $11,106.2367. WR tidak tersedia pada manifest ini. Hasil historis dipilih in-sample, bukan baseline independen OOS. Stress cost existing: PF1.663/DD83.319%; tidak dianggap robust. XAU + filter/divergence/early entry: NOT RUN karena kalender macro historis mandatory tidak lengkap; gate frozen tidak dilepas.

EUR reference replay 2016–2025: {"scope": "PUBLIC_BID_SYNTHETIC_COST_REPLAY", "policy_hash": "894860d6f8c968b2c6e45800e5f6542adfca5f512027eca7758e5b70a504e0e1", "trades": 204, "trades_month": 1.6997673145359977, "win_rate": 0.5294117647058824, "profit_factor": 2.2111414005448498, "expectancy_r": 0.2743963572566617, "max_dd_equity_m1_percent": 40.00313480008659, "ending_balance_usd": 11820.225714285078, "net_return_percent": 11720.225714285078, "average_r": 0.2743963572566617, "median_r": 0.0777590419773686, "mae_r": 0.618537288995379, "mfe_r": 1.0165651291485436, "holding_minutes": 199.79901960784315, "long": 114, "short": 90, "cost": {"spread": 0.00012, "slip_per_side": 1e-05, "extra_round_trip": 0.0}, "limitations": ["M1 OHLC equity extrema, not tick-order drawdown", "No native broker ASK/spread history, swaps or execution latency", "Constant 1:100 research margin, not current DEMO broker leverage", "Conditional trade removal preserves frozen virtual feedback"]}

EUR 2025 matched opportunity subset ablation berikut memakai kandidat USDJPY M5 lag5, sign−1, shock2sigma dipilih train partial corr dari pool M5/M15. Tidak dipilih melalui OOS winner. Ini bukan full counterfactual executable strategy: subset baseline opportunities, virtual feedback frozen dipertahankan, tidak membuka opportunities tambahan saat trade dihilangkan. Baseline sendiri sebelumnya dioptimasi 2016–2025; jangan menyebut baseline 2025 independen OOS.

|Variant 2025|Trades|Trades/month|WR %|PF|Expectancy R|DD %|Net %|Median R|MAE R|MFE R|Hold min|Long/short|
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|baseline|31|2.5851|51.6129|1.8158|0.1804|29.2639|101.7957|0.0032|0.5939|0.8483|203.1290|20/11|
|cross_asset_filter|3|0.2502|66.6667|1.2978|-0.1466|14.7831|1.9229|0.0317|0.6109|0.6741|196.6667|2/1|
|divergence_filter|0|0.0000|N/A|N/A|N/A|0.0000|0.0000|N/A|N/A|N/A|N/A|0/0|

Filter hanya 3 trades dan PF turun; DD turun bersamaan kehilangan ~90% kesempatan, tanpa benefit jelas. Divergence nol trades. REJECTED untuk eksekusi. Early entry NOT RUN: historical event coverage dan valid early H1/M15/area/invalidation geometry tidak tersedia. Sharpe/Sortino N/A. Session splits lengkap di shadow JSON.

EUR full reference balance $11,820.2257/PF2.21114 cocok dokumen frozen; DD40.0031% di replay memakai high/low peak intrabar konservatif dibanding 37.08% dokumen. Definisi dibedakan, dokumen/frozen policy tidak diubah.

## Robustness

32 shadow perturbations: threshold 1.5/2/2.5, lag sekitar satu bar; additive roundtrip cost .5/1/2pip; information delay 1/5/10min; 20 seeded random removal 10%. Ini tidak menggantikan full spread/slippage bracket-fill replay atau actual delayed fills. Bootstrap expectancy N/A karena N<20. Full historical broker spread/tick dropout, Monte Carlo ordering, true early-entry dan joint leader calibration belum dijalankan; kandidat gagal acceptance awal, tidak dipromosikan berdasarkan robustness parsial.

FP Markets Standard EUR spread 1.2pip dipakai frozen +slip.1pip per side; spread berubah-ubah dan simulasi bukan actual broker cost history. Sources: https://www.fpmarkets.com/forex-spreads/ ; https://www.histdata.com/ .

## Integrasi dan health

Read-only engine, dashboard research pada tab XAU/EUR, model default approved=false, zero execution authority. Tidak mengganti baseline H1/M15/M5 atau risk. Reference/execution geometry scanner existing tetap terpisah; current probability/lag/confidence tidak direkayasa. Runtime cache/freshness/latency/fail graceful dan optional Turso latest/calibration/history batched tersedia dan diuji; migration belum diterapkan karena tidak ada approved production model. Tidak menambah dashboard DB queries atau feed polling.

Turso and active XAU/EUR primary workers verified fresh via CI. DEMO broker read-only snapshot passed: zero orders mutated, zero token refresh, zero DB writes. Retired maintenance workflows dialihkan ke backend Turso. Local Streamlit boot XAU/EUR tested. Deployed dashboard version perlu verifikasi setelah merge, tidak diasumsikan dari local boot.

## Recommendation

**RESEARCH ONLY.** Simpan code, raw data, hasil gagal dan dashboard transparan. Jangan mengaktifkan signal maupun auto-trading. Prioritas riset berikutnya: intraday timestamped yields/yield spreads +actual broker bid/ask +historical macro calendar point-in-time, kemudian ulangi pre-registered WF/OOS dan full baseline counterfactual. Tidak ada angka contoh yang dilaporkan sebagai backtest nyata.
