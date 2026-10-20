# Pemeriksaan kebutuhan makro BTC — 20 Oktober 2026

Kesimpulan: prioritas riset berikut adalah risk appetite pasar saham AS dan stres pasar, ditambah konfirmasi repricing suku bunga/dolar. Makro belum terbukti meningkatkan profit strategi BTC ini. Tidak ada perubahan pada cBot beku, bridge produksi, risiko atau trading live.

## Bedakan arah, waktu, dan harga entry

Makro harian/mingguan menilai konteks risk-on/risk-off, bukan menetapkan harga atau menit entry. Harga entry tetap memerlukan sinyal harga closed-bar. Untuk challenger baru, reaksi harga pasca-rilis dan konfirmasi struktur harus diuji terpisah dari filter arah. FOMC/CPI/NFP bukan sinyal BUY atau SELL mekanis; konsensus yang tersedia sebelum rilis dan data aktual saat publikasi diperlukan jika menguji surprise. Tanpa arsip konsensus, uji reaksi harga setelah rilis, bukan surprise buatan.

## Prioritas data

| Data | Fungsi riset | Keterbatasan |
|---|---|---|
| S&P 500 atau Nasdaq + VIX | Konteks risk appetite dan perubahan stres; jangan hitung beberapa indeks berkorelasi sebagai bukti independen | Korelasi dengan BTC berubah; VIX adalah volatilitas opsi saham, bukan arah BTC |
| DXY tradable/intraday + yield AS 2 tahun | Konfirmasi dolar dan repricing ekspektasi kebijakan | Yield2y juga mencerminkan faktor lain; bukan ukuran murni ekspektasi Fed. Fed broad dollar bukan DXY dan publikasinya mingguan |
| FOMC, CPI, NFP + reaksi harga | Menentukan kapan menunggu dan kapan evaluasi ulang sinyal setelah rilis | Waktu UTC harus mengikuti DST. Rilis tidak otomatis memberi arah. Belum ada arsip konsensus tervalidasi |
| Fed balance sheet, Treasury cash, RRP | Konteks likuiditas lebih lambat | Campuran frekuensi, unit dan waktu publikasi harus diselaraskan; proksi net liquidity bukan saldo uang yang otomatis masuk BTC |
| Arus ETF spot BTC AS | Permintaan institusi setelah produk tersedia | Data baru mulai era ETF2024, bukan input2019. Perubahan AUM mencakup perubahan harga, bukan net flow murni. Gunakan data setelah benar-benar dipublikasikan |
| Funding, open interest, basis | Posisi/leverage pelaku dan risiko squeeze | Ini data turunan/posisi kripto, bukan makro murni. Funding positif tidak otomatis SELL; OI naik tidak menyatakan arah |

## Bukti dan konflik riset

CME melaporkan meningkatnya korelasi BTC dengan ekuitas sejak2020, tidak khusus Nasdaq. Working paper Chicago Fed2026 menemukan eksposur BTC terhadap sentimen saham luas; eksposur tambahan Nasdaq menjadi tidak signifikan setelah mengendalikan Dow Jones. Karena itu Nasdaq bukan satu-satunya leader yang harus dipaksakan.

New York Fed2023 menemukan respons intraday BTC terhadap kejutan makro tidak kuat dalam sampel penelitiannya. IMF2023 membahas transmisi kebijakan moneter melalui risk appetite dan siklus kripto. Perbedaan horizon/sampel ini penting: konteks siklus dapat relevan tanpa membuat setiap event menjadi sinyal entry yang andal. Working paper bukan jaminan hubungan kausal yang stabil.

## Pemeriksaan data aktual

Data telah diunduh dan diperiksa dari FRED, sampai cutoff portfolio9 Oktober2026:

- NASDAQ100:2.206 observasi valid sejak2 Januari2018.
- VIXCLS:2.238 observasi valid sejak2 Januari2018.
- DGS2:2.194 observasi valid sejak2 Januari2018.
- Ketiganya tersedia pada107 peluang sinyal BTC lama dengan asumsi lag konservatif dua hari kerja federal AS, dan tidak memakai observasi dengan waktu ketersediaan setelah sinyal.
- Ini historical current-vintage, belum sertifikasi point-in-time/ALFRED. Tidak dipakai sebagai sinyal menit yang sama.

Satu temuan penting: H.10 Fed memublikasikan nilai harian dolar untuk minggu sebelumnya pada Senin16:15 waktu AS, atau hari kerja berikutnya bila libur. Oleh karena itu tanggal observasi tidak sama dengan tanggal data tersedia. Memakai nilai dolar hari ini dalam replay hari ini akan menimbulkan lookahead.

## Diagnostik terbatas, bukan replay baru

Dua hipotesis tetap diperiksa pada peluang sinyal dan transaksi baseline yang sudah terjadi:

1. RISK_VETO: arah Nasdaq20 observasi berlawanan dengan sisi trade dan perubahan VIX5 observasi juga berlawanan.
2. TRIPLE_VETO: kondisi di atas ditambah perubahan yield2y20 observasi berlawanan dengan sisi trade.

RISK_VETO menandai19 dari107 sinyal. Di setiap path baseline,17 transaksi aktual masuk kelompok ini dan11 di antaranya menang. Jadi bahkan kombinasi Nasdaq/VIX tidak boleh dianggap sebagai filter penolak yang otomatis menghapus transaksi buruk.

TRIPLE_VETO menandai8 sinyal, mencakup7 transaksi baseline per path; sampelnya terlalu kecil untuk menyimpulkan edge. Rincian tersedia dalam CONDITIONAL_DIAGNOSTIC.csv.

Ini hanya klasifikasi transaksi lama. Tidak ada saldo akhir atau DD baru yang dihitung. Menghapus lalu menjumlahkan ulang PnL kelompok lama tidak mereplikasi compounding, margin, dan kesempatan entry portfolio baru.

## Kandidat arsitektur penelitian

- MacroContext: dukungan BUY, dukungan SELL, atau campuran, dengan umur data dan kualitas sumber.
- EventState: normal, menunggu rilis, atau menunggu konfirmasi reaksi. Hindari blok24jam seragam yang sebelumnya menurunkan profit.
- PriceTrigger: sinyal teknikal closed-bar tetap menjadi pemicu; untuk entry berbasis sweep/displacement/retest diperlukan challenger dengan replay terpisah, bukan mengubah label strategi lama.
- Execution: spread, slippage, margin bersama, SL/TP dan Friday-flat tetap diperiksa.

Prioritas uji yang masuk akal: perbandingan baseline vs konteks risk appetite, lalu tambahan dolar/yield2y, kemudian reaksi pasca-event. Jangan sekaligus menambahkan semua filter sehingga tidak diketahui mana yang membantu. Wajib menilai tiap tahun, BUY/SELL, biaya/delay, serta saldo dan floating DD portfolio bersama. Semua data harus tersedia pada saat sinyal. Jangan mempromosikan ke live dari diagnostik ini.

## Source

- https://www.cmegroup.com/insights/economic-research/2025/why-is-bitcoin-moving-in-tandem-with-equities.html
- https://www.chicagofed.org/publications/working-papers/2026/2026-16
- https://www.newyorkfed.org/research/staff_reports/sr1052
- https://www.imf.org/en/publications/wp/issues/2023/08/04/the-crypto-cycle-and-us-monetary-policy-534834
- https://fred.stlouisfed.org/series/NASDAQ100
- https://fred.stlouisfed.org/series/VIXCLS
- https://fred.stlouisfed.org/series/DGS2
- https://www.federalreserve.gov/releases/h10/
- https://www.federalreserve.gov/releases/h41/default.htm
- https://www.bls.gov/schedule/2026/home.htm
- https://www.sec.gov/newsroom/speeches-statements/gensler-statement-spot-bitcoin-011023
- https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf

Riset profit sebelumnya: Actions39382525371, commit1b1bd63f1d5633da4bc2caaffaf8dae39737e5a2. Filter yield riil/FOMC lama gagal meningkatkan saldo kedua path. Pemeriksaan kebutuhan ini tidak menggantikan hasil tersebut.
