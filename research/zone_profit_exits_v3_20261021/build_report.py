from pathlib import Path
import json
import pandas as pd
from profit_engine import ROOT

def table(df,columns):
    out=['| '+' | '.join(columns)+' |','| '+' | '.join(['---']*len(columns))+' |']
    for _,r in df.iterrows():
        out.append('| '+' | '.join('—' if pd.isna(r[c]) else f'{r[c]:.4f}' if isinstance(r[c],float) else str(r[c]) for c in columns)+' |')
    return '\n'.join(out)

def main():
    cfg=json.loads((ROOT/'LOCKED_PROTOCOL_V3.json').read_text());sel=json.loads((ROOT/'LOCKED_TRAIN_SELECTION.json').read_text())
    audit=json.loads((ROOT/'RESULT_AUDIT.json').read_text());quality=json.loads((ROOT/'NEW_DATA_QUALITY.json').read_text())
    manifest=json.loads((ROOT/'NEW_INPUT_MANIFEST.json').read_text());s=pd.read_csv(ROOT/'COMPARISON.csv')
    rank=pd.read_csv(ROOT/'TRAIN_SELECTION_RANKING.csv');paired=pd.read_csv(ROOT/'MATCHED_ENTRY_EXIT_ABLATION.csv')
    fresh=s[s.split.eq('new_validation') & s.scope.eq('one_position')]
    base=fresh[fresh.policy.eq('BASE_1R_60') & fresh.cost_multiple.eq(1)].iloc[0]
    chosen=fresh[fresh.policy.eq(sel['policy'])]
    normal=fresh[fresh.cost_multiple.eq(1)];wins=normal[normal.policy.ne('BASE_1R_60')].sort_values('sum_net_R',ascending=False)
    best=wins.iloc[0]
    verdict='Belum ditemukan exit challenger dengan peningkatan profit yang dapat dinyatakan tervalidasi.'
    actual=pd.read_csv(ROOT/'ONE_POSITION_LEDGER.csv')
    actual=actual[actual.split.eq('new_validation') & actual.policy.eq(sel['policy'])]
    gross=float(actual.gross_R.sum());cost=float(actual.cost_R.sum())
    reasons=actual.groupby('reason').agg(n=('event_id','size'),gross_R=('gross_R','sum'),net_R=('net_R_1x','sum')).reset_index()
    selection=json.loads((ROOT/'PREVALIDATION_GIT_LOCK.json').read_text())
    text=f'''# RIZAN — Profit Exit Challenger V3

21 Oktober2026 · `RZ-PROFIT-EXIT-V3-20261021` · **RESEARCH ONLY**

**{verdict}** Eksperimen ini menguji cara exit dengan entry dan risiko awal tetap. Semua hasil berikut benar-benar dihitung dari quote/tape yang dibaca. Tidak ada perubahan cBot beku, bridge, trading live atau merge ke main.

## Keputusan sebelum hasil tanggal baru

Delapan exit dikunci dalam `LOCKED_PROTOCOL_V3.json`, SHA256 `{sel['protocol_sha256']}`. Entry tetap **zona H1 + absorption awal V2**: detektor zona, first-touch, sweep, threshold volume15s, arrival timestamp dan stop awal tidak dituning. Risk awal dan leverage tidak dinaikkan untuk membuat profit lebih tinggi. H4 dicatat sebagai konteks, bukan filter tambahan. Tidak ada layering atau compounding akun di model ini.

Pemilihan hanya memakai **1Feb dan1Mar2024**. **1Apr dan1Mei** sudah pernah dilihat dan dilabeli `seen_diagnostic`, tidak dipakai sebagai bukti out-of-sample baru. Sebelum outcome baru direplay, pilihan `{sel['policy']}` sudah disimpan pada commit [{selection['commit']}](https://github.com/rizanrizan93/Forex-scanner/commit/{selection['commit']}). Hash file pilihan diperiksa tidak berubah setelah validasi. Lulus screen train bukan kualifikasi live.

Kriteria pemilihan: minimal5 transaksi satu-posisi pada train, mean netR>0 danPF>1 pada biaya1× dan1,5×; urutkan profit per peluang yang sama pada1,5×, lalu drawdown kumulatifR lebih kecil. Jika tidak ada yang lolos, hanya boleh mencatat kandidat diagnostik gagal. Pada sampel train kecil ini, pilihan aktual adalah `{sel['policy']}`, screen train `{sel['training_screen_pass']}`.

## Data baru yang diperoleh dan digunakan

- Venue: **Bybit linear BTCUSDT perpetual**, bukan BTCUSD CFD, XAUUSD atau EURUSD broker.
- Empat tanggal baru: **1Jul,1Agu,1Okt,1Nov2024 UTC**, ditetapkan sebelum download/outcome; semuanya hari kerja. Ini **empat hari**, bukan periode Juli–November penuh.
- Setiap tanggal memakai3 hari pemanasan L2 sebelumnya: total16 arsip L2 baru, **{sum(x['messages'] for x in quality['books']):,} pesan**.
- Tape baru: **{sum(x['trade_rows_unique'] for x in quality['trades']):,} transaksi unik**, dengan sisi aggressor dan arrival timestamp. Total ukuran20 input baru: **{sum(x['bytes'] for x in manifest):,} byte**. Duplikat, lag dan coverage perhari ada di `NEW_DATA_QUALITY.json`.
- Semua ZIP dibaca penuh untuk CRC, tape gzip dibaca penuh; SHA256 dan URL asli ada di `NEW_INPUT_MANIFEST.json`. Quote invalid: **{sum(x['invalid_seconds'] for x in quality['books'])} detik** di16 hari L2; tidak diimputasi. Snapshot/delta diproses sebelum sampling1detik.
- Transaksi baru tersedia setelah arrival. Untuk arsip L2 tanpa arrival, tetap memakai asumsi publikasi+1detik V2, bukan latency broker terukur.

Sumber: [Tardis Bybit](https://docs.tardis.dev/historical-data-details/bybit) dan arsip L2 Bybit di manifest. Hari pertama bulan tersedia sebagai sampel publik; pemilihan hari merupakan convenience sample, bukan sampel acak. Tidak ada akun Bookmap resmi, data CME berlisensi atau pembayaran yang diaktifkan. Hasil tidak berlaku otomatis pada XAU/EUR.

## Exit yang diuji

| ID | Exit | Batas waktu |
| --- | --- | --- |
| BASE_1R_60 | TP1R, stop awal tetap |60menit |
| TP15_60 | TP1,5R, stop awal tetap |60menit |
| TP2_120 | TP2R, stop awal tetap |120menit |
| STRUCT_CAP2_120 | Target=min(2R,batas H1 lawan yang sudah diketahui); fallback2R jika tidak tersedia/di belakang entry |120menit |
| PARTIAL_1R_2R_120 | Tutup50% saat1R, sisa ke2R/stop/waktu |120menit |
| BE_AFTER1R_TP2_120 | Setelah1R, stop pindah ke harga entry, efektif quote berikutnya |120menit |
| TRAIL075_AFTER1R_TP2_120 | Setelah1R, stop mengikuti peak yang sudah teramati dikurangi0,75R, efektif quote berikutnya |120menit |
| TIME_PROTECT_TP2_120 | Pada menit30, tutup jika MFE<0,5R; selain itu lanjut2R/stop |120menit |

BE harga entry tetap membayar biaya sehingga bisa rugi net. Partial exit tidak mendapat entry gratis: entry fee dikenakan sekali pada volume awal, exit fee dan financing dibebankan proporsional volume/durasi. Trailing tidak boleh memakai peak masa depan atau mengangkat stop secara retroaktif pada quote yang sama. Target struktural tidak dipindah setelah melihat masa depan.

Entry memakai ask untukBUY danbid untukSELL; exit memakai sisi executable sebaliknya pada sampel quote. Spread sudah terkandung dalam harga tersebut. Fee5,5bp/sisi, slippage debit1bp/sisi, financing debit3bp notional/hari. Biaya1,5× dan2× mengalikan fee/slippage/financing, **tidak mengalikan spread**. Ini asumsi debit biaya, bukan tarif FP tersertifikasi, funding settlement aktual, limit queue atau market-impact stress. Tidak ada perubahan fill karena biaya alternatif.

## Audit kontrol dan cohort

Paket V2 asli dipulihkan dari ZIP SHA256 `43ce4bf3874045adb4f0d78be45d669346db50c0ee80766346432e808fc4b1ae`;86 anggota ber-manifest diperiksa. `V2_REPRODUCTION_AUDIT.json` menunjukkan entry/exit, grossR, costR dan netR lama direproduksi tanpa selisih pada sinyal yang cocok. Source V2 dan strategi beku tidak diubah.

Untuk perbandingan utama semua exit, setiap entry harus mempunyai120menit quote lengkap tanpa gap. Ini filter **ketersediaan data offline**, bukan syarat entry live yang dapat mengetahui koneksi masa depan. Semua signal/exclusion tetap tersimpan di ledger; tidak memilih cohort berdasarkan untung/rugi. Batas ini menghindari pembanding60/120menit memakai peluang yang berbeda di ujung arsip. Model V2 langsung menyensor saat horizon melewati ujung dataset, bahkan jika terminal mungkin terjadi lebih awal; kontrol direproduksi apa adanya dan primary common cohort menghindari boundary tersebut.

Event study pada entry sama dan satu-posisi per exit dilaporkan terpisah. Durasi exit berbeda bisa membuat transaksi berikutnya terlewat; karena itu profit kumulatif dan profit per peluang juga disajikan, bukan hanya win rate transaksi yang tersisa. Skenario exit berbeda tidak boleh dijumlahkan sebagai satu portfolio.

## Ranking train yang dipakai sebelum validasi

''' + table(rank,['policy','training_screen_pass','n','train_mean_R_1x','train_mean_R_15x','rank_profit_per_opportunity_15x'])+f'''

## Hasil tanggal baru — satu posisi per exit, biaya normal

''' + table(normal,['policy','n','wins','win_pct','sum_net_R','mean_net_R','PF_R','max_cumulative_R_DD'])+f'''

Baseline pada data baru: **{int(base.n)} transaksi, win{base.win_pct:.2f}%, total{base.sum_net_R:+.4f}R, mean{base.mean_net_R:+.4f}R**. Baris seluruh alternatif tetap ditampilkan. Alternatif dengan total normal tertinggi pada data baru adalah `{best.policy}` dengan{best.sum_net_R:+.4f}R; ini **observasi post-hoc**, tidak menggantikan kandidat yang sudah dikunci atau menjadi bukti validasi kandidat tersebut.

## Apa yang menjelaskan kerugian sampel baru

Seluruh delapan exit masih mencatat total negatif pada empat tanggal baru. Kandidat yang dikunci sebelum replay juga gagal pada sampel baru. Time-protect hanya memperbaiki total normal sekitar 0,0212R terhadap baseline; perubahan sekecil ini pada 11 transaksi tidak cukup untuk menyatakan peningkatan profit konsisten.

Baseline sudah menghasilkan **{gross:+.4f}R sebelum debit komisi/slippage/financing**, lalu debit tersebut menambah **{cost:.4f}R** sehingga net menjadi **{base.sum_net_R:+.4f}R**. Spread aktual sampel bid/ask sudah termasuk gross. Jadi kerugian tidak bisa dijelaskan hanya oleh biaya. Rata-rata debit tambahan adalah **{cost/len(actual):.4f}R per transaksi**; ini berarti biaya cukup besar relatif terhadap jarak stop awal.

''' + table(reasons,['reason','n','gross_R','net_R'])+f'''

Kelompok timeout mempunyai gross positif tetapi net negatif setelah biaya. Stop yang gagal mengimbangi target juga memberi kontribusi rugi. Ini diagnosis pada sampel, bukan bukti penyebab universal atau alasan untuk menyaring transaksi rugi setelah melihat hasil. Entry H1 + absorption awal belum menunjukkan keunggulan yang bertahan pada empat hari baru. Menaikkan TP atau leverage tidak memperbaiki bukti tersebut.

## Stress untuk kandidat terpilih

''' + table(chosen,['policy','cost_multiple','n','win_pct','sum_net_R','mean_net_R','PF_R'])+'''

Tabel biaya semua alternatif ada di `COMPARISON.csv`. Bila biaya membuat meanR negatif atau sampel tidak memadai, kandidat tidak boleh dipromosikan hanya karena hasil normal/angka win rate tampak baik.

## Efek exit pada entry yang identik

''' + table(paired[paired.split.eq('new_validation') & paired.cost_multiple.eq(1)],['policy','matched_events','base_same_entries_mean_R','challenger_mean_R','mean_exit_delta_R','sum_exit_delta_R'])+f'''

Ini mengisolasi perubahan exit pada peluang yang sama. Sementara tabel satu-posisi di atas juga mencakup efek transaksi terlewat karena hold lebih lama. Risiko awal setiap posisi tetap; angka R tidak sama dengan persen return akun.

## Rekonsiliasi dan batas kesimpulan

- Skenario lengkap: **{audit['complete_exit_model_rows']}**; status seluruh baris ada di audit, termasuk censor/gap.
- Pemeriksaan fraction partial menjumlah1, cash gross/net dan fee perleg lulus. Residual cash absolut maksimum **{audit['max_cash_identity_residual_usd_per_initial_btc']:.12g} USD perBTC awal**. Entry setelah keputusan dan zona tersedia sebelum touch diperiksa.
- Flag `structural_target_used` menunjukkan batas lawan tersedia; jumlah yang betul-betul menurunkan cap2R dilaporkan terpisah dalam `structural_binding_events`. Banyak fallback berarti bukan seluruh observasi menguji target struktural murni.
-15 tes V3 lulus dan12 tes baselineV2 lulus secara terpisah. Tidak ada klaim CI native/full parity atau rekaman semua paket tanpa kehilangan.
- Pemilihan sudah dikunci sebelum empat tanggal baru, tetapi train hanya dua tanggal dan kandidat entry berasal dari riset historis sebelumnya. Sampel baru ini belum cukup untuk menyatakan edge stabil di seluruh regime atau signifikan setelah banyak percobaan.
- Drawdown adalah penurunan kumulatifR, **bukan floating equity DD persen akun**. Tidak ada saldo akhir, leverage, margin bersama, layering atau compounding yang disimulasikan; tidak boleh memindahkan hasil ke statistik cBot portfolio.
- Tidak ada jaminan hasil masa depan. XAU/EUR membutuhkan L2/trades sesuai dan basis/roll yang diaudit jika memakaiGC/6E. Eksperimen ini hanya BTCUSDT Bybit.

## Berkas dan reproduksi

`EXIT_LEDGER.csv`, `FILL_LEDGER.csv`, `ONE_POSITION_LEDGER.csv`, `MATCHED_ENTRY_EXIT_ABLATION.csv`, `DAILY.csv`, `DIRECTION_CONTRIBUTIONS.csv`, protokol, pilihan train, audit, source dan grafik disertakan. Paket menyertakan input turunan quote/tape yang digunakan, sehingga replay bisa diulang tanpa download mentah lagi. Raw baru tetap terpisah; URL/hash tersimpan untuk merekonstruksi setiap delta.

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest test_profit_engine -v
python3 profit_engine.py old
# Pilihan dibuat oleh stage old; jangan ubah setelah membaca stage new.
python3 profit_engine.py new
python3 audit_profit.py
MPLBACKEND=Agg python3 plot_results.py
python3 build_report.py
# Jika ingin rekonstruksi data baru dari raw:
python3 new_inputs.py
```

Source dan hasil ada di branch riset tersendiri. cBot beku, bridge, `.env` produksi, risk live dan state eksekusi tidak disentuh; tidak merge ke main.
'''
    (ROOT/'LAPORAN_PROFIT_EXIT_V3_20261021.md').write_text(text)
    status={'experiment':cfg['experiment'],'selected_before_new_outcomes':sel['policy'],'prevalidation_commit':selection['commit'],
            'new_date_replay_complete':True,'consistent_profit_improvement_qualified':False,'live_qualified':False,
            'baseline_v2_reproduced':True,'tests_v3':15,'tests_baseline_v2':12,'xau_eur_validated':False,
            'orders_sent':False,'bridge_modified':False,'frozen_strategy_modified':False,'risk_or_leverage_increased':False}
    (ROOT/'STATUS.json').write_text(json.dumps(status,indent=2)+'\n')
    print('report generated',flush=True)

if __name__=='__main__':main()
