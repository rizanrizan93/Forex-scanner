# V315 — Precision TP Ladder

## Tujuan

V313 menunjukkan bahwa H1 reusable/retested zone yang memperoleh V189 M5
reclaim + MSS + displacement mempunyai conditional reaction quality yang kuat.
V314 kemudian menunjukkan bahwa single terminal TP 1.00 ATR menghasilkan
expectancy positif, tetapi TP rate dan precision target masih terlalu rendah.

V315 menguji apakah masalah utama memang exit geometry:

`H1 + M5 confirmation -> refined pocket fill -> TP1 dekat -> BE -> runner`

V315 **tidak mengubah entry detector**. Entry dan stop dibekukan dari geometry
yang dipilih development V314:

- entry: `POCKET_PROXIMAL_LIMIT`
- stop: `POCKET_DISTAL + 0.10 H1 ATR`
- limit fill window: 120 menit
- terminal runner harus tetap >=1.50R

## TP ladder grid

TP1:

- 0.25 ATR
- 0.35 ATR
- 0.50 ATR

Partial fraction:

- 25%
- 50%
- 75%

Runner:

- 0.75 ATR
- 1.00 ATR

Sesudah TP1, sisa posisi diproteksi di break-even. Untuk menghindari lookahead
intrabar, BE baru aktif pada M5 berikutnya; tidak boleh retroaktif pada candle
yang pertama kali menyentuh TP1.

## Conservative replay

- spread proxy $0.37;
- slippage proxy $0.002;
- commission proxy $0.002 round-trip;
- STOP_FIRST untuk ambiguity;
- tidak ada target credit pada fill candle;
- worse stop opening gap;
- max hold 480 menit.

## Precision objective

Metric utama bukan hanya runner TP:

- TP1 hit rate;
- TP1 Wilson lower 95%;
- TP1 hit dengan MAE <= $5;
- runner TP after TP1;
- break-even after TP1;
- profit factor;
- average net R;
- median MAE;
- fill rate.

V315 juga mengukur jarak TP1 ke H1 zone berlawanan yang masih active secara
causal pada saat TP1 diketahui. Ini hanya context untuk objective:

`TP pertama dekat dengan next reversal area`

dan **bukan** authority untuk membuka trade berikutnya.

## Development / holdout

Confirmed V313 `ALL_H1_MICRO_REQUIRED` opportunities dibagi seperti V314:

- development 60%;
- purge 24 jam;
- holdout 40%.

Semua ladder combinations hanya dipilih di development.

Development eligibility:

- >=30 fills;
- TP1 hit >=60%;
- PF >=1.10;
- average net R >=0.

Ranking:

1. TP1 + MAE <=$5 precision;
2. TP1 hit rate;
3. average net R;
4. PF.

Holdout tidak memilih parameter.

## Holdout gate

Gate dibekukan sebelum hasil:

- >=30 fills;
- fill rate >=25%;
- TP1 hit >=65%;
- TP1 Wilson lower 95% >=55%;
- TP1 + MAE <=$5 >=55%;
- PF >=1.30;
- average net R >=0.15.

Pass hanya mengizinkan forward DEMO **shadow/prospective** validation. Tidak
memberi execution authority.

## Supabase egress

Berbeda dari beberapa research runtime lama, full V315 grid dan row evidence
hanya disimpan sebagai GitHub Actions artifact. Supabase heartbeat hanya menerima
summary compact agar research tidak ikut memperbesar dashboard/runtime egress.

## Batasan

- sample recent-era yang sama dengan V313/V314;
- V314 holdout sebelumnya sudah diamati, sehingga V315 adalah stage-3
  reanalysis, bukan external OOS;
- historical cost memakai fixed proxy, bukan tick spread;
- M5 OHLC tidak membuktikan urutan intrabar;
- opposite H1 proximity hanya diagnostic context;
- no execution or promotion authority.
