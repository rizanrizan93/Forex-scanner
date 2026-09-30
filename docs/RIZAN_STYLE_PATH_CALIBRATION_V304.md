# RIZAN STYLE PATH CALIBRATION — V304

## Tujuan

V304 mengukur seberapa dekat **RIZAN STYLE PATH ENGINE V303** dengan forecast publik yang sudah tersedia sebelum outcome terjadi.

Kalibrasi ini tidak menambah execution authority dan tidak menjadi vote tambahan di V296. Tujuannya adalah membedakan tiga hal:

1. **geometric imitation** — apakah RIZAN menemukan decision zone, KEY, dan destination yang sama;
2. **branch classification** — apakah setelah decision zone harga benar-benar memilih rejection atau acceptance;
3. **prospective outcome** — apakah jalur yang dipetakan mencapai destination sesudah reference tersedia, tanpa lookahead.

## Reference corpus

File:

`calibration/xau_v304_afiq_public_reference_corpus.json`

Reference awal berasal dari capture forecast publik yang diberikan user pada 30 Sep 2026. Angka zona ditranskripsi dari gambar tersebut.

Untuk menjaga causal evaluation:

- `available_from` adalah waktu capture tersebut tersedia untuk proyek;
- `source_published_at` dibiarkan null karena timestamp publikasi asli belum diverifikasi;
- bar sebelum `available_from` selalu dikeluarkan dari outcome evaluation;
- horizon reference dibatasi.

Public channel/source identity dapat diverifikasi terpisah, tetapi numeric geometry untuk sample awal bersumber dari capture yang diberikan user.

## Metrik alignment

### Decision-zone overlap

Overlap dibagi lebar zona yang lebih sempit. Nilai 1 berarti zona RIZAN sepenuhnya overlap dengan reference zone.

### KEY error

V304 membandingkan:

- RIZAN rejection/reclaim key;
- RIZAN break/acceptance key;

terhadap reference KEY band.

Error = 0 jika key RIZAN berada di dalam reference band.

### Branch direction match

Membandingkan direction dari:

- rejection branch;
- acceptance branch.

### Destination alignment

- rejection route dibandingkan dengan destination pertama reference;
- acceptance next destination dibandingkan dengan destination pertama reference.

### Reference alignment score

Skor 0–100 adalah skor kesamaan geometri terhadap satu reference forecast.

**Ini bukan win rate, bukan probability, bukan confidence trading, dan bukan profit factor.**

## Prospective outcome

Outcome evaluator memakai M15 bars setelah `available_from` dan mencatat:

- decision-zone arrival;
- first-touch timestamp;
- rejection path confirmed;
- acceptance break;
- acceptance destination confirmed;
- reversal extreme;
- reversal-price error terhadap KEY band;
- terminal rejection path completion;
- terminal acceptance path completion.

State utama:

- `WAIT_DECISION_ZONE_ARRIVAL`
- `DECISION_PENDING`
- `REJECTION_PATH_CONFIRMED`
- `ACCEPTANCE_BREAK_WAIT_DESTINATION`
- `ACCEPTANCE_PATH_CONFIRMED`

## Runtime integration

V182:

1. membangun supply/demand map;
2. menyelesaikan M5 path projection;
3. membangun V303 style path;
4. menjalankan V304 alignment + prospective outcome.

Payload:

- `rizan_style_path_engine_v303`
- `rizan_style_path_calibration_v304`

V296 menyalin V304 ke decision snapshot dan mengeksposnya sebagai:

`NON_VOTING_PUBLIC_REFERENCE_CALIBRATION`

Tidak ada double-counting terhadap V182/V303.

## Batasan sample awal

Sample pertama hanya satu forecast reference dan timestamp publikasi asli belum diverifikasi. Karena itu:

- belum boleh menyimpulkan akurasi Afiq;
- belum boleh menyimpulkan RIZAN lebih baik/lebih buruk;
- belum boleh memakai alignment score sebagai win rate;
- belum boleh mempromosikan V304 ke execution influence.

Tahap berikutnya adalah memperbesar corpus dengan forecast yang timestamp-nya dapat diverifikasi sebelum outcome dan melakukan walk-forward/reference-by-reference evaluation.
