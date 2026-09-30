# V313 — H1 Reusable Primary Reversal + M5 Reconfirmation

## Tujuan

V312 menunjukkan bahwa blind reuse menaikkan coverage tetapi menurunkan kualitas.
Sinyal terbaik ada pada H1, terutama ketika reaction sebelumnya HOLD dan parent
zone masih structural. V313 menguji apakah fresh M5 microstructure dapat menjadi
filter yang mengembalikan kualitas tanpa kembali ke fresh-only.

Target struktural:

`first reaction -> H1 reusable candidate -> M5 reclaim + MSS + displacement -> post-confirm reaction`

## Candidate universe

V313 hanya menilai kandidat yang:

- H1;
- sudah pernah disentuh secara causal;
- lifecycle V312 menyatakan fresh micro refresh diperlukan;
- berada dalam V312/V309-compatible forward-reachable handoff universe <= $5.

Tiga policy dibekukan sebelum hasil dilihat:

1. `ALL_H1_MICRO_REQUIRED`
2. `PRIOR_HOLD_H1_MICRO_REQUIRED`
3. `STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED`

Policy ke-3 adalah primary confirmatory policy karena V312 menunjukkan cohort
H1 structural + prior HOLD paling menarik.

## Historical M5 confirmation

V313 memakai engine V189 yang sama:

- source touch / sweep;
- proximal reclaim;
- local executable M5 MSS;
- displacement confirmation;
- refined origin pocket.

Candidate dipilih **sebelum** M5 confirmation.

Aturan waktu yang dibekukan:

- candidate harus disentuh M5 dalam 240 menit;
- reclaim + MSS + displacement harus selesai maksimal 90 menit sejak first M5 touch;
- confirmation baru causal pada close displacement M5, yaitu `displacement_at + 5m`.

## Post-confirm outcome

Ini belum broker trade replay.

Sesudah confirmation, V313 memakai confirmation-time market price sebagai anchor
dan mengukur selama 240 menit:

- HOLD: favorable excursion >=0.50 ATR;
- BREAK: M5 close melewati H1 distal;
- STALL: tidak HOLD dan tidak BREAK.

Jika HOLD dan BREAK ambigu pada bar yang sama, distal close BREAK menang.

Baseline juga dihitung dari first M5 touch agar kita dapat mengukur apakah
menunggu V189 confirmation benar-benar meningkatkan conditional reaction quality.

## Recent-era cTrader overlap

Full V312 memakai 100K M15 dari 2022–2026. cTrader M5 100K hanya mencakup
periode lebih pendek. Karena itu V313 sengaja menjadi recent-era overlap study:

- M15 target 50K bars untuk zone/lifecycle context;
- M5 target 100K bars untuk micro confirmation;
- hanya reaction timestamps yang berada di dalam M5 coverage yang dievaluasi.

Ini lebih relevan untuk era terbaru, tetapi **bukan** full-history M5 validation.

## Chronological validation

Candidate series dibagi:

- development 60%;
- purge 24 jam;
- holdout 40%.

Primary gate hanya memakai holdout policy
`STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED`.

Gate dibekukan sebelum hasil:

- >=30 confirmed holdout candidates;
- M5 confirmation rate >=10%;
- post-confirm HOLD rate >=60%;
- Wilson lower 95% >=50%;
- uplift >=7.5 percentage points vs first-touch baseline;
- median touch -> confirmation <=60 menit.

Pass hanya mengizinkan tahap **exact-entry / SL / TP replay**. Tidak memberi
execution authority.

## Execution

- policy effect: RESEARCH_ONLY
- execution influence: false
- execution authority: false
- promotion authority: false

V229/V280/admission/protection, V309 Primary Reversal, dan DEMO execution tidak
diubah oleh V313.
