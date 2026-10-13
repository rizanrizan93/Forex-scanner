# RIZAN — 20 keluarga alternatif, 20.000.000 kombinasi
14 Oktober2026WIB. Protokol sebelum replay; scanner-only, tanpa order/cBot.

Tujuan: menemukan aturan reaksi/titikbalik intraday yang profit sesudahbiaya.
Reaksi searahtrend setelahpullback tidak otomatis berarti pembalikantrendD1.
Jumlah20juta adalah tuple parameter dari20definisi operasional, bukan20juta
strategi independen. Beberapa parameter bisa berbagi keputusan.

## Definisi keluarga
|Source|Aturan dasar|
|---|---|
|H1_BB20/H1_BB40|M5close kembali ke dalam band H1 mean±2std20/40 setelahpreviousM5close di luar; body searah|
|H1_KELTNER20|Re-entry EMA20H1±1,5ATR20H1 denganbodysearah|
|H1_LINEAR48|Re-entry fitted lineartrend48H1±1,5stdclose|
|H1_DONCHIAN24|Reclaim extreme24H1 denganbodysearah|
|M15_RSI7/14|RSI sebelumnya≤35BUY/≥65SELL, RSIberputar danbodyM15searah|
|M15_ROC16|NormalizedROC16M15 melewati±2ATR15 lalu berputar denganbodysearah|
|M15_ATR_STRETCH12|HargaM15 >1ATRH1 di sisi berlawanan mean12M15, body berbalik|
|M15_CLIMAX|CandleM15sebelumnya range>1,5ATR15 denganbodyberlawanan, candle berikutnya body/close berbalik|
|ASIA_FALSE_BREAK|Sweep lalu reclaim range00–06UTC yang sudah selesai|
|EUROPE_FALSE_BREAK|Sweep lalu reclaim range06–12UTC yang sudah selesai|
|NY_OPENING_FADE|Sweep lalu reclaim range12–13UTC, proxy openinghour tetap|
|PREV_D1_FAILED_BREAK|M5sweep/reclaim high/lowD1tertutup sebelumnya|
|D1_OPEN_STRETCH|Harga bergerak >25%ADR20 dariUTCdayopen melawanarahentry, kemudianbodyM5berbalik|
|M15_DOUBLE_SWEEP|Sweep/reclaim extreme8M15, setelahsweepsearah lain dalam8M15sebelumnya|
|M15_BREAKER|Failedclosebreak extreme8M15 laluclose kembali melalui levelbreak dalam4candle|
|H1_FVG_FILL|ThreecandleH1gap bullish/bearish sudahterbentuk; M5touchgap danreclaimproximal; gapinvalid jikaH1close melewatidistal|
|H1_FAILED_BOS|Closebreak extreme12H1 laluclose kembali melalui levelbreak dalam2H1; signal hanya setelahH1tertutup|
|M15_COMPRESSION_FADE|8rangeM15sebelumnya rata-rata<0,65ATR15, lalu sweep/reclaim extreme8M15|

Breaker/FVG/failedBOS adalah definisioperasional OHLC penelitian, bukan bukti
transaksi institusi atau implementasi sempurna seluruh modelICT.
NY12–13UTC adalah proxy tetap, bukan jam resmi NYSE/DST.
Semua bandH1 diketahui sebelumM5membuka; M15signal hanya pada candle lengkap.
ADR20 danD1regime dari dailyUTCtertutup. D1:closevsEMA50 danEMA20slope3hari;
ANY/ALIGNED/OPPOSED/NEUTRAL. H1bias:closevsEMA20H1.

## Grid
2arah×20family×2entry×5SL×5TP×5horizon×5strength×5confirmation×4D1×5phase×4session
=20.000.000tuple. Masing-masingfamily1juta tuple.
SL diluar low/high M5trigger +0,25/0,5/0,75/1/1,5ATR14M5.
TP15/25/35/50/75%ADR20; horizon60/120/240/360/480menit.
Target15%ADR berbeda dari batas25%batchsebelumnya:keluarga reactionmedium
ikut diuji dan persentase antarjarak tidak langsung sebanding.
NetRRstress≥1,5 pada plannedentry untuk semua tuple.

Strength0/0,5/1/1,5/2 menggunakan scorefamily masing-masing:bandpenetration/ATRH1,
RSIovershoot10point, ROCovershoot, rangeclimax excess, session/sweepdepth/ATRH1,
atau D1openstretch/25%ADR. ScoreantarFamily tidak dianggap ukuran identik.
Confirmation:BASE, M5body≥0,25ATR5 searah, completedM15bodysearah,
M5sweep/reclaim previous12M5extreme, H1biasaligned.
Phase dalam6jam:ALL,FIRST60,SECOND60,MIDDLE120,LAST120.
SessionsUTC00–06/06–12/12–18/18–24 (WIB07–13/13–19/19–01/01–07).
Exit≤20:55UTC; waktu remaining pada signalsminimal60menit.

## Dua entry policy
NEXT_M1:marketreference pada openM1setelahsignals.
RETEST50_TOUCH:wait bidmidpoint(open+close)/2M5trigger selama≤30menit;
modelmarket-on-touch, bukan brokerlimitfillpasti. Fill reference tetaplevel
rencana ditambahspread/slip; intrabarfills tidak boleh mengambilTP darihigh/low
candlefill yang urutannya tidakdiketahui. Stop-first tetapdiberlakukan.
Gapopeningstop mengisi exit lebihburuk. Deadlinequote harusada tepat.
Pendingtimeout=-7:notfilled. Gapdata>300detik=-9:censored.
Firstknowneligible intent mengklaim hari meski unfilled/censored; tidak mengganti
menggunakan hasil future. WR/TP-hit dihitung daritradeterukur, bukan pendingmiss;
notfilled/fillrate dilaporkan terpisah. Peluang bersyarat pada trigger/filter/fill.

Biayasintetis reference0,25/0,05; cautious0,5/0,1; stress1/0,2 spread/slipperfill.
M1bidOHLC, bukan brokerhistoricaltick. Tidak lot/leverage/compounding/layering.
Tidak ada data DOM/macro/event initialpublication terverifikasi.

## Pemisahan dan ranking
2016–2025:train2016–2021;validation2022–2025 telahdilihat, eksploratif.
Train n180/netpositif/PF1,15/5tahunpositif n15pertahun;validationn60/PF1,2,
stressmeanpositif/descriptiveLCBmeanpositif/3tahunpositif; censored≤2%.
Rankingutama:WilsonlowerbounddeskriptifTP-before-SL amongeligible; bukan
confidence terkoreksi20juta percobaan. Diagnostik terbaik tidak dipromosikan.
Rolling2020–2025 hanya memilih dengan tahunsebelumnya.

Parameterdikunci sebelumoutcomeJan–Sep2026;prices2026cached danperiodepernah
tersedia untukproyeklain, bukanpristineholdout. Test n30/PF1,2/mean&stresspositif/
monthblockCIbawah>0/censored≤2%. Target15%ADR kandidat tidak disebut majorreversal
hanya berdasarkanpersentase; tampilkanjaraknyata/frekuensi/horizon.
200shard (20family×10tahun),20sourcelock,1globallock,11ledger danverify.
Downloadartifact berdasarkanname untukmencegah potong100artifactpertama.
