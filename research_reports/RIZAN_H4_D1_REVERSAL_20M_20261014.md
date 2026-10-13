# RIZAN — 20.000.000 konfigurasi reversal H4/D1
14 Oktober 2026 WIB

## Hasil
Replay20.000.000tuple selesai untuk2016–2025. Status **RESEARCH_ONLY**;
nol kandidat lolos semua syarat. Ini tidak membuktikan semua pola reversal
pasti rugi, tetapi keluarga/ruang parameter ini belum menghasilkan zona utama
dengan peluang tinggi dan profit stabil sesuai protokol.

Studi utama: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38456814232
Audit sensitivitas: https://github.com/rizanrizan93/Forex-scanner/actions/runs/38459249130
Source/protokol sebelum replay:c2731d7628918bf119b19395203c288798a4ac17.

## Pengujian baru
9sumber H4 dan1sumber D1:
OB3/6/12bar; pivot2/3/5bar kanan-kiri; range6/12/24H4; levelD1 sebelumnya.
OB mensyaratkan displacement body≥0,8ATR14H4 dan close BOS high/low3H4sebelumnya.
Zona berasal dari candle berlawanan terakhir dalamlookback. BUY low sampai
body-high; SELL body-low sampai high. Zona baru diketahui saat close BOS,
bukan waktu candle asal; invalid jika H4close melewati distal.
Pivot ekstrem unik baru diketahui setelah right-bars selesai; tanpa backdating.
Range memiliki usia dari ekstrem aktual terakhir, bukan direset tiap candle.

D1regime menggunakan close vsEMA50 dan arah EMA20 selama3dailycandle tertutup.
ANY/ALIGNED/OPPOSED/FLAT relatif terhadap arah. FLAT adalah kategori netral
operasional, bukan bukti sideways pasti. Definisi OB/sweep ini bukan bukti
transaksi institusi/bandarmology historis.

Konfirmasi5mode:TOUCH (kontrol belum terkonfirmasi), M5_RECLAIM,M15_RECLAIM,
M5_SWEEP,M15_SWEEP. Reclaim close melampaui proximal dengan body searah;
sweep juga melampaui distal. M15 lengkap15M1, dan zona harus sudah ada sebelum
M15membuka. Wick M15 untukmodeM15; wick M5 untukmode lain. MappingH4/D1
menggunakan informasi sebelumM5membuka.

## Grid20juta
2arah×10source×5padding×5stop×5target×4horizon×5wick×4regime×5usia×5konfirmasi×4sesi.
Padding0/0,025/0,05/0,1/0,2ATR H4. BufferSL0,05/0,1/0,2/0,35/0,5ATR H1.
TP25/35/50/75/100%ADR20. Horizon2/4/6/8jam. Wick0/20/35/50/65%.
Usia12/24/48/96/192jam. Sesi WIB07–13/13–19/19–01/01–07 (UTC tetap).
Exit paling lambat20:55UTC; sisa waktu entryminimal120menit.

SL di luar distal padded-zone dan ekstrem15menit terakhir, ditambah buffer
ATR H1. Entry next-M1open setelah trigger selesai. NetRRstress≥1,5 dan
target≥25%ADR20 untuk semua tuple. Target adalah formula penelitian,
bukan level opposing-zone live. Tidak mengklaim satu reversal setiap hari.

100shard tahun×source masing-masing mengolah2juta tuple/source/tahun;
ruangkonfigurasi tetap20juta, bukan200juta strategi. Tuple bisa berbagi keputusan.
Memori dibatasi dengan source streaming tanpa memangkas grid.

## Data dan biaya
3,492,721bidM1 di tahun2016–2025 pluswarm-up/buffer.
SHA256/rentangUTC tiap tahun tersedia diJSON. H4minimal180M1 perbar,
D1minimal900M1; EMA50D1 memerlukan50hari valid. Beberapa gap tetap ada.

| Model | Spread | Slippage per fill |
|---|---:|---:|
|Reference|0,25|0,05|
|Cautious untuk ranking|0,50|0,10|
|Stress|1,00|0,20|

HargaXAU/USDperounce, bukan returnakun. Biaya sintetis, bukan broker bid/askticks.
Tanpa lot/leverage/compounding/layering; tanpa overnight/swap.
Stop-first jikaTP/SLsamabarM1; adverse gap bisa loss>1R; deadlinequote harus tepat.
Gap>300detik/deadlinehilang dicensor. Firsteligible perconfig/hari setelahfilter;
censored first tetap mengklaim hari, tidak diganti berdasarkan outcome nanti.

## Seleksi dan audit
Train2016–2021, validation2022–2025. Periode ini sudah dilihat sebelumnya:
eksploratif, bukan pristineholdout. Ranking tertinggi berdasarkan Wilsonlower
bound deskriptif TP-before-SL di antara kandidat yang memenuhi semua gates.
Tidak ada koreksi confidence untuk20juta percobaan.

Train:n180/netpositif/PF1,15/5tahunpositif dengan≥15trade/tahun.
Validation:n60/PF1,20/stressmeanpositif/meanlowerboundpositif/3tahunpositif;
censored≤2% masing-masing. Tidak menurunkan ambang setelah hasil.

| Gate kumulatif | Tuple tersisa |
|---|---:|
|Train n≥180 dan validation n≥60|426.028|
|Train netpositif|3.012|
|PF train≥1,15|681|
|PF validation≥1,20|2|
|Expectancy stress validation positif|0|

Seluruh fold rolling2020–2025 juga tidak memilih kandidat.
Daftar utama terkunci kosong. Pipelineledger2026utama sukses tetapi kosong:
tidak ada trade kandidat utama2026 yang diuji.

## Kandidat peluang tertinggi dengan sampel cukup
Diagnostik dipilih setelah melihat validation, di antara ntrain180/nvalidation60.
Ini bukan probabilitas trading tervalidasi atau maksimum rawrate dari sampel kecil.

| Metrik | BUY | SELL |
|---|---:|---:|
|Sumber|LowD1sebelumnya|HighD1sebelumnya|
|D1regime|ANY|OPPOSED|
|Konfirmasi|TOUCH|TOUCH|
|JendelaWIB|13:00–19:00|19:00–01:00|
|Train n|194|194|
|Validation n|179|187|
|TP sebelum SL train|21,13%|23,71%|
|TP sebelum SL validation|30,73%|32,62%|
|Net-positiveWRvalidation|34,64%|35,29%|
|PFtrain|0,709|0,649|
|PFvalidation|0,993|1,054|
|Expectancyvalidation|−0,0046R|+0,0354R|
|Expectancystressvalidation|−0,181R|−0,333R|
|JarakTPvalidation rata-rata|12,91|9,25|
|JarakSLvalidation rata-rata|6,54|4,80|
|Censoredvalidation|13|11|

Kedua padded-zone0,2ATRH4 dan bufferSL0,5ATRH1. BUY target35%ADR/horizon8jam;
SELL target25%ADR/horizon6jam. Angka jarak adalah **USD/ounce/poin harga XAU**,
bukan dolar laba/rugiakun dan bukan harga entry hari ini.
CensoringBUY13/(179+13)=6,77%; SELL11/(187+11)=5,56%, melebihi2%.
Frekuensi validation terukur3,73BUY/bulan dan3,90SELL/bulan; bukan setupharian.
TOUCH tidak membutuhkan reclaim/sweep. Tidak menyebut jam ini waktu terbaik.

## Perbandingan semua keluarga
Contoh tertinggi tiap arah/source berdasarkan scoredeskriptif di antara
samplecukup; bukan seluruhsource maksimumPF dan bukan kandidat lolos.

|Arah|Source|D1|Konfirmasi|WIB|Ntrain|Nval|TP-hitval|PFtrain|PFval|
|---|---|---|---|---|---:|---:|---:|---:|---:|
|BUY|H4_OB_3|ANY|TOUCH|19–1|218|154|15.58%|0.527|0.932|
|SELL|H4_OB_3|ANY|TOUCH|19–1|181|104|18.27%|0.651|0.587|
|BUY|H4_OB_6|ANY|TOUCH|19–1|180|133|17.29%|0.618|0.686|
|SELL|H4_OB_6|ANY|TOUCH|19–1|187|127|20.47%|0.538|0.653|
|BUY|H4_OB_12|ANY|TOUCH|19–1|181|133|17.29%|0.613|0.686|
|SELL|H4_OB_12|ANY|TOUCH|19–1|187|127|20.47%|0.537|0.653|
|BUY|H4_PIVOT_2|ANY|TOUCH|19–1|215|174|20.69%|0.905|0.766|
|SELL|H4_PIVOT_2|ANY|TOUCH|19–1|243|175|27.43%|0.742|0.908|
|BUY|H4_PIVOT_3|ANY|TOUCH|19–1|181|150|21.33%|0.740|0.775|
|SELL|H4_PIVOT_3|ANY|TOUCH|19–1|194|139|27.34%|0.581|0.921|
|BUY|H4_PIVOT_5|ANY|TOUCH|19–1|194|138|10.87%|0.681|0.597|
|SELL|H4_PIVOT_5|ANY|TOUCH|19–1|180|117|18.80%|0.578|0.946|
|BUY|H4_RANGE_6|ANY|TOUCH|13–19|184|187|27.81%|0.674|0.972|
|SELL|H4_RANGE_6|OPPOSED|TOUCH|19–1|202|206|31.07%|0.562|0.967|
|BUY|H4_RANGE_12|ANY|TOUCH|19–1|226|198|22.22%|0.746|0.786|
|SELL|H4_RANGE_12|ANY|TOUCH|19–1|196|171|29.24%|0.538|0.955|
|BUY|H4_RANGE_24|ANY|TOUCH|19–1|204|140|20.71%|0.543|0.628|
|SELL|H4_RANGE_24|ANY|TOUCH|13–19|187|142|27.46%|0.457|0.825|
|BUY|D1_PREVIOUS|ANY|TOUCH|13–19|194|179|30.73%|0.709|0.993|
|SELL|D1_PREVIOUS|OPPOSED|TOUCH|19–1|194|187|32.62%|0.649|1.054|

Contoh H4 saja:BUY range6H4 TP-hitvalidation27,81%/PF0,972;
SELL range6H4 TP-hit31,07%/PF0,967. Keduanya masih ditolak.

## Dua tuple pivotH4 dengan PF historical positif
Audit tambahan memeriksa dua tuple yang sudah ada dalam20juta grid;
bukan konfigurasi baru dan tidak mengubah gates. KeduanyaBUY H4_PIVOT_2,
padding0,025ATRH4, bufferSL0,2ATRH1, target100%ADR20, M15_RECLAIM,
D1ANY, sesi19–01WIB, horizon8jam. Hanya usia maksimum berbeda96/192jam.

| Metrik | Usia96jam | Usia192jam |
|---|---:|---:|
|Ntrain|181|183|
|PFtrain|1,362|1,343|
|Nvalidation|122|122|
|PFvalidation|1,208|1,208|
|TP-hitvalidation|4,92%|4,92%|
|MeanRvalidation cautious|+0,123R|+0,123R|
|MeanRvalidation stress|−0,018R|−0,018R|
|TPvalidation rata-rata|32,29|32,29|
|SLvalidation rata-rata|7,34|7,34|
|NJan–Sep2026|28|28|
|PF2026|0,561|0,561|
|Net-positiveWR2026|28,57%|28,57%|
|TPfull-before-SL2026|0%|0%|
|MeanR2026|−0,309R|−0,309R|
|MeanstressR2026|−0,337R|−0,337R|
|TP2026 rata-rata|123,40|123,40|
|SL2026 rata-rata|23,58|23,58|
|MaxDD2026 dalamR|9,343R|9,343R|

Returnvalidation positif berasal juga dari market exit saat horizon berakhir;
tidak berartiTPpenuh sering tercapai. Target100%ADR terlalu jauh pada28trade2026
ini:tidak adaTPfullhit, tetapi ada8timeouttrade denganprofitbersih.
Usia96/192 berbagi seluruhtradevalidation/2026; bukan dua strategi independen.
Trainyearpositif4/6,censoredvalidation7/(122+7)=5,43%, meanLCBvalidationnegatif.
Gagal biaya stress,kestabilan,censoring danhasil2026. Tetap penelitian saja.

Sensitivitycandidate dikunci sebelum outcome2026 dihitung, berdasarkan PF
train/val yang sudah diketahui. Harga2026cached danperiode telah terpakai
di proyek lainnya; tidak mengklaim pristineholdout. N28 terlalu kecil untuk
kesimpulan generalisasi kuat. Ini auditdiagnostik; tidakpromosi.
Pipeline utama tidak memiliki2026trade; audit ini justru menguji28trade
pervarianresearch. Keduanya tidak boleh dicampur.

## Verifikasi dan scanner
20tests lulus lokal/jobunit; smoke satu source2juta tuple/14field selesai
dengan nilai finite. Syntheticdata smoke tidak masuk hasilhistoris.
100shard/lock/11ledger/verify utama sukses. Auditsensitivity akhir sukses.
Audit pertama berhenti karena unduhan lintasrun hanya melihat100artifactpertama,
melewatkan2018/2019; diperbaiki dengan namaartifact eksplisit10tahun.
Hasil20juta utama tidak dihitung ulang atau diubah karena perbaikanunduhan.

Scope/hashcBotXAU/EUR lulus; tidak ada perubahan strategy/execution/order.
Syntaxmain/panel lulus. CIumumrepository masih gagal importOrderSide; risetPASS
bukan seluruhCIhijau. UIStreamlit langsung belum diverifikasi.
Panel source terbaru memuat status20juta,diagnostik10keluarga, dan audit2026.
Tidak mempromosikan zona/SL/TP/liveforecast baru karena nol kandidat lolos.
Engine h4_d1_reversal.py menghitung zona kausal, tetapi model ini belum menjadi
feedgeometri live terkalibrasi. Tidak ada order atau perubahan VPSbridge.

## Kesimpulan ruang penelitian ini
H4/D1/OB/pivot/sweep sudah diuji sesuaigrid. Belum ditemukan titik balik
berpeluangtinggi sekaligus profitstabil. Perlu hipotesis berbeda untuk riset
berikutnya; memperbanyak tuple setara tidak menambah bukti.
