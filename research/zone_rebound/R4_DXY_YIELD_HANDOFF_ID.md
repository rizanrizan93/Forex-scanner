# RIZAN XAU Bounce Zone R4 — Riset DXY + Yield, handoff untuk Work

**Tanggal:** 18 November 2026 (WIB)  
**Status:** DESAIN EKSPERIMEN, BUKAN HASIL BACKTEST BARU. READ-ONLY.  
**Instrumen:** XAUUSD (FP Markets cTrader); BUY dan SELL simetris secara implementasi, hasil diuji terpisah.  
**Prioritas:** pantulan **USD 10/oz dari entry yang benar-benar mungkin dieksekusi**, bukan jarak dari low/high yang baru diketahui belakangan.  
**Larangan:** jangan mengubah Manual R3, Frozen V1, cBot LIVE, bridge, order path, risk, sizing, SL/TP atau aturan auto-trading. LIVE unlock = FALSE. Draft riset ini hanya memberi tugas kepada Work.

## 1. Baseline terverifikasi dan pelajaran

Referensi [FIXED10_ZONES_ID.md](FIXED10_ZONES_ID.md) pada commit a690a2b8d8f6f517912adc6481f43c87d656806d:

- Uji 146.849 *candidate events* historis M1; 18.560 aturan dan 111.360 rule–scenario. Kejadian dapat overlap: bukan 146.849 trade independen.
- Pada holdout 2025, kriteria pokok USD 10 sebelum adverse USD 10, <=240 menit, pemenang kelas zona+teknikal: **BUY 49/123 (39,84%)**; **SELL 54/143 (37,76%)**. Target >=80% belum didemonstrasikan.
- Break–retest struktural BUY 60/126 (47,62%); order block proxy BUY 70/149 (46,98%), SELL 65/148 (43,92%). Ini hipotesis family-to-investigate, bukan konfigurasi yang siap deploy.
- Riset sebelumnya memakai **EURUSD** sebagai proksi USD intraday, **bukan ICE DXY**; untuk yield memakai DFII10/DGS2/DGS10 harian dengan lag konservatif, **bukan yield tick atau minute-level**.
- Eksperimen baru harus membandingkan **pada entry waktu & geometri sama**: zona saja, zona+DXY, zona+yield, zona+DXY+yield. Jangan membandingkan pemenang berbeda lalu mengklaim peningkatan causal.
- DXY/US10Y hourly 2 tahun yang dilaporkan dalam pekerjaan Work belum dikonfirmasi tersimpan di repo dengan source/hash dan as-of; audit dan registrasi dulu sebelum uji.

## 2. Hipotesis utama: *zone acceptance*, bukan oversold sederhana

H0: setelah memperhitungkan biaya dan seleksi kausal, DXY/yield serta respons harga pada zona **tidak menambah** probabilitas target USD 10 secara out-of-sample dibanding zona identik tanpa macro.

H1A (TREND BUY): H1/H4 naik dan koreksi memasuki demand H1 yang belum dipakai, displacement asal + break of structure historis, ruang menuju supply lawan >= USD 12, momentum turun melambat, terjadi M5 reclaim/MSS, dan DXY/yield berubah dari menekan menjadi netral/menurun.

H1B (TREND SELL): kebalikan simetris H1A; tetapi hasil harus dipisah, tidak dilatih dengan membalik label secara sintetis.

H1C (REVERSAL BUY): sapuan low *previous session / previous day* ke demand yang telah dipublikasikan, candle kembali menutup di dalam range, M5 reclaim tanpa memasukkan candle yang belum close, divergence macro melonggar; hanya jika target USD 10 memiliki ruang.

H1D (REVERSAL SELL): sapuan high ke supply, reclaim turun, DXY dan/atau yield menguat pada timestamp yang valid.

H1E (FAILED BREAKOUT / S-R FLIP): breakout H1 yang sudah selesai, retest level baru setelah waktu konfirmasi, penolakan M5. Uji kelanjutan tren, jangan campur dengan pembalikan countertrend.

H1F (ABSORPTION / MOMENTUM DECELERATION): dalam 2–5 candle M5 menuju zona, range/velocity melambat dan gagal mempertahankan high/low baru; uji perbaikan marginal di atas A–E. Dari OHLC, istilah absorption hanya label proksi, bukan pembuktian limit order institusi.

Semua hipotesis adalah kandidat; **belum ada angka kemenangan untuk R4**.

## 3. Kontrak data yang wajib terpenuhi

### XAU & eksekusi
- M1 bid **dan ask** jika tersedia, UTC timestamp, source, gap, spread, DST, termasuk semua biaya aktual FP Markets. Tick bid/ask lebih disukai untuk kandidat final.
- Simpan `formation_close_ts`, `published_ts`, `first_touch_ts`, `confirmation_ts`, `entry_ts`; jangan pernah menggunakan data setelah `entry_ts` sebagai fitur.
- Harga BUY memakai ask saat entry dan bid saat exit; SELL memakai bid saat entry dan ask saat exit. Last-trade/high-low bid tunggal adalah batas eksploratif, bukan hasil live.
- Tombol atau halaman research **tidak** menghasilkan order.

### DXY/USDX
- **Prioritas ICE DXY/USDX** spot/index (atau futures dengan metadata kontrak dan roll) dengan rekaman tick/H1 timestamp. Bukti nama vendor dan hak guna serta apakah quote **index, spot synthetics, atau futures** wajib ada.
- Bila ICE DXY resmi tidak tersedia, **rekonstruksi 6 pasangan** sesuai bobot ICE hanya boleh diberi label `SYNTHETIC_DXY`; tidak boleh dinamai `ICE_DXY`. Beda spread/latency/konstituen dicatat.
- **EURUSD M1 bukan DXY**. Boleh menjadi kontrol ablation terpisah.
- Untuk as-of pada candle H1: hanya gunakan candle DXY yang sudah close; time lag dicatat. Jangan `ffill` tanpa batas, jangan memakai *current unfinished H1* seolah full close.

### Yield
- **US2Y/US10Y Treasury.gov harian** adalah *daily reference*, bukan feed intraday. Treasury menyatakan par-yield didasarkan pada indikasi kuotasi sekitar 15:30 ET tiap hari kerja dan dipublikasikan setelah itu. Tidak boleh dipakai untuk konfirmasi perubahan 5/15 menit.
- Untuk analisis intraday gunakan feed **quote UST 2Y / 10Y timestamped yang benar-benar intraday**, atau interest-rate futures dengan label proxy, kontrak, dan arah transformasi yield yang benar. Jika tidak ada, set `yield_intraday=UNAVAILABLE`; jangan membuat perubahan intraday fiktif.
- Bedakan nominal UST yields dari real yield TIPS (misalnya DFII10), dan kejutan kebijakan. Data FRED revisi terbaru tanpa vintage PIT hanya eksploratif.
- Setiap fitur menyimpan `source, event_timestamp, observed_timestamp, release_timestamp, ingested_at, age_sec, freshness_flag`.

### Rezim dan event
- Pasangkan `macro_regime` dengan korelasi rolling **returns/deltas**, bukan level; hitung dari data sampai t-1 saja. Jika hubungan emas dengan DXY/yield lemah atau positif, bobot filter inverse disusutkan/di-nonaktifkan; **jangan selalu memaksa XAU berlawanan dengan yields**.
- CPI, NFP, FOMC, PPI: terapkan *blackout* yang dibakukan sebelum riset, atau modelkan kategori event terpisah. Backtest tidak boleh menggunakan hasil actual news sebelum release.
- Semua waktu acuan UTC, tampilan WIB, zona America/New_York untuk publikasi Treasury/Fed dan DST.

Sumber primer: [ICE USDX Futures](https://www.ice.com/products/194/US-Dollar-Index-USDX-Futures), [ICE methodology](https://www.ice.com/publicdocs/data/ICE_FX_Indexes_Methodology.pdf), [US Treasury interest rate statistics](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/), [WGC gold dollar/yields](https://www.gold.org/goldhub/research/gold-market-commentary-january-2025).

## 4. Konstruksi zona tanpa lookahead

Simpan setiap kandidat zona sebagai objek dengan id deterministik dan `family, side, timeframe, proximal, distal, origin_ts, published_ts, expiry_ts, touch_count, status`:

1. **Base displacement** H1: base 1–4 candle yang sudah close, departure impulsif, break struktur yang diketahui saat itu; zona dari high/low base, bukan digambar ulang setelah berhasil.
2. **Order block proxy**: candle terakhir berlawanan sebelum displacement *yang sudah selesai*. Jangan menyimpulkan institusi dari OHLC.
3. **FVG**: 3 candle H1/M15 selesai; publikasi baru setelah candle ketiga tutup.
4. **Confirmed swing / previous day/session high-low**: ekstrem dari jendela selesai; confirmed pivots menunggu right-bars.
5. **Break–retest/flip**: level dengan breakout close terkonfirmasi, kemudian retest; *entry* baru setelah level dipublikasikan.
6. **Liquidity sweep origin**: sweeping lalu reclaim; zona dipublikasikan setelah reclaim, sehingga pengujian retouch berikutnya berbeda dari entry saat sweep itu sendiri.

Catat lebar zona dalam USD dan ATR, jarak ke zona lawan, jarak dari first touch ke konfirmasi, kedalaman touch, dan jumlah touch sebelumnya. Buat eksperimentasi *first-touch* vs *second-touch* di bucket terpisah.

## 5. Uji macro dan pembentukan skor

Unit analisis: `zone_id + touch_id`, bukan jumlah bar dari berbagai rule. Fitur kandidat:
- Geometri: kualitas departure, lebar zona/ATR H1, usia, touches, overlap HTF, jarak obstacle vs target.
- Perilaku pendekatan: kecepatan ΔXAU 5/15/30m, normalized extension dari H1 EMA, wick rejection/reclaim yang selesai, MSS M5/H1, *relative volatility*.
- DXY: ΔDXY 5/15/60m atau candle H1 lengkap; `zscore` kalibrasi TRAIN saja; slope dan *turn* hanya candle completed.
- Yield: ΔUS2Y/10Y bp 5/15/60m **hanya bila feed intraday nyata**; real yield daily sebagai rezim, bukan trigger menit.
- Macro *lead/lag*: bandingkan delta DXY/yield sebelum touch dan respons XAU 5/15 menit sebelum entry; hindari lag yang diketahui setelah entry.
- **Controls**: random matched entry same session/volatility/zone-distance; reverse-direction counterfactual; no-zone baseline; label leakage tests.
- Jika ada skor 0–100 di UI, judulnya **Skor Kualitas Setup**, bukan `probabilitas menang`. Probabilitas hanya boleh dari *calibrated* OOS model dengan CI.

Hanya beberapa parameter bebas dibuka per eksperimen. Pilih satu keluarga aturan dengan *nested rolling walk-forward*, simpan daftar kandidat dan semua kegagalan untuk mencegah cherry picking. Gunakan ablation pada **geometri/entry yang sama** saat macro ditambah.

## 6. Definisi hasil yang tidak boleh berubah setelah melihat label

Untuk tiap BUY/SELL yang benar-benar fill:
- `DIRECTION_1ST`: pertama mencapai +0,25 ATR vs -0,25 ATR dalam 60 menit. **Berbeda** dari pantulan USD 10.
- `TOUCH_GROSS10_H60_A5/A10/A20`, `TOUCH_GROSS10_H240_A5/A10/A20`: dari referensi touch yang diketahui saat itu; jangan sebut trade-win.
- `ENTRY_NET10_H60_A5/A10/A20`, `ENTRY_NET10_H240_A5/A10/A20`: dari executable entry sesudah konfirmasi, net spread/commission/slippage. **Ini metrik utama yang dapat ditranslasikan ke setup manual.**
- `MFE_USD/MAE_USD`, min-to-target, adverse-before-target, no-fill, timeout, gap, overlap, per tahun, BUY/SELL, session WIB, macro regime.
- Bila target dan adverse terjadi di candle M1 yang sama, fail/adverse-first kecuali tick mengonfirmasi urutan.
- Data stale/missing, unavailable intraday yield, gap, no-fill: kelompok tersendiri **dan** laporkan dampaknya pada coverage; jangan membuang kejadian gagal hanya karena datanya sulit.
- Baseline run harus identik dengan R3/Fixed10 reference jika input hash identik. DXY/yield add-on dievaluasi hanya pada cohort dengan sumber valid.

Acceptance untuk klaim akurasi >=80%: **n >=100 fresh, non-overlapping, out-of-sample trades per side** + lower 95% Wilson >=80%, biaya dan adverse yang realistis, tanpa mengubah definisi selama pengujian. Jika gagal: tampilkan hasil asli, frekuensi, jarak maksimum benar, dan alasan dominan kegagalan. Tidak menjanjikan angka.

## 7. Urutan kerja untuk Work (prioritas)

**P0 (audit, hasil dulu):** Lacak XAU M1/tick, DXY hourly dua tahun, US10Y hourly yang disebut pada sesi Work, provenance, completeness dan as-of. Apakah yield adalah intraday market quote atau data Treasury daily? Pastikan DXY asli, bukan EUR. Buat manifest SHA256 serta sample alignment anti-lookahead. Tampilkan ketidaksinkronan.

**P1 (pilot 2024–Mar 2026):** Implementasi fitur H1 zona, sweep/reclaim M5, acceptance + macro change point. Pertama backtest zona-only, lalu DXY, yield, gabungan dengan **event IDs tetap**. Ukur delapan label di atas, nilai BUY/SELL terpisah. Jangan gunakan 2025 untuk memilih parameter jika akan diklaim 2025 OOS; pilih blok lain.

**P2 (full-history & reproducibility):** Perluas DXY/yield kompatibel hingga 2019; bila tidak tersedia, **nyatakan pilot dua-tahun secara eksplisit**, jangan menyamaratakan hasil 2019–2026. Rekap tahunan, kontrol, CI, multiple-testing, median dan P90 MAE.

**P3 (shadow mode scanner):** Tampilkan tab *Bounce Zone R4 (Eksperimental)*, dua arah BUY/SELL, proximal/distal, usia, zone type, score quality, reason checklist, DXY / yield freshness, target +10, invalidation, dan status WAIT/TOUCH/RECLAIM/CONFIRMED/EXPIRED. Pertahankan Manual R3; jangan integrasikan ke cBot/frozen.

**P4 (promosi hanya berbasis evidence):** Tinjau stabilitas 2025/2026 dan out-of-sample data terbaru, serta replay tick. Jika belum memenuhi ambang, gunakan sebagai context/visual zone, **bukan sinyal >80%**.

## 8. Guardrail teknis

- Tidak ada import execution, bridge, dispatcher, cBot order handler dari modul `research/zone_rebound`.
- Semua eksperimen default `dry_run=true` dan `emit_order=false`; jangan menambahkan jalur live.
- Semua as-of joins `<= decision_timestamp`, dengan validasi timestamp *publish*, bukan hanya tanggal nilai.
- Test: late DXY candle, stale DXY, missing yield, CPI timestamp, DST rollover, duplicate timestamps, gap, same-bar target/adverse, buy/sell spread, no-fill, repeated-zone touches, reason checklist trace.
- Keluaran wajib: `manifest.json` source/hash, `trade_ledger.csv`, `ablation.csv`, `oos_annual.csv`, `calibration.csv` jika skor probabilistik, `failure_analysis.md`, screenshots success **dan** failure.

## 9. Literatur pendukung, bukan bukti 80%

- Carol Osler, NY Fed, [Support for Resistance](https://www.newyorkfed.org/research/epr/00v06n2/0007osle.html) dan [Currency Orders and Exchange Rate Dynamics](https://www.newyorkfed.org/research/staff_reports/sr125.html): pengelompokan order/level dapat mendorong reaksi *maupun* percepatan breakout.
- [World Gold Council, 2025](https://www.gold.org/goldhub/research/gold-market-commentary-january-2025): USD cenderung berhubungan terbalik dengan emas, hubungan yield lebih bervariasi.
- [S&P Global, 2025](https://www.spglobal.com/market-intelligence/en/news-insights/research/treasury-yields-and-gold-prices-breaking-expectations): emas dan yield dapat naik bersama dalam rezim tertentu.
- [CME Market by Order](https://www.cmegroup.com/articles/faqs/market-by-order-mbo.html): bukti order-book memerlukan feed transaksi/kuotasi, bukan OHLC XAU broker semata.

**Kesimpulan:** R4 belum teruji. Nilai tambah tahap ini adalah membetulkan definisi dolar/yield, memisahkan touch dari entry yang terlambat, mengukur real $10 outcome, dan menuntut ablation OOS. Pertahankan seluruh LIVE dan Manual R3 tanpa perubahan sampai evidence memenuhi kontrak.
