# Audit macro XAU — tiga sinyal SELL 20 Oktober 2026

**Hasil rekonstruksi: ketiga kandidat SELL gagal filter macro beku, dengan status `XAU_MACRO_DIRECTION_BLOCK`.** Ini membuktikan keputusan fungsi macro menggunakan titik data yang direkonstruksi, bukan pembuktian pengiriman/penerimaan snapshot di terminal live pada waktu kejadian.

Sumber primer FRED dan ALFRED vintage **20 Oktober 2026** sudah diunduh dan disimpan, dengan checksum setiap file. Header vintage ALFRED cocok dengan tanggal yang diminta. Nilai titik yang relevan cocok antara FRED saat audit dan vintage ALFRED tanggal kejadian:

| Seri | Observasi sebelumnya | Observasi terpilih | Perubahan |
|---|---|---|---:|
| DGS10, nominal Treasury 10 tahun | 15 Oktober: 5,10% | 16 Oktober: 5,09% | −0,01 poin persentase |
| DFII10, real yield 10 tahun | 15 Oktober: 2,78% | 16 Oktober: 2,74% | −0,04 poin persentase |

Adapter yang benar-benar sedang dipakai bridge cocok SHA256 dengan source riset. Aturannya memberi jeda **dua hari kerja federal AS**, dihitung pada tengah malam America/New_York. Dengan aturan tersebut, titik observasi 16 Oktober baru dianggap layak digunakan engine mulai **20 Oktober 04.00 UTC / 11.00 WIB**. Ini batas ketersediaan MODEL engine, bukan klaim bahwa FRED baru menerbitkan data pada jam tersebut. Ketiga sinyal terjadi setelah batas itu.

Fungsi `ExternalOk` asli pada source XAU beku memilih **DGS10 untuk SELL**, DFII10 untuk BUY. Ia memblokir jika `side * Delta > 0`. Untuk SELL: `side = -1` dan `Delta DGS10 = -0,01`, sehingga hasilnya positif dan order ditolak oleh filter arah macro. SELL mengizinkan delta nol atau positif, bukan delta negatif.

| Sinyal SELL, 20 Oktober WIB | DGS10 terpilih | Hasil fungsi asli |
|---|---:|---|
| 19.05 | −0,01 | XAU_MACRO_DIRECTION_BLOCK |
| 19.40 | −0,01 | XAU_MACRO_DIRECTION_BLOCK |
| 20.55 | −0,01 | XAU_MACRO_DIRECTION_BLOCK |

Kalender FF dan BLS yang diambil saat audit berhasil diparse. Pada kalender rekonstruksi tersebut, tidak ditemukan event dalam keluarga NFP/CPI/PPI/JOLTS/ECI/FOMC pada jendela −30 menit hingga +495 menit masing-masing sinyal. Kalender ini diambil setelah kejadian dan bukan arsip delivery saat kejadian. Pada uji rekonstruksi, penolakannya berasal dari arah DGS10, bukan flag feed tidak tersedia atau blok kalender.

Sembilan uji fungsi macro asli selesai: tiga rekonstruksi lengkap ditolak, tiga kontrol yang mengisolasi yield dengan kalender diizinkan ditolak, dan tiga kontrol positif dengan delta DGS10 +0,01 lolos. Kontrol positif sepenuhnya sintetis, bukan nilai historis. Seluruh 16 source strategi dalam freeze manifest tetap cocok. Tidak ada order live atau perubahan parameter/strategi/bridge produksi.

**Implikasi untuk replay sebelumnya:** satu basket XAU muncul pada kontrol yang memberikan izin macro sintetis. Hasil itu tidak menunjukkan bahwa macro historis menyetujui SELL. Ketika titik historis yang relevan dimasukkan ke fungsi macro asli, izin SELL gagal pada ketiga waktu tersebut. Tidak adanya entry XAU tanggal 20 konsisten dengan aturan macro beku ini; tidak perlu menganggap BTC yang belum aktif sebagai penjelasannya.

DFII10 yang turun akan lolos syarat arah macro untuk BUY, tetapi tidak menciptakan setup BUY. Kandidat teknikal yang diperiksa adalah SELL, dan engine tidak otomatis membaliknya menjadi BUY.

**Batas bukti live:** pemeriksaan terarah mencakup 1.039 file pada folder state/bridge/hasil riset yang dicatat dalam JSON audit; batas pencarian tidak tercapai. Tidak ditemukan snapshot ber-ProducedUtc tanggal 20 Oktober pada arsip yang diperiksa. Log yang membuktikan snapshot tertentu benar-benar diterima terminal pada tiga waktu sinyal belum tersedia. Karena itu, penyebab operasional aktual tidak dinyatakan pasti atau tunggal. Namun, rekonstruksi data historis dan pengujian source memberikan alasan macro yang jelas dan teruji untuk menolak ketiga SELL.

Bukti:

- Actions: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39538488841 — completed/success.
- Artifact: RIZAN-OCT20-MACRO-GATE-AUDIT, ID 12318119655, 197.915 byte.
- SHA256 ZIP artefak asli: c57192cf06b856309ccfadca11480926865adec66b23a5b181f290863078d970.
- Source audit: 3a7b9cdbc5c49d9aee422693da6a9e5e06b14ef4; branch research/october-entry-audit-20261021.
- Folder riset VPS: /home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/october-macro-audit/run-39538488841/ . Produksi hanya dibaca.
- Seri resmi: https://fred.stlouisfed.org/series/DGS10 dan https://fred.stlouisfed.org/series/DFII10 . URL unduhan FRED/ALFRED yang tepat, waktu audit, header vintage, level, availability, dan checksum tersimpan dalam MACRO_RECONSTRUCTION_AUDIT.json.

Replikasi: checkout commit source audit, ikuti `.github/workflows/october-macro-audit.yml`, atau gunakan snapshot input tersimpan `MACRO_GATE_INPUT.json` lalu `dotnet run -c Release --project october_macro_audit/MacroGateReplay.csproj`. Pengujian fungsi memakai API stub terisolasi, bukan terminal/broker live. Untuk byte data yang sama, gunakan CSV dalam paket ini, bukan mengunduh versi terkini lagi.
