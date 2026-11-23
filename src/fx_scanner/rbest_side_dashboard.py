"""RIZAN eight winning side lanes: verified shadow signals vs archived evidence.

R25 BUY and R11 SELL are reconstructed only for H1/H4; other historical
leaderboard lanes remain explicit unavailable until independent live parity.
Never map percentages to live model score, trade authority or entry orders.
"""
from __future__ import annotations


def candidate_runtime_rows(best, lock, r281):
    """Pure, testable 8-slot comparison with independently observed statuses."""
    out=[]
    for record in lock["entries"]:
        tf=record["tf"];side=record["side"]
        lane=(best or {}).get(tf) or {}
        state=lane.get("state")
        if tf in ("H1","H4"):
            if state in ("RESEARCH_SHADOW","MODEL_ABSTAIN"):
                active=lane.get("buy_active") if side=="BUY" else lane.get("sell_active")
                code="AKTIF · SHADOW" if active is True else "TIDAK TERPICU"
            else:
                code="WAIT DATA" if state=="WAIT_DATA" else "MENUNGGU INFERENSI"
            decision=lane.get("direction","WAIT")
            exp=lane.get("target")
            reason=lane.get("reason","FEED_UNAVAILABLE")
        elif tf=="D1" and side=="BUY":
            # R28.1 D1 is multi-head; it is not an independent R25-style
            # side winner. Reuse ONLY the already validated D1 direction.
            old=(r281 or {}).get(tf) or {}
            state=old.get("state")
            decision=old.get("direction","WAIT")
            if state=="RECONSTRUCTED_SHADOW":
                code="R28.1 AKTIF" if decision=="BUY" else "R28.1: BUKAN BUY"
            else:
                code="R28.1: WAIT"
            exp=old.get("target")
            reason="R28.1 MULTIHEAD, BUKAN INFERENSI SISI INDEPENDEN"
        else:
            code="BELUM ADA MODEL INFERENSI"
            decision="WAIT"
            exp=None
            reason="ARTIFAK HISTORIS; INPUT/REFIT LIVE BELUM DIVERIFIKASI"
        out.append({
            "TF":tf,"Sisi":side,"Kandidat":record["version"],
            "Hasil kandidat":code,"Prediksi gabungan":decision,
            "Horizon":exp,"Alasan":reason,
            "Akurasi historis":f'{record["accuracy"]:.2%}',
            "Sampel":f'{record["correct"]}/{record["n"]}',
            "Bukti":record.get("run_url",""),
        })
    return out


def render_best_candidate_block(st, best, lock, r281, wib):
    st.markdown("### 8 kandidat terbaik · status inferensi terpisah")
    st.caption(
        "Kandidat BUY dan SELL adalah metode berbeda. H1/H4 menguji ulang "
        "aturan R25 BUY × R11 SELL pada candle cTrader tertutup. "
        "R28.1 tetap baseline tersendiri. Akurasi historis bukan skor live "
        "atau probabilitas order berhasil."
    )
    rows=candidate_runtime_rows(best,lock,r281)
    for tf in ("H1","H4"):
        record=(best or {}).get(tf) or {}
        with st.container(border=True):
            current=record.get("direction","WAIT")
            st.metric(tf+" · R25 BUY × R11 SELL (riset)",current)
            st.write(
                "**"+record.get("state","WAIT DATA")+"** · "
                +str(record.get("reason","FEED_UNAVAILABLE"))
            )
            if record.get("target"):
                st.caption("Candle target: "+wib(record["target"])
                           +" · diterbitkan: "+wib(record["issued"]))
                st.caption("R25 BUY: "+("TRIGGER" if record["buy_active"] else "TIDAK")
                           +" · R11 SELL: "+("TRIGGER" if record["sell_active"] else "TIDAK"))
                if record.get("buy_score") is not None:
                    st.caption("R25 skor BUY "+f'{record["buy_score"]:.4f}'
                               +" / ambang "+f'{record["buy_threshold"]:.2f}'
                               +" · gate "+str(record.get("buy_gate")))
            if record.get("expired_at"):
                st.caption("Sinyal telah berakhir: "+wib(record["expired_at"]))
            if current in ("BUY","SELL"):
                st.info(
                    "Prediksi kandidat RESEARCH SHADOW. Bukan otorisasi entry; "
                    "butuh forward validation dan konfirmasi SMC."
                )
    st.dataframe(
        [{**r, "Horizon":wib(r["Horizon"])} for r in rows],
        hide_index=True,width="stretch",
        column_config={"Bukti":st.column_config.LinkColumn(
            "Bukti replay",display_text="GitHub Actions")}
    )
    st.caption(
        "PERINGATAN: R11 SELL memiliki estimasi net P&L historis negatif; "
        "R25 H4 BUY 2026 hanya 12/28 benar. D1 SELL R18 dan W1 R27/R24 "
        "belum memiliki inferencer sisi valid untuk data kontemporer. "
        "Jangan menyimpulkan arah dari nilai akurasi historis."
    )
