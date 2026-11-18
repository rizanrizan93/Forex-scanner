# RIZAN H1/H4 arah — audit R2 + R3 dan penolakan promosi 60%

Tanggal 18 November 2026 WIB. Status: **R2 selesai, R3 rolling + enam kandidat price action selesai sebagai diagnosa; tidak ada yang memenuhi akurasi arah 60% dengan kelayakan yang cukup.** Tidak boleh mengaktifkan sinyal LIVE atau mengubah Frozen V1 / Manual R3.

## Metrik utama 2025–2026 (setiap BUY dan SELL berdiri sendiri)

Semua angka adalah **akurasi arah setelah skenario biaya $0,50/ons**, pada menit akhir horizon H1 (60m) atau H4 (240m). Ini bukan peluang pantulan $10, win rate trading eksekusi FP Markets atau probabilitas terkalibrasi.

| Model | H1 BUY | H1 SELL | H4 BUY | H4 SELL |
|---|---:|---:|---:|---:|
| Frozen R1 (PR #881) | 50,00%, n824 | 45,81%, n465 | 53,30%, n182 | 57,39%, n115 |
| R2 statis, seleksi 2024 (PR #882) | 48,57%, n4309 | 45,12%, n1168 | 49,73%, n374 | 47,02%, n604 |
| R3 logistic rolling, seleksi 2024 (diagnostik) | 47,07%, n495 | 42,31%, n104 | 50,60%, n502 | 48,54%, n410 |

**R2 (run 44240141371):** seluruh 8 tahun 2019–2026 dan aggregator berhasil, dengan SHAs input tahunan dan ledger feature/label. Model R2 dipilih menggunakan 2024; hasil pengujian 2025–26 jauh dari 60% kedua sisi. R2 H1 seleksi LOGIT threshold 0.52 ALL, validasi 2024 BUY 48,44% (n1311), SELL 41,37% (n1303). R2 H4 HGB threshold 0.52 ALL, validasi BUY 52,02% (n248), SELL 43,41% (n311).

**R2 train H4 (2019–2023) saja:** BUY 61,62% (n1368), SELL 64,74% (n953). Hasil yang terlihat >60% pada in-sample **runtuh** saat validasi 2024 dan test 2025–26. Ini bukti risiko overfit/regime shift, BUKAN penemuan strategi 60%.

**R3 rolling diagnostik:** fitur dan label sama persis dari shard R2, model LogisticRegression(C=0.1) refit kuartalan menggunakan hanya **12 atau 36 bulan masa lalu**, membuang training label yang belum jatuh tempo sebelum refit; 2024 memilih window/threshold/gate, 2025–26 dievaluasi. R3 H1 terpilih window12 threshold 0.55 filter TF_MOMENTUM; R3 H4 window12 threshold 0.55 ALL. Tidak mencapai target.

**Enam hipotesis SMC/price action eksploratif:** BOS continuation, HTF trend pullback, sweep-zone reclaim proxy, momentum persistence, overextension reversal, breakout rejection. Pada test 2025–26 H1 sweep proxy BUY 70,59% (12/17) tetapi SELL hanya 42,11% (8/19); validasi 2024 n9 per sisi. **Dilarang mempromosikannya sebagai sinyal 70% karena terlalu sedikit kejadian, asimetris, dan post hoc.** H4 BOS continuation SELL 59,74% (46/77), BUY hanya 51,01% (76/149). Semua metode gagal memenuhi 60% di kedua sisi dengan dukungan lintas tahun.

## Kontrol tanpa model (semua jam dengan horizon lengkap)

| Periode | H1 selalu BUY | H1 selalu SELL | H4 selalu BUY | H4 selalu SELL |
|---|---:|---:|---:|---:|
| 2024 | 45,43% | 40,49% | 51,34% | 42,11% |
| 2025–26 | 47,58% | 45,88% | 49,12% | 48,11% |

Kontrol memperhitungkan gerakan arah setelah $0,50, bukan win rate tanpa biaya; nilai dapat tidak menjumlah 100% karena gerakan lebih kecil dari biaya membuat kedua arah gagal.

## Keterbatasan audit

- HistData public XAUUSD M1, konversi fixed EST ke UTC oleh importer proyek; bukan spread/komisi/quotes FP Markets. **Data 2026 berakhir 13 Nov 2026 pukul 21:58 UTC**, bukan 18 Nov.
- R2 full historical 2019–26 terbukti sukses di workflow; R3 dan enam keluarga memakai 8 archive feature yang diunduh dari run R2, bukan fetch alternatif independen. Setiap signal tercipta dari completed candles.
- Tabel currency_macro_state di Supabase ForexRizan hanya 56 observasi 2 Sep–6 Okt 2026. **Tidak tersedia histori DXY, US2Y dan US10Y intraday point-in-time 2019–26** pada database tersebut. Jangan mengklaim telah menguji macro delapan tahun.
- Validasi 2025–26 sudah berkali-kali diperiksa oleh R1, R2, R3 dan penelitian terdahulu; **tidak boleh lagi disebut holdout proyek yang pristine**. Perlu blok forward yang benar-benar baru untuk klaim berikutnya.
- Proksi sweep berdasarkan OHLC/ATR bukan bukti hidden order institusional. Penelitian post-hoc atas keluarga kecil dapat meng-overfit, terutama 17–19 observasi.

## Prioritas berikutnya (tidak mengubah LIVE)

1. **Macro provenance first:** cari lisensi/feed ICE DXY/USDX (atau synthetic USDX diberi label jujur) dan US2Y+US10Y market quotes yang memiliki timestamp publikasi/as-of per menit/H1; tentukan tahun awal yang benar-benar tersedia. Daily Treasury/FRED tidak sah sebagai yield intraday.
2. **Conditional direction, bukan always-on:** deteksi zona H1/H4 pra-sentuh, sweep dan reclaim M5 yang telah close, jarak ke zona lawan, kondisi breakout/failed-breakout dan momentum melambat. Tambahkan DXY/yield melalui same-event ablation, lihat apakah coverage dan kualitas arah meningkat TANPA memindahkan waktu entry setelah melihat hasil.
3. **Regime shift:** ukur rolling correlation return XAU–DXY dan yield, volatilitas relatif, sesi, dan jadwal makro; rezim boleh negatif/positif. Jangan memaksa inversi XAU dengan yield ketika tanda relasi berubah.
4. **Pre-register** aturan dan biaya, data manifest, batas n dan confidence interval sebelum evaluasi; validasi forward setelah 13 Nov 2026 memakai data benar-benar belum pernah diperiksa. Gate praktis: >=60% BUY DAN SELL, n memadai (misalnya >=100 sinyal independen per sisi), hasil lintas 2024/2025/2026 tidak terkonsentrasi dalam satu tahun, dan batas bawah CI tidak dekat 50%.
5. Setelah arah terbukti, baru masuk penelitian pantulan USD10 dari entry sebenarnya. Jika belum terbukti, tampilkan WAIT / research panel, bukan BUY/SELL dengan skor seolah 80%.

Referensi macro: World Gold Council Gold Market Commentary January 2025 (regime-dependent gold/yield correlations), dan IMF Gold in Central Bank Reserves 2026 (perbedaan jalur real yield, USD dan permintaan safe haven).

**Keputusan:** R1 tetap baseline; R2 dan R3 gagal promosi; cBot LIVE, bridge dan Manual R3 tetap tidak diubah. Tidak ada akurasi >=60% kedua sisi yang dapat dipercaya untuk H1/H4 dari hasil saat ini.
