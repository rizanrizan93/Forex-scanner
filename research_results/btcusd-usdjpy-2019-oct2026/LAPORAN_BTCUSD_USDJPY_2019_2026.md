# RIZAN — BTCUSD dan USDJPY, pencarian setup2019–15Oktober2026

**Status: TARGET_NOT_FOUND_IN_TESTED_UNIVERSES. Validitas eksekusi broker: NOT_VALIDATED.**

Setiap instrumen dimulai dariUSD100 tanpa topup, pada akun riset terpisah. Periode akhir2019-01-01–2026-10-15 23:59UTC. Tiga universe masing-masing1.000.000 tuple per instrumen telah dijalankan langsung padaM1: GENERIC, SESSIONS, POSITION. Total6.000.000 penilaian periodepenuh, gabunganunikBTC2,998,022 danUSDJPY2,998,022 setelah overlapparameterH4 dihapus. Ini24keluarga aturan dasar dengan kombinasi parameter; bukan jutaan keluarga statistikindependen. Pengulangan periodeMaret/Oktober tidak dihitung sebagai konfigurasi baru.

## Hasil utama — pemilihan historis, belum bukti keuntungan broker

| symbol | criterion | variant | id | family | equity | floating_dd | pf | win_rate | trades | adds |
|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSD | FULL | POSITION | 792291 | structure_break | 85,424.59 | 58.44 | 1.55 | 30.38 | 79 | 0 |
| BTCUSD | DD50 | POSITION | 682607 | displacement_follow | 10,978.90 | 49.30 | 1.45 | 56.94 | 72 | 0 |
| BTCUSD | TRAIN | GENERIC | 500406 | displacement_follow | 11,418.38 | 85.61 | 1.04 | 47.98 | 669 | 0 |
| USDJPY | FULL | GENERIC | 496711 | compression_break | 11,285.81 | 56.67 | 1.34 | 52.20 | 295 | 223 |
| USDJPY | DD50 | GENERIC | 578508 | break_retest | 2,701.38 | 48.58 | 2.15 | 61.54 | 26 | 21 |
| USDJPY | TRAIN | GENERIC | 514964 | structure_break | 266.40 | 94.23 | 1.03 | 57.26 | 117 | 0 |

FULL memilih saldo tertinggi pada seluruhperiode. DD50 memilih saldo tertinggi denganDDmodel<50%. TRAIN memilih hanya berdasarkan2019–2022, lalu menampilkan kinerja periodepenuh. PemilihanFULL/DD50 menggunakan seluruhhistory dan bersifat eksploratif. HasilTRAIN/validasi/test bukan holdoutprospektif yang belum pernah dilihat; sejarah pasar ini telah diteliti sebelumnya.

Jumlah targetUSD100.000 pada setiap universe, termasuk semua jumlahtrade:

| symbol | variant | configurations | target100k_any_trade_count | target100k_dd50_min30trades | profitable_fraction | best_any_trade_count_equity |
|---|---|---|---|---|---|---|
| BTCUSD | GENERIC | 1000000 | 0 | 0 | 0.18 | 18,046.40 |
| BTCUSD | POSITION | 1000000 | 0 | 0 | 0.22 | 85,424.59 |
| BTCUSD | SESSIONS | 1000000 | 0 | 0 | 0.08 | 1,396.68 |
| USDJPY | GENERIC | 1000000 | 0 | 0 | 0.09 | 11,285.81 |
| USDJPY | POSITION | 1000000 | 0 | 0 | 0.10 | 3,981.56 |
| USDJPY | SESSIONS | 1000000 | 0 | 0 | 0.04 | 8,642.16 |

Tidak ada penghapusan konfigurasi rugi. Seluruhmillion-rowfile tersedia; kandidat mentah dengan sedikittrade juga diperiksa. Saldo dan drawdown disajikan sesuai model, tanpa perubahanfee atau peningkatanrisk untuk memaksakan target.

## Ketahanan biaya dan leverage untuk pemimpin setiap kriteria

| symbol | criterion | id | equity | COST1_5_equity | COST2_equity | DELAY_NEXT_M1_equity | LEVERAGE2_equity |
|---|---|---|---|---|---|---|---|
| BTCUSD | FULL | 792291 | 85,424.59 | 43,635.14 | 31,025.15 | 85,590.41 | 623.14 |
| BTCUSD | DD50 | 682607 | 10,978.90 | 7,680.49 | 5,715.82 | 5,279.33 | 142.25 |
| BTCUSD | TRAIN | 500406 | 11,418.38 | 2,429.11 | 590.04 | 5,413.66 | 346.28 |
| USDJPY | FULL | 496711 | 11,285.81 | 5,913.13 | 3,315.32 | 13,308.19 | nan |
| USDJPY | DD50 | 578508 | 2,701.38 | 1,175.56 | 966.18 | 1,407.98 | nan |
| USDJPY | TRAIN | 514964 | 266.40 | 177.21 | 113.05 | 253.13 | nan |

ModelBTC menggunakanleverage10 yang belum dibuktikan untuk akun/histori broker. LEVERAGE2 adalah sensitivitas terpisah. USDJPY menggunakanleverage200model. Biaya1,5x/2x mengalikan komisi,slippage,financing; spreadasumsi tetap. Delay memakai next-observedM1 setidaknya1menit kemudian, bukan simulasi2detik. NO_ADDS merelokasi anggaranawal menjadi100% dan bukan ablationvolume-terkunci.

## Pembagian waktu untuk pemimpin yang dipilih

| symbol | criterion | id | TRAIN_2019_2022_equity | VALID_2023_2024_equity | TEST_2025_OCT2026_equity |
|---|---|---|---|---|---|
| BTCUSD | FULL | 792291 | 2,950.87 | 1,431.62 | 100.00 |
| BTCUSD | DD50 | 682607 | 1,428.90 | 595.83 | 100.00 |
| BTCUSD | TRAIN | 500406 | 8,936.84 | 427.18 | 100.00 |
| USDJPY | FULL | 496711 | 770.41 | 504.88 | 268.54 |
| USDJPY | DD50 | 578508 | 1,214.71 | 133.22 | 148.06 |
| USDJPY | TRAIN | 514964 | 2,165.74 | 19.85 | 85.10 |

Setiap segmen dimulai dari100 untuk mengisolasi kinerja segmen. Saldo periodepenuh tetap melalui compounding kontinu2019–Oktober tanpa setoran. Eksperimen terpisah pada kontrolMaret mengunci parameter sebelum April–Oktober; seluruh hasil lanjutannya tetap disertakan, termasuk kerugian.

## Data dan ketepatan waktu

BTCUSD menggunakan seluruhOHLCM1 resmiBitstamp, pasanganUSD, beserta rawresponseAPI dan checksum. Pada pembanding sampaiMaret, arsipCDD kehilangan85.414menit dan5.458candleOHLC berbeda dariAPIprimer, selisihmaksimum sekitarUSD1.908,89. Sourcefinal mengambil seluruh periode dariAPIprimer dengan aturan sama untuk semua timestamp, tidak memilih harga berdasarkan profit. Candlevolume0 yang dipublikasikan penyedia tetap dilabeli sebagai candleprovider; tidak ada tick atau harga interpolasi lokal. Ini harga tradeexchange, belum historicalbid/askCFD.

USDJPY berasal dari eksporHistData yang diaudit diActions39176779912, timezoneESTtetap+5jam keUTC. Semua timestamp,uniqueIDs,positiveOHLC,hash dan bulanperiode diverifikasi. Gapweekend/holiday/sparsequotes tetap dijabarkan padaauditsource; kalenderbroker dan seluruh gap tidak tersertifikasi. DatasetM1 bukan pengganti tickbid/ask.

SignalbarM5/M15/H1/H4/D1 sesuaiuniverse telahclosed sebelum entrynextbaropen. H4trend memakai candleclosed. Sessionwindows didefinisikan sebagai UTCtetap;WIB=UTC+7. Indikator coldstart pada2019, tidak mengklaim kesamaan denganprehistory/startupcBotnative. Tidak ada feedmacro atau syntheticmacropermissions pada strategi baru ini.

Prefixdifferential memodifikasi hanya hargamasa depan di memori dan menguji500parameter per universe: seluruh hasil akun sebelumcutoff tetap sama. Ada9fixtureeksekusi dan6aritmetika pada setiap engine. Ini cakupan regresi, bukan sertifikasi semua kemungkinanplatform.

## Asumsi model yang material

USDJPY: min/step1000USDbaseunits,max2.000.000; spread0,01JPY=1pip;slippage0,001JPY/sisi;komisiUSD0,00003/unit/sisi;financingdebit0,01%notional/hari prorata. PnLJPY dikonversi keUSD pada quoteexit.

BTC: min/step0,01BTC,max100BTC;spread5bp;slippage1bp/sisi;komisi5bp/sisi;financingdebit3bpnotional/hari prorata. Leverage10 adalah hipotesisriset, bukan bukti kontrakbroker. Fee,carry,weekendtrading,leveragehistoris,maxsize,rounding,depth danminimumstop broker belum diverifikasi.

Marginbudget10/25/50%equity,risk1–20%,integerstep dan compounding benar-benar diterapkan. SL/TP bersamaan menggunakanSTOP_FIRST; gapSL memakai openyanglebihburuk; stage ditambahkan pada openberikutnya setelah keputusancandleclosed. Break-even aktif mulai candleberikutnya. Expiry ditutup pada candletersediaberikutnya, bukan quotejamkosong. Tidak adaACK,partialfill,rejection/recovery native atau swapledgerbroker.

DD adalah statistikjalur/envelopeOHLC yang dipilihengine. Peak pada candleterkenastop dibatasi oleh aturanSTOP_FIRST; nilainya bukan batasatas matematis untuk setiap urutantick yang mungkin. Karena urutanintramenit danbid/askbroker tidak tersedia, DD<50%model tidak menjamin DDaktual<50%.

## Rekonsiliasi dan artefak

Setiap5shard berisi200.000IDinterleaved; gabungannya tepat1.000.000ID dantupleunik per universe, dengan engine daninputhash sama. Penilaian rawleader,DD50 dantrainleader direkonstruksi dariparameterCSV, dibandingkan dengan saldo semulamillion-rowfile, kemudian diuji biayadansegmen. Seluruhledger terpilih direkonsiliasi independen dari harga,volume,komisi,financing dan kas. Detailnilaierror ada diCASH_RECONCILIATION.json.

Selisihmikro pada beberapa eksporUSDJPY presisi12digit diperbaiki menjadi17digit. Regresinya membuktikan jalurfinansial,tradecount,stage dan hasilMaret tetap sama. Sourceasli dandiffexport dipertahankan. KesalahanunitDatetimePandas3 pada auditor/APIrequest awal juga diperbaiki secaraeksplisit ke nanosekon; runyanggagal/superseded tidak dipromosikan menjadi buktiprofit.

Paket perinstrumen memuat seluruhkonfigurasi,sourceexecuted,parameterpemimpin,ledger lengkap kandidat,laporanbulanan/tahunan,grafik danmanifestSHA256. Tick asli XAU/EUR,VPSarchive,cBotlive,bridge,envproduksi danstrategifrozen lama tidak diubah.

## Sumber dan reproduksi

- Bitstamp historicalOHLCAPI: https://www.bitstamp.net/api/
- HistData: https://www.histdata.com/f-a-q/
- Modelcommissionreference: https://www.fpmarkets.com/ctrader-fees-and-charges/
- Branch: research/btcusd-usdjpy-million-2019-2026.
- FullOctober universeexecution: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39213912052
- FullOctober independentaudit: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39214728591
- Positionuniverseexecution: https://github.com/rizanrizan93/Forex-scanner/actions/runs/39216109535
- KontrolMaret/extension: Actions39213178402 dan39213656204; rawdata/sourcebuild39211599931 dan39212036090.

**Kesimpulan: target dilaporkan sesuai angkaactualmodel di atas. Pencarianhistoris tidak membuktikan keuntungan masa depan atau profitbroker. Jika target belum ditemukan, tidak ada konfigurasiUSD100.000 yang diklaim berhasil.**
