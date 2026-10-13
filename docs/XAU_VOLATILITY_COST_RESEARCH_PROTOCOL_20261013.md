# Protokol filter volatilitas/biaya XAU — sebelum outcome 2026

Contract RIZAN_XAU_VOLATILITY_COST_REVERSAL_NET_V1, scanner-only.
Hipotesis tambahan: sinyal reversal harus memiliki ATR14 M5 yang sudah diketahui pada close trigger, memadai dibanding spread cautious0,50 XAUUSD. Minimum rasio ATR5/spread [0;0,5;1;1,5;2], artinya ATR5 minimum [0;0,25;0,50;0,75;1,00] XAUUSD. Nol adalah baseline tanpa filter. Tidak memakai volatilitas sesudah entry, hari profit, maupun hasil trade untuk memilih observasi.

Varian memakai structural M5 source/stop/target dan seluruh syarat seleksi protokol sebelumnya: channel24/32/48/64, sweep24confirmed, halfwidth tetap0,5H1ATR; stop max(0,5XAUUSD, ATR5×[1;1,65;2,15;2,65;3,25], jarak cautiousfill ke seed/trigger extreme); TP[1,5;2;3;4;6,6]nominalR dan>=25%ADR20. Dimensi filtervol5 menggantikan halfwidth5, sehingga tepat10.000.000tuple yang saling berkorelasi.

Training2016–2021 n>=180,netR>0,PF>=1,15,>=5tahunpositif dengan>=15trade/tahun,censor<=2%.
Validation2022–2025 n>=60,PF>=1,20,stressR>0,meanLCB>0,>=3tahunpositif,censor<=2%.
Jan–Sep2026 hanya outcome kandidat yang parameter-nya sudah terkunci: n>=30,meanNetR>0,PF>=1,20,stressmean>0,lower95%monthlyblockbootstrap meanR>0,censor<=2%.
Tahun2026 sudah ada dicache; bukan first-download-after-lock. Tahun2016–2025 sudah pernah dilihat dalam studi lain, sehingga confidence sejarah deskriptif dan walkforward tetap eksploratif.

Tidak menurunkan ambang profit untuk membuat hasil lolos. Biaya spread/slip/commissionproxy, firsteligible UTCday/perarah, next-M1-open, stop-first/gaps, timeout20:55UTC/deadlineopen, nonovernight dancensored-dayclaim sama protokol struktural. BUY/SELL bukan portfolio gabungan. Equity/lot/layering/cBot tidak dimodelkan. Tidak menjamin reversal setiap hari; tidak menyebut zona top/bottom absolut harian.

Rincian metode pada docs/XAU_STRUCTURAL_M5_RESEARCH_PROTOCOL_20261013.md. Ini pengujian tambahan sesudah seleksi historis keluarga struktural kosong; outcome kandidat2026 keluarga-keluarga sebelumnya juga kosong.

