# 1.0.1 — 15 November 2026 WIB

Rilis 1.0.0 lolos kompilasi SDK, tetapi pemeriksaan lanjutan dengan cTrader Console 5.10.1.0 melaporkan jenis `Indicator`. Pemeriksaan kompilasi sebelumnya belum menangkap masalah paket tersebut.

Rilis 1.0.1 mengekspor satu kelas publik `cAlgo.Robots.RizanBootstrap125V1` yang langsung mewarisi `cAlgo.API.Robot`, menjadikan tipe implementasi engine internal, dan mengekspor `.algo` biner tanpa source tertanam. Source lengkap tetap tersedia dalam ZIP. Native cTrader Console kini melaporkan `Type=cBot`; kontrol cBot minimal juga melaporkan `cBot`.

Isi fungsi host dan rumus engine dibandingkan dengan rilis awal: perubahan pada fungsi host hanya identitas versi log; file engine hanya berubah pada akses tipe, bukan isi fungsi. Kontrak profil, label order dan namespace checkpoint tetap kompatibel. Tidak ada perubahan aturan seed, handoff125, sizing, SL/TP, basket atau Guard47.

86 assertion C# dan 9 test bridge lulus. File `.algo` yang disertakan persis file yang dibaca pada uji native, diverifikasi dengan SHA256. Bukti native ini adalah pembacaan metadata, bukan uji order nyata. Replay tick broker penuh mempunyai status terpisah.

Gunakan file terbaru satu instance; file 1.0.0 perlu diganti. Bridge server tidak memerlukan penggantian karena kontrak state/protokol tetap sama.
