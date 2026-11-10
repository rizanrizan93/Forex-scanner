"""Display BUY050 evidence chronology without confusing positions and orders."""
from __future__ import annotations
import json
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

CONTRACT="RIZAN_BUY050_EVENT_TIMELINE_V1"
PROFILE="13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"
URL=("https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
     "buy050-event-audit/runtime/buy050_event_timeline.json")
NAMES={
    "SIGNAL_RECORDED":"Sinyal tercatat native",
    "SIGNAL_CHANGED_DURING_GAP":"Sinyal berubah saat monitor tidak aktif",
    "INTENT_PREPARED":"Intent order disiapkan",
    "BASKET_STATE_ACTIVE":"Basket ada pada checkpoint",
    "QUARANTINE_ON":"Quarantine terdeteksi",
    "FAULT_ON":"Native fault terdeteksi",
    "EXIT_PENDING_ON":"Exit pending terdeteksi",
    "CHECKPOINT_RESET":"Versi checkpoint menurun",
    "BROKER_OPEN_POSITION_OBSERVED":"Posisi BUY050 terbuka terverifikasi broker",
    "BROKER_ORDER_ACCEPTED":"Order BUY050 diterima broker",
    "BROKER_ORDER_FILLED":"Order BUY050 berstatus FILLED",
    "BROKER_ORDER_REJECTED":"Order BUY050 ditolak broker",
    "BROKER_ORDER_CANCELLED":"Order BUY050 dibatalkan",
    "BROKER_ORDER_EXPIRED":"Order BUY050 kedaluwarsa",
    "BROKER_DEAL_FILLED":"Deal BUY050 FILLED (bukti eksekusi)",
    "BROKER_DEAL_PARTIAL":"Deal BUY050 terisi sebagian",
    "BROKER_DEAL_REJECTED":"Deal BUY050 ditolak",
    "BROKER_DEAL_ERROR":"Deal BUY050 mengalami error eksekusi",
    "BROKER_DEAL_NO_RESPONSE":"Deal BUY050 tanpa respons LP (MISSED)",
}
SYMBOLS=("XAUUSD","EURUSD","BTCUSD")
TZ=ZoneInfo("Asia/Jakarta")

def dt(value):
    try:
        x=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return x.astimezone(timezone.utc) if x.tzinfo else None
    except (TypeError,ValueError,OverflowError):
        return None

def wib(value):
    t=dt(value)
    return t.astimezone(TZ).strftime("%d/%m %H:%M:%S WIB") if t else "—"

def evaluate_timeline(raw,*,now=None):
    now=now or datetime.now(timezone.utc)
    if (not isinstance(raw,dict) or raw.get("contract")!=CONTRACT
        or raw.get("strategy")!="P3_BUY050" or raw.get("profile_sha256")!=PROFILE
        or raw.get("read_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("execution_influence") is not False
        or raw.get("terminal_journal_available") is not False
        or type(raw.get("broker_deals_verified")) is not bool
        or type(raw.get("broker_orders_history_complete",False)) is not bool):
        raise ValueError("INVALID_BUY050_TIMELINE")
    started,ended=dt(raw.get("started_at")),dt(raw.get("ended_at"))
    if not started or not ended or ended<started or ended>now+timedelta(seconds=30):
        raise ValueError("TIMELINE_CLOCK_INVALID")
    age=(now-ended).total_seconds()
    hist_from,hist_to=dt(raw.get("broker_history_from")),dt(raw.get("broker_history_to"))
    if (raw.get("broker_deals_verified") is True or raw.get("broker_orders_history_complete") is True) and (
        not hist_from or not hist_to or not hist_from<=hist_to<=now+timedelta(seconds=30)
    ):
        raise ValueError("BROKER_HISTORY_UNATTESTED")
    rows=raw.get("events")
    if not isinstance(rows,list) or len(rows)>120:
        raise ValueError("TIMELINE_EVENTS_INVALID")
    clean=[]
    for r in rows:
        if (not isinstance(r,dict) or r.get("symbol") not in SYMBOLS
            or r.get("event") not in NAMES or not dt(r.get("observed_at"))):
            raise ValueError("TIMELINE_EVENT_INVALID")
        if dt(r["observed_at"])>now+timedelta(seconds=30):
            raise ValueError("TIMELINE_FUTURE_EVENT")
        clean.append(r)
    # Sampling happens on the VPS once per second during the job. Publishing
    # happens only once per workflow. No claim of continuous live streaming.
    fresh=-30<=age<=900
    gap=raw.get("unobserved_gap_s")
    if gap is not None and (type(gap) not in (int,float) or gap<0):
        raise ValueError("INVALID_COVERAGE_GAP")
    return {
        "fresh":fresh,"age_seconds":age,"events":list(reversed(clean)),
        "started_at":raw.get("started_at"),"ended_at":raw.get("ended_at"),
        "samples":raw.get("samples"),"failures":raw.get("failures"),
        "max_interval_s":raw.get("max_interval_s"),"unobserved_gap_s":gap,
        "broker_open_positions_observed":raw.get("broker_open_positions_observed") is True,
        "broker_observed_at":raw.get("broker_observed_at"),
        "continuous_coverage_confirmed":raw.get("continuous_coverage_confirmed") is True,
        "broker_deals_verified":raw.get("broker_deals_verified") is True,
        "broker_orders_history_complete":raw.get("broker_orders_history_complete") is True,
        "broker_history_from":raw.get("broker_history_from"),
        "broker_history_to":raw.get("broker_history_to")
    }

def fetch(slot):
    req=Request(URL+"?slot="+str(slot),headers={"User-Agent":"RIZAN-BUY050-event-audit"})
    with urlopen(req,timeout=8) as response:
        data=response.read(70_001)
    if len(data)>70_000:
        raise ValueError("TIMELINE_TOO_LARGE")
    return json.loads(data)

def render_timeline(raw,*,now=None):
    import streamlit as st
    view=evaluate_timeline(raw,now=now)
    st.markdown("#### Audit sinyal → intent → posisi broker")
    st.caption("Sumber: checkpoint BUY050 pada VPS (sampel 1 detik selama job), lalu rekonsiliasi posisi terbuka di broker. Tidak mengubah cBot LIVE.")
    st.caption("Jendela teramati: "+wib(view["started_at"])+" sampai "+wib(view["ended_at"]))
    c1,c2,c3=st.columns(3)
    c1.metric("Sampel",str(view["samples"] or 0))
    c2.metric("Gangguan baca",str(view["failures"] or 0))
    c3.metric("Celah sebelum job",f'{view["unobserved_gap_s"]:.0f} dtk' if view["unobserved_gap_s"] is not None else "Tidak diketahui")
    if not view["fresh"]:
        st.warning("Audit belum diperbarui dalam 15 menit. Riwayat ditampilkan sebagai arsip, bukan status LIVE.")
    if not view["continuous_coverage_confirmed"]:
        st.info("Cakupan belum kontinu: sinyal pada jeda antar-job atau saat pembacaan gagal mungkin tidak tertangkap langsung. Jangan artikan riwayat kosong sebagai tidak ada sinyal.")
    gap = view["unobserved_gap_s"]
    if gap is not None and gap > 60:
        st.warning(f"CELAH MONITORING {gap / 60:.1f} menit · jeda sebelum job berikutnya "
                   "dapat menyembunyikan perubahan sinyal. Audit ini bukan streaming 24/7.")
    if not view["broker_open_positions_observed"]:
        st.caption("Rekonsiliasi posisi broker pada publikasi ini belum tersedia. Tidak ada keputusan FILLED/REJECTED yang dapat dipastikan.")
    if view["broker_deals_verified"]:
        st.caption("Histori deal broker dibaca untuk jendela "+wib(view["broker_history_from"])+" – "+wib(view["broker_history_to"])+". Status FILLED/REJECTED hanya dari record broker yang cocok.")
    else:
        st.caption("Histori deal belum lengkap atau tidak tersedia. Tanpa record broker yang cocok, status eksekusi tetap UNKNOWN.")
    if not view["broker_orders_history_complete"]:
        st.caption("Histori order broker belum lengkap. Terminal journal native juga belum terhubung.")
    st.caption("Posisi terbuka merupakan bukti positif; tidak ditemukannya posisi bukan bukti order gagal atau sinyal terlewat.")
    if not view["events"]:
        st.caption("Tidak ada peristiwa yang teramati pada sampel audit ini. "
                   "Ini BUKAN bukti bahwa strategi tidak memberi sinyal ataupun "
                   "bahwa tidak ada order di luar jendela pemantauan.")
    else:
        display=[]
        for item in view["events"][:24]:
            display.append({
                "Waktu diamati":wib(item["observed_at"]),
                "Instrumen":item["symbol"],
                "Peristiwa":NAMES[item["event"]],
                "Waktu sinyal":wib(item.get("signal_at")),
                "Bukti":item.get("evidence") or "Tidak dapat dipastikan",
                "Proteksi":item.get("protection") or "—",
            })
        st.dataframe(display,hide_index=True,width="stretch")
    st.caption("Order ACCEPTED, FILLED, dan REJECTED hanya ditampilkan jika ada record broker historis dengan label strategi yang cocok. Sinyal yang tidak diikuti record broker tetap UNKNOWN, bukan otomatis terlewat.")

def render_audit_panel():
    import streamlit as st
    @st.cache_data(ttl=45,show_spinner=False)
    def cached(slot):
        return fetch(slot)
    try:
        now=datetime.now(timezone.utc)
        render_timeline(cached(int(now.timestamp()//45)),now=now)
    except (OSError,ValueError,TypeError,KeyError,TimeoutError):
        st.markdown("#### Audit sinyal → intent → posisi broker")
        st.warning("Feed audit BUY050 belum tersedia atau tidak valid. Status eksekusi belum dapat dikonfirmasi.")
