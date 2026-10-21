# Rekonstruksi audit

Semua eksekusi di bawah hanya untuk folder riset. Tidak menjalankan cBot pada akun broker.

1. Checkout `research/october-entry-audit-20261021`. Source beku disimpan di `portfolio_7day_frozen`; hasil wrapper lengkap memakai commit `0612939a23b35e0275d1b7e50956e0f330abf3dc`.
2. Unduh artefak replay run `39536869038`, ID `12318001900`. Verifikasi ZIP SHA256 `5897e08bebe02306d75509ea15127379555c74e7c6e994f5747c48552b4b5b4e` sebelum ekstraksi ke root checkout riset. Artefak memuat `publish` (termasuk 3 CSV broker dan seed BTC), `activation` dan manifest input broker.
3. Untuk replay byte yang sama, gunakan seed `publish/BTC_H1.csv` dalam artefak, bukan menanyakan feed terkini lagi. Cocokkan dengan `BTC_FRESH_SEED_MANIFEST.json` dari artefak. Input broker replay adalah pengambilan awal yang berakhir 21 Oktober 02:49 UTC; hasil broker/margin yang lebih baru dalam laporan bukan input replay tersebut.
4. Salin tiga `publish/*_BROKER_M1.csv` ke `broker/publish/`, yang sudah memiliki manifest `BROKER_READ_ONLY_HISTORY.json` dari artefak. Jangan mengganti manifest dengan pembacaan broker yang lebih baru.
5. Dengan .NET SDK 8.0.426: jalankan `python3 october_order_readiness/build_activation_replay.py`, `dotnet build -c Release october_order_readiness/ActivationReplay.csproj`, lalu `python3 october_order_readiness/run_activation_replay.py`. Harus ada 12 case selesai, error nol, dan konservasi cash. `ACTIVATION_REPLAY_CONFIG.json` menjelaskan initial state, rentang waktu, spread dan macro controls.
6. Fixture order: `dotnet run -c Release --project october_order_readiness/OrderabilityTests.csproj`. Ini memakai API stub tanpa jaringan broker. Untuk suite lengkap, ikuti `.github/workflows/october-order-readiness.yml`; instal kebutuhan bridge sebelum membuat fixture feed.

Untuk merekonstruksi laporan dari arsip hasil saja, simpan tiga ZIP artefak sesuai nama dalam `ARTIFACT_PROVENANCE.json` ke `october_order_readiness/evidence/`. Jalankan `CONSOLIDATE_EVIDENCE.py` dan `WRITE_REPORT.py` dari root checkout. Snapshot native/current macro tambahan merupakan bukti terpisah run `39536538363`, sudah tersimpan dalam laporan.

Jangan menyamakan pengujian ini dengan FULL_PARITY tick broker, rekonstruksi snapshot macro historis, atau pembuktian order live diterima broker. Jangan mengganti source entry/SL/TP/risk untuk memaksa jumlah entry.
