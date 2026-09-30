# RIZAN STYLE PATH ENGINE — V303

## Tujuan

RIZAN STYLE PATH ENGINE mengubah peta supply/demand V182 menjadi forecast struktural bercabang yang mudah dibaca:

1. current source;
2. next decision zone;
3. KEY rejection/reclaim;
4. KEY break/acceptance;
5. primary path;
6. rejection branch;
7. acceptance/continuation branch;
8. next structural destination.

Engine ini dibuat untuk menjelaskan **alur harga**, bukan sekadar menampilkan supply, demand, entry, dan target sebagai angka yang terpisah.

## Kontrak

- Contract: `RIZAN_STYLE_PATH_ENGINE_V303`
- Policy: `STRUCTURAL_FORECAST_ONLY`
- Execution authority: **false**
- Execution influence: **false**
- Input utama: V182 supply/demand atlas + current dashboard price.
- DEMO execution tetap melalui V229/V280/admission/protection.

Engine tidak menjadi vote baru di V296 karena ia merupakan transformasi struktural dari V182. Ini mencegah double-counting evidence.

## State machine

### APPROACH_DECISION_ZONE
Harga berada pada reaction side dan masih menuju decision zone.

### DECISION_ZONE_ACTIVE
Harga berada di dalam decision zone. Engine menunggu salah satu cabang valid.

### DECISION_ZONE_REJECTION_CONFIRMED
M5 leg yang source-nya sama dengan decision zone mencapai `M5_REFINEMENT_CONFIRMED_SHADOW`. Rejection branch menjadi armed.

### DECISION_ZONE_ACCEPTED_BREAK
Harga berada di break side dari distal decision zone. Engine menganggap zona lama tidak boleh di-fade dan continuation branch menjadi armed.

### NO_STRUCTURAL_PATH / NO_DECISION_ZONE
Fail-closed. Engine tidak mengarang path.

## KEY levels

Untuk **supply / SHORT zone**:

- rejection/reclaim key = batas bawah zona;
- break/acceptance key = batas atas zona.

Untuk **demand / LONG zone**:

- rejection/reclaim key = batas atas zona;
- break/acceptance key = batas bawah zona.

Ini membuat KEY bersifat deterministic dan machine-readable.

## Dashboard

Panel `RIZAN STYLE PATH ENGINE` ditempatkan sebelum V240 Canonical XAU Decision Map dan menampilkan:

- arah leg aktif;
- state;
- decision zone;
- KEY rejection/reclaim;
- KEY break/acceptance;
- primary route;
- rejection route;
- acceptance route;
- status cabang.

Panel memakai current V182 map dan freshest XAU price yang sudah digunakan dashboard, sehingga tidak menambah polling database baru.

## Decision Center

V296 menyimpan payload `rizan_style_path_engine` di dalam decision snapshot dan menambahnya ke support evidence sebagai:

`NON_VOTING_BRANCHING_STRUCTURAL_FORECAST`.

Dengan demikian path tersedia untuk audit/outcome research tanpa menduplikasi bobot V182.

## Tahap berikut

V303 adalah structural path layer. Tahap berikut yang layak diuji secara prospective:

- accuracy decision-zone arrival;
- rejection vs acceptance classification;
- latency sampai branch confirmation;
- branch-specific MFE/MAE;
- source-to-destination completion;
- kalibrasi per timeframe, depth, session, dan pressure state.

Tidak ada klaim win rate sampai sample forward yang cukup tersedia.
