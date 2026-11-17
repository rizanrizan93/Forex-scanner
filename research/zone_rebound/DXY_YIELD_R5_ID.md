# RIZAN — sumber macro riset zona R5: DXY + yield

Instruksi pengguna 18 November 2026: gunakan DXY dan yield karena itu sumber
macro yang akan dipakai. R5 tidak memakai EURUSD atau basket sintetis sebagai
pengganti DXY. Hasil proxy R4 tetap merupakan eksperimen terdahulu.

## Status

Input dan jalur entry replay telah diganti dan diverifikasi dengan tes.
**Belum ada hasil akurasi replay DXY + yield pada 2019–Maret 2026.**
Cache publik yang berhasil diambil berisi DXY 12–17 November 2026 dan
US10Y 11–17 November 2026. Input zona mempunyai 110.595 sentuhan,
2 Januari 2019–31 Maret 2026. Tidak ada tanggal bersama; replay diblokir.
US2Y intraday dari endpoint publik CNBC gagal HTTP 403 dan tidak diisi data
harian atau futures. Ini masalah cakupan sumber, bukan hasil strategi gagal.

Kode ini adalah riset offline terpisah; bukan perubahan scanner production.

## Komponen dan hipotesis awal

| Komponen | BUY XAU | SELL XAU | Peran |
|---|---|---|---|
| DXY 15 menit | Turun ≥0,01% | Naik ≥0,01% | Arah dolar dari seri indeks |
| US10Y 15 menit | Turun ≥0,5 bp | Naik ≥0,5 bp | Yield intraday utama |
| US2Y 15 menit | Turun ≥0,5 bp | Naik ≥0,5 bp | Konfirmasi tambahan jika tersedia |
| Real yield 10Y harian | Penurunan sebagai konteks | Kenaikan sebagai konteks | Bukan pengganti yield intraday |

Ini hipotesis yang harus diuji, bukan hukum arah emas atau ambang terkalibrasi.
Jika DXY dan yield bertentangan, gabungan tidak lolos. Data basi atau hilang
tidak diganti dengan EURUSD, yield futures, harga obligasi, atau yield harian.

Aturan pembentukan zona/rejection/reclaim/sweep/micro-shift R4 dipertahankan
dalam `r5_entry_core.py`. R5 menginjeksikan aturan DXY/yield langsung ke
pemilihan entry pertama yang eligible, maksimal 15 menit dari sentuhan.
Sampel kontrol juga dibatasi pada cakupan DXY dan US10Y yang sama.

## Sumber dan kualitas waktu

- DXY: Yahoo `DX-Y.NYB`, indeks yang melacak ICE U.S. Dollar Index; distribusi
  sekunder, bukan klaim feed ICE resmi. Direct DXY CFD broker dapat diterima
  hanya dengan label sumber dan tipe CFD yang eksplisit, bukan basket sintetis.
- US10Y: Yahoo `^TNX`, indeks yield dalam persen, bukan harga ZN futures.
- US2Y: cash yield bertimestamp, misalnya CNBC/Tradeweb ketika dapat diakses.
- Treasury/Fed daily: hanya konteks publikasi harian, bukan pergerakan per menit.

CSV perlu `observed_at`, `available_at`, `value`, `series`, `unit`,
`instrument_kind`, `source`, `frequency`, `time_basis`.
Observasi hanya boleh dipakai setelah `available_at`, dengan umur maksimal
10 menit dan selisih waktu DXY/US10Y maksimal 5 menit. Perubahan memakai
observasi yang telah tersedia pada masing-masing ujung jendela 15/60 menit.
Perubahan yield dihitung dalam basis poin: selisih nilai persen ×100.

Normalisasi cache Yahoo 5 menit memakai penutupan candle +60 detik sebagai
**asumsi** ketersediaan historis. Candle terakhir yang belum selesai menurut
waktu snapshot vendor dibuang. Asumsi ini bukan sertifikasi point-in-time,
latency nyata, atau feed real-time. Hasil yang kelak memakai cache ini harus
diberi label eksploratif; source yang mencatat ingest asli dapat memakai
`OBSERVED_INGEST`.

## Jalankan

```bash
PYTHONPATH=src:. python -m research.zone_rebound.dxy_yield_r5 \
  --dxy /path/dxy_points.csv --us10y /path/us10y_points.csv \
  --touches /path/zone_events_r3.csv.gz --out /path/r5_output

PYTHONPATH=src:. python -m research.zone_rebound.dxy_yield_r5 \
  --dxy /path/dxy_points.csv --us10y /path/us10y_points.csv \
  --us2y /path/us2y_points.csv --touches /path/zone_events_r3.csv.gz \
  --xau /path/XAUUSD_m1.csv --replay --out /path/r5_output

PYTHONPATH=src:. python -m unittest discover -s tests -p 'test_dxy_yield_r5*.py' -v
```

Preflight hanya mengukur cakupan data, bukan akurasi. Replay yang mempunyai
data bersama tetap harus memisahkan target $10, batas melawan $10, timeout,
ambigu satu candle, gap, arah endpoint 15 menit, serta MFE/MAE. Dataset kalender
tidak disamakan dengan input lama, dan persentase R4 tidak dilabel ulang sebagai R5.

## Referensi

- [ICE: DXY, data intraday dan historis](https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-currency-indices)
- [Treasury: sifat data yield curve harian](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)
