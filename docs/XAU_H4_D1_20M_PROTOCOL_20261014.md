# RIZAN XAU H4/D1 — 20.000.000 konfigurasi reversal
14 Oktober 2026 WIB. Protokol dikunci sebelum replay. Scanner-only; tanpa order.

Keluarga baru: H4 OB pada displacement/BOS, pivot H4 terkonfirmasi, range H4,
serta high/low D1 sebelumnya. Regime D1 dihitung dari daily candle tertutup:
close vs EMA50 dan slope EMA20 tiga candle. ANY/ALIGNED/OPPOSED/FLAT terhadap
arah reversal. Ini definisi operasional penelitian, bukan bukti order institusi.

OB: body H4 searah ≥0,8 ATR14 H4 dan close menembus high/low tiga H4 sebelumnya;
zona berasal dari candle berlawanan terakhir dalam3/6/12H4 sebelum trigger.
BUY low sampai body-high; SELL body-low sampai high. Terbentuk pada close BOS,
bukan timestamp candle asal. Invalidation saat H4 close melewati distal.
Pivot: ekstrem unik dengan2/3/5bar kiri dan kanan; diketahui baru pada close
right-bars. Range:min/max6/12/24H4. Usia range dari ekstrem aktual terbaru,
bukan direset setiap H4. Semua mapping HTF diketahui sebelum M5 membuka.

Grid tepat2×10×5×5×5×4×5×4×5×5×4=20.000.000 tuple:
side2;source10; padding0/0,025/0,05/0,1/0,2ATR H4; bufferSL0,05/0,1/0,2/0,35/0,5
ATR H1; target25/35/50/75/100% ADR20; horizon2/4/6/8jam; wick0/20/35/50/65%;
D1regime4; maxage12/24/48/96/192jam; confirmation5; session4.
Konfirmasi:TOUCH,M5_RECLAIM,M15_RECLAIM,M5_SWEEP,M15_SWEEP.
TOUCH termasuk belum berbalik sebagai kontrol; reclaim membutuhkan close
melewati proximal dengan body searah. Sweep juga melewati distal. M15 harus
lengkap15M1 dan anchor sudah ada sebelum M15 membuka. Wick M15 untuk mode M15;
M5 untuk mode lain. SL di luar distal padded zone dan ekstrem15menit terakhir,
lalu bufferATR H1. Entry next-M1 open setelah trigger. RRstress minimum1,5
untuk semua tuple; target≥25%ADR20. Tidak mengejar bounce kecil0,5ATR saja.

Sesi WIB07–13/13–19/19–01/01–07, fixed UTC. Exit≤20:55UTC dan waktu tersisa
minimal120menit; horizon8jam tidak melewati batas tersebut. Pertama eligible
per arah/config/hari setelahfilter; censored first tetap klaim hari. Bar
ambigu stop-first; adverse gap mengisi stop lebih buruk; deadline quote tepat.
Gap>300detik dicensor. Spread/slippage sintetis0,25/0,05;0,50/0,10;1,00/0,20.
R adalah risk penelitian, bukan return akun. Tidak lot/leverage/compounding.

2016–2025 terdiri100shard (10tahun×10source), masing-masing2juta tuple source.
Total20juta konfigurasi, bukan200juta strategi, dan banyak tuple bisa berbagi
keputusan. Source streaming membatasi RAM dan preserves seluruh grid.
Training2016–2021; validation2022–2025 sudah dilihat sebelumnya, eksploratif.
Gates:train n180/PF1,15/netpositif/5tahunpositif; validation n60/PF1,20,
stressmeanpositif/descriptive meanLCBpositif/3tahunpositif; censored≤2%.
Ranking utama:descriptive Wilson lower bound TP-before-SL di antara eligible.
Multiple search confidence belum terkoreksi. Diagnostik unqualified tetap
berlabel penelitian. Winrate net positif berbeda dari target-hit rate.

Kandidat dikunci sebelum outcomesJan–Sep2026; prices2026 sudahcached. Test2026:
n30/PF1,20/mean danstresspositif/month-blockCIbawah>0/censored≤2%.
Rolling2020–2025 hanya menggunakan tahun sebelumnya untuk seleksi.
H4 minimum180M1/candle; D1 minimum900; EMA50D1 memerlukan50dailyvalid.
Macro/event tidak dipakai tanpa histori initial-publication-time yang terverifikasi.
Tidak ada probabilitas titik balik pasti atau reversal dijamin setiap hari.
