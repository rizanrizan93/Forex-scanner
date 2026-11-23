"""R29.1 H4 historical high-coverage frozen alternative.

Research-only immutable benchmark display; deliberately DOES NOT fetch,
publish, or surface live BUY signals from losing 2026 carry-forward policy.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]
LOCK=ROOT/"research/RIZAN_R291_H4_BUY_COVERAGE_FROZEN_20261123.json"
DIAG=ROOT/"research/RIZAN_R296_H4_COVERAGE_CARRY_2026_DIAGNOSTIC.json"
ORIGINAL_SHA="943e82b27b27c519774e7046aa313391633bdfb42ea17e6c187059e3931ad1fc"

def load_verified():
    freeze=json.loads(LOCK.read_text())
    diag=json.loads(DIAG.read_text())
    if (freeze.get("source_json_sha256")!=ORIGINAL_SHA
            or freeze.get("id")!="RIZAN_R291_H4_BUY_HIGH_COVERAGE_HISTORICAL_FROZEN_20261123"
            or freeze.get("research_only") is not True
            or freeze.get("execution_authority") is not False
            or freeze.get("historical_pooled",{}).get("n")!=332
            or freeze.get("historical_pooled",{}).get("correct")!=199
            or diag.get("frozen_lock_source_sha256")!=ORIGINAL_SHA
            or diag.get("source_run_id")!=45178443988
            or diag.get("execution_authority") is not False
            or diag.get("decision")!="LOCK_AS_HISTORICAL_FREQUENCY_REFERENCE_NOT_SIGNAL_PROMOTION"
            or set(freeze.get("annual_policies",{}))!={"2024","2025","2026"}):
        raise ValueError("R296_FROZEN_HISTORY_EVIDENCE_NOT_VERIFIED")
    expected={"2024":(143,83),"2025":(176,108),"2026":(13,8)}
    for yr,(n,k) in expected.items():
        e=freeze["annual_policies"][yr]["evaluation"]
        if e.get("n")!=n or e.get("correct")!=k:
            raise ValueError("R296_ANN_FOLD_MISMATCH_"+yr)
    carry=diag.get("carry_2025_to_2026",{})
    if ((carry.get("n"),carry.get("correct"))!=(111,54)
            or carry.get("positive_net_estimate") is not False):
        raise ValueError("R296_CARRY_FORWARD_DIAGNOSTIC_MISMATCH")
    return freeze,diag


def render_h4_high_coverage_reference(st):
    st.markdown("### H4 BUY · R29.1 High Coverage (FROZEN HISTORIS)")
    try:
        archive,receipt=load_verified()
    except (OSError,ValueError,KeyError,TypeError):
        st.warning("Arsip R29.1 belum dapat diverifikasi; kandidat tidak ditampilkan.")
        return
    with st.container(border=True):
        a,b=st.columns(2)
        a.metric("R29.1 · Sinyal historis", "332")
        b.metric("R29.2 · Sinyal historis", "126")
        st.caption("R29.1: 199/332 = 59,94% · R29.2: 79/126 = 62,70%. "
                   "Keduanya menggabungkan konfigurasi tahunan berbeda, "
                   "bukan akurasi live.")
        st.dataframe([
            {
                "Tahun":int(year),
                "Model":entry["policy"]["model"],
                "Setup":entry["policy"]["gate"],
                "Ambang":entry["policy"]["threshold"],
                "Sinyal":entry["evaluation"]["n"],
                "Benar":entry["evaluation"]["correct"],
                "Akurasi":f'{entry["evaluation"]["accuracy"]:.2%}',
                "Net estimasi USD/oz":entry["evaluation"]["net_mean_after_assumed_cost_usd_oz"],
            }
            for year,entry in archive["annual_policies"].items()
        ],hide_index=True,width="stretch")
        carry=receipt["carry_2025_to_2026"]
        st.warning("STATUS: FROZEN RESEARCH · TIDAK DIPROMOSIKAN MENJADI SINYAL ENTRY. "
                   "Konfigurasi banyak-sinyal tahun 2025 ketika digunakan tetap "
                   "di 2026 hanya benar 54/111 (48,65%) dengan net estimasi "
                   "−$3,20/oz. Konfigurasi pilihan 2026 sendiri hanya "
                   "menghasilkan 13 sinyal dan net estimasi negatif.")
        st.caption("R29.1 tetap tersedia sebagai pembanding frekuensi untuk "
                   "riset selanjutnya. Sinyal yang dipakai untuk pantauan "
                   "sekarang tetap panel R29.2 H4 BUY yang terpisah; "
                   "keduanya tidak memiliki otoritas eksekusi.")
