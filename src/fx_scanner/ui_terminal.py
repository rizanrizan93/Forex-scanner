"""Shared UI-only design system for the ForexScanner Streamlit terminal.

This module does not fetch quotes, inspect orders, write storage or change
strategy. It only renders presentation and escapes all variable HTML content.
The back-end continues to own all status and signal semantics.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

TERMINAL_CSS = """
<style>
:root {
  --rz-bg: #0b121c;
  --rz-surface: #121e2d;
  --rz-surface-hi: #172638;
  --rz-line: #29394d;
  --rz-text: #e8eff7;
  --rz-muted: #9facbd;
  --rz-teal: #46ccb9;
  --rz-red: #e98a8d;
  --rz-amber: #e5b66c;
}
html, body, [data-testid="stAppViewContainer"] { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
[data-testid="stAppViewContainer"] {
  background: radial-gradient(ellipse 90% 24rem at 8% -5%, rgba(54,122,139,.13), transparent 80%),
              var(--rz-bg);
  color: var(--rz-text);
}
[data-testid="stMainBlockContainer"] {
  max-width: 1660px !important;
  padding: 4.25rem clamp(.9rem, 2.25vw, 2.5rem) 4.5rem !important;
}
[data-testid="stMainBlockContainer"] h1, [data-testid="stMainBlockContainer"] h2,
[data-testid="stMainBlockContainer"] h3 { letter-spacing: -.025em; }
[data-testid="stMainBlockContainer"] h1 { font-size: clamp(1.45rem, 2.3vw, 2.2rem); font-weight: 680; }
[data-testid="stMainBlockContainer"] h2 { font-size: clamp(1.22rem, 1.7vw, 1.6rem); font-weight: 670; }
[data-testid="stMainBlockContainer"] h3 { font-size: 1.12rem; font-weight: 650; }
[data-testid="stMainBlockContainer"] p { line-height: 1.56; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--rz-muted) !important; }
[data-testid="stMetric"] {
  background: linear-gradient(170deg, rgba(22,37,54,.93), rgba(16,26,40,.93));
  border: 1px solid var(--rz-line);
  border-radius: 13px;
  padding: 15px 16px;
  min-height: 94px;
  box-shadow: 0 6px 19px rgba(0,0,0,.09);
}
[data-testid="stMetricLabel"] p {
  color: var(--rz-muted) !important;
  font-size: .79rem !important;
  letter-spacing: .035em;
}
[data-testid="stMetricValue"] {
  font-size: clamp(1.25rem, 2.15vw, 1.83rem) !important;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.028em;
}
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--rz-line);
  border-radius: 12px;
}
[data-testid="stExpander"], [data-testid="stDataFrame"] {
  border-color: var(--rz-line);
  border-radius: 12px;
}
[data-testid="stAlert"] {
  border-radius: 11px;
  border-width: 1px;
}
.stTabs [data-baseweb="tab-list"] {
  gap: .4rem;
  border-bottom: 1px solid var(--rz-line);
  overflow-x: auto;
  scrollbar-width: thin;
}
.stTabs [data-baseweb="tab"] {
  font-weight: 570;
  white-space: nowrap;
  border-radius: 8px 8px 0 0;
}
.stTabs [aria-selected="true"] {
  color: var(--rz-teal) !important;
}
.st-key-rizan_primary_navigation,
.st-key-rizan_xau_navigation {
  background: #101b29;
  border: 1px solid var(--rz-line);
  border-radius: 13px;
  padding: .4rem .55rem;
  isolation: isolate;
}
[data-testid="stLayoutWrapper"]:has(> .st-key-rizan_primary_navigation) {
  position: sticky;
  top: 3.45rem;
  z-index: 991;
  background: var(--rz-bg);
  padding-block: .25rem;
}
[data-testid="stLayoutWrapper"]:has(> .st-key-rizan_xau_navigation) {
  position: sticky;
  top: 7.55rem;
  z-index: 990;
  background: var(--rz-bg);
  padding-block: .25rem;
}
.st-key-rizan_primary_navigation [role="radiogroup"],
.st-key-rizan_xau_navigation [role="radiogroup"] {
  display: flex;
  align-items: center;
  gap: .38rem;
  flex-wrap: nowrap !important;
  overflow-x: auto;
  scrollbar-width: thin;
  padding: .14rem 0 .2rem;
}
.st-key-rizan_primary_navigation [role="radiogroup"] > label,
.st-key-rizan_xau_navigation [role="radiogroup"] > label {
  flex: 0 0 auto;
  white-space: nowrap;
  margin: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: .45rem .72rem;
  font-size: .86rem;
  font-weight: 570;
  transition: background .12s ease, border-color .12s ease;
}
.st-key-rizan_primary_navigation [role="radiogroup"] > label:hover,
.st-key-rizan_xau_navigation [role="radiogroup"] > label:hover {
  background: rgba(148,163,184,.11);
}
.st-key-rizan_primary_navigation [role="radiogroup"] > label:has(input:checked),
.st-key-rizan_xau_navigation [role="radiogroup"] > label:has(input:checked) {
  background: rgba(70,204,185,.13);
  color: #8ae6d9;
  border-color: rgba(70,204,185,.34);
}
.st-key-rizan_primary_navigation [role="radiogroup"] > label [data-testid="stMarkdownContainer"] p,
.st-key-rizan_xau_navigation [role="radiogroup"] > label [data-testid="stMarkdownContainer"] p {
  font-size: .86rem !important;
}
.st-key-rizan_primary_navigation [role="radiogroup"] > label [data-baseweb="radio"],
.st-key-rizan_xau_navigation [role="radiogroup"] > label [data-baseweb="radio"] {
  /* Keep keyboard/screen-reader access while removing the circular ornament. */
  position: absolute;
  width: 1px; height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}
.st-key-rizan_primary_navigation [role="radiogroup"] > label:focus-within,
.st-key-rizan_xau_navigation [role="radiogroup"] > label:focus-within {
  outline: 2px solid #8ae6d9;
  outline-offset: 2px;
}
.rz-brand {
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; padding: .15rem 0 1.18rem;
}
.rz-brand-left { display: flex; align-items: center; gap: .82rem; min-width: 0; }
.rz-logo {
  width: 43px; height: 43px; border-radius: 11px; display: grid;
  place-items: center; flex: 0 0 auto;
  background: #142e38; border: 1px solid rgba(70,204,185,.41);
  color: #91eadc; font-weight: 800; font-size: 1.18rem; letter-spacing: -.07em;
}
.rz-brand-name { color: var(--rz-text); font-weight: 740; letter-spacing: .085em; font-size: 1rem; }
.rz-brand-sub { color: var(--rz-muted); font-size: .74rem; letter-spacing: .115em; margin-top: .18rem; }
.rz-brand-side { text-align: right; color: var(--rz-muted); font-size: .74rem; white-space: nowrap; }
.rz-brand-side strong { color: #d7e4ef; font-size: .81rem; font-weight: 630; display: block; }
.rz-section-intro { padding: 1rem .05rem .8rem; border-bottom: 1px solid var(--rz-line); margin-bottom: 1.2rem; }
.rz-eyebrow { color: var(--rz-teal); font-size: .68rem; font-weight: 780; letter-spacing: .15em; text-transform: uppercase; }
.rz-section-title { margin: .32rem 0 .23rem; color: var(--rz-text); font-weight: 700; font-size: clamp(1.18rem, 2vw, 1.6rem); letter-spacing: -.035em; }
.rz-section-desc { color: var(--rz-muted); font-size: .83rem; line-height: 1.53; }
.rz-note { font-size: .77rem; color: var(--rz-muted); line-height: 1.55; padding: .55rem 0; }
.rz-progress-track { display: flex; overflow: hidden; height: 5px; background: #253347; border-radius: 99px; width: 100%; margin: .65rem 0 .4rem; }
.rz-progress-pass { background: #54c7b5; }
.rz-progress-fail { background: #d87d83; }
.rz-progress-unknown { background: #566a81; }
.rz-progress-label { display: flex; justify-content: space-between; gap: 1rem; color: var(--rz-muted); font-size: .78rem; }
.rz-condition {
  display: flex; align-items: flex-start; gap: .78rem;
  padding: .88rem .95rem; border: 1px solid var(--rz-line);
  border-radius: 11px; background: rgba(19,31,46,.73);
  margin: .44rem 0;
}
.rz-condition.pass { border-left: 3px solid #53c1af; }
.rz-condition.fail { border-left: 3px solid #d18189; }
.rz-condition.unknown { border-left: 3px solid #8596aa; }
.rz-condition-icon {
  display: grid; place-items: center; width: 24px; height: 24px; border-radius: 6px;
  flex: 0 0 auto; font-size: .87rem; font-weight: 750;
  background: #223044; color: #9cacbe; margin-top: .08rem;
}
.rz-condition.pass .rz-condition-icon { color: #86e6d5; background: rgba(57,183,165,.15); }
.rz-condition.fail .rz-condition-icon { color: #ffc0c4; background: rgba(220,113,127,.13); }
.rz-condition-body { min-width: 0; flex: 1; }
.rz-condition-top { display: flex; flex-wrap: wrap; align-items: center; gap: .35rem .7rem; justify-content: space-between; }
.rz-condition-title { color: var(--rz-text); font-size: .88rem; font-weight: 645; }
.rz-condition-status { color: var(--rz-muted); font-size: .69rem; font-weight: 720; letter-spacing: .055em; text-transform: uppercase; }
.rz-condition.pass .rz-condition-status { color: #86e6d5; }
.rz-condition.fail .rz-condition-status { color: #f1a7b1; }
.rz-condition-detail { margin-top: .35rem; color: #b4c0d0; font-size: .79rem; line-height: 1.53; overflow-wrap: anywhere; }
.rz-condition-meta { margin-top: .4rem; color: #889bb0; font-size: .71rem; overflow-wrap: anywhere; }
@media (max-width: 850px) {
  [data-testid="stMainBlockContainer"] { padding: 3.55rem .72rem 3rem !important; }
  [data-testid="stLayoutWrapper"]:has(> .st-key-rizan_primary_navigation) { top: 2.9rem; }
  [data-testid="stLayoutWrapper"]:has(> .st-key-rizan_xau_navigation) { top: 6.85rem; }
  .rz-brand { gap: .55rem; padding-bottom: .7rem; }
  .rz-logo { width: 36px; height: 36px; }
  .rz-brand-name { font-size: .9rem; }
  .rz-brand-sub { font-size: .62rem; letter-spacing: .05em; }
  .rz-brand-side { font-size: .65rem; }
  .rz-brand-side strong { font-size: .69rem; }
  .st-key-rizan_primary_navigation,
  .st-key-rizan_xau_navigation { padding: .31rem .4rem; }
  .st-key-rizan_primary_navigation [role="radiogroup"] > label,
  .st-key-rizan_xau_navigation [role="radiogroup"] > label { padding: .39rem .54rem; }
  [data-testid="stMetric"] { padding: .7rem .75rem; min-height: 75px; }
  .rz-condition { padding: .7rem .67rem; gap: .53rem; }
  .rz-condition-title { font-size: .83rem; }
}
@media (prefers-reduced-motion: reduce) {
  * { scroll-behavior: auto !important; transition-duration: 0ms !important; }
}
</style>
"""


def _safe(value: object) -> str:
    return escape(str(value), quote=True)


def render_brand(st) -> None:
    """Brand and timezone only; deliberately no claimed live market/bridge status."""
    local = datetime.now(ZoneInfo("Asia/Jakarta"))
    stamp = local.strftime("%d %b %Y · %H:%M WIB").upper()
    st.markdown(
        '<div class="rz-brand">'
        '<div class="rz-brand-left"><div class="rz-logo" aria-hidden="true">R</div>'
        '<div><div class="rz-brand-name">RIZAN<span style="color:#75d4c6"> / </span>FOREXSCANNER</div>'
        '<div class="rz-brand-sub">MARKET INTELLIGENCE WORKSPACE</div></div></div>'
        '<div class="rz-brand-side"><strong>ANALYTICS DESK</strong>'
        + _safe(stamp) + '</div></div>',
        unsafe_allow_html=True,
    )


SECTION_DESCRIPTIONS = {
    "Zona reversal": ("REACTION ZONES", "Peta zona reaksi", "Pemantauan zona teknikal; harga dan status validasi berasal dari mesin masing-masing."),
    "Zona A→B": ("PREDICTIVE MAP", "Zona prediktif A→B", "Level dan pemicu teknikal untuk dipantau, bukan instruksi order."),
    "Setup": ("TRADE PREPARATION", "Setup & eksekusi", "Ringkasan setup dan konteks, sesuai status sebenarnya dari sistem."),
    "Hierarki zona": ("MARKET STRUCTURE", "Hierarki zona", "Urutan prioritas zona berdasarkan struktur dan umur candle."),
    "Keputusan": ("DECISION DESK", "Pusat keputusan XAU", "Konfirmasi struktur, makro, dan status sumber sebelum entry."),
    "Analisis Terpadu": ("CONFLUENCE DESK", "Checklist · SMC/ICT · USD Lead", "Satu keputusan analisis XAUUSD dengan validasi data, yield, struktur, dan risiko secara terpisah."),
    "Checklist": ("ENTRY READINESS", "Checklist XAUUSD", "Syarat BUY dan SELL ditampilkan terpisah, termasuk data yang belum valid."),
    "Teknikal": ("PRICE STRUCTURE", "Teknikal XAU · SMC / ICT", "Struktur H1, lokasi M15 dan konfirmasi M5 dengan checklist BUY/SELL."),
    "USD Lead": ("CROSS-ASSET INTELLIGENCE", "USD Lead & Yield", "Ekspektasi Fed, dolar, yield dan validasi arah XAU—research-only."),
    "Demand": ("LIQUIDITY DESK", "Demand & supply", "Area demand dan supply untuk penilaian risiko dan lokasi."),
    "Pre-News": ("EVENT INTELLIGENCE", "Pre-News Expectation", "Pembacaan skenario kejutan rilis makro dan sumber prakiraan."),
    "Makro": ("RATES & MACRO", "Treasury & arah makro", "Yield resmi dan proksi intraday dipisahkan menurut freshness dan frekuensi."),
    "Pengaturan": ("WORKSPACE", "Pengaturan", "Pengaturan dan referensi dashboard."),
    "EURUSD": ("FX DESK", "EURUSD", "Analisis pasangan EURUSD dan sumber pasar tersedia."),
    "cBots": ("STRATEGY MONITOR", "cBots V1", "Status observasi cBot; status monitor bukan konfirmasi eksekusi order."),
}


def render_section_intro(st, *, pair: str, detail: str) -> None:
    key = detail if pair == "XAUUSD" else pair
    eyebrow, title, description = SECTION_DESCRIPTIONS.get(
        key, ("MARKET DESK", key, "Panel analitik ForexScanner.")
    )
    st.markdown(
        '<div class="rz-section-intro"><div class="rz-eyebrow">' + _safe(eyebrow)
        + '</div><div class="rz-section-title">' + _safe(title) + '</div>'
        '<div class="rz-section-desc">' + _safe(description) + '</div></div>',
        unsafe_allow_html=True,
    )


def render_page_intro(st, *, eyebrow: str, title: str, description: str) -> None:
    """Reusable inside focused decision and macro pages."""
    st.markdown(
        '<div class="rz-section-intro"><div class="rz-eyebrow">' + _safe(eyebrow)
        + '</div><div class="rz-section-title">' + _safe(title) + '</div>'
        '<div class="rz-section-desc">' + _safe(description) + '</div></div>',
        unsafe_allow_html=True,
    )


STATUS_DETAILS = {
    "PASS": ("pass", "✓", "TERPENUHI"),
    "FAIL": ("fail", "×", "BELUM TERPENUHI"),
    "UNKNOWN": ("unknown", "–", "DATA BELUM VALID"),
}


def condition_html(*, title: str, state: str, detail: str, meta: str = "") -> str:
    """No markup is taken from an external quote/provider without escaping."""
    style, icon, label = STATUS_DETAILS.get(state, STATUS_DETAILS["UNKNOWN"])
    meta_html = (
        '<div class="rz-condition-meta">' + _safe(meta) + '</div>'
        if meta else ""
    )
    return (
        '<div class="rz-condition ' + style + '">'
        '<div class="rz-condition-icon" aria-hidden="true">' + icon + '</div>'
        '<div class="rz-condition-body"><div class="rz-condition-top">'
        '<span class="rz-condition-title">' + _safe(title) + '</span>'
        '<span class="rz-condition-status">' + label + '</span></div>'
        '<div class="rz-condition-detail">' + _safe(detail) + '</div>'
        + meta_html + '</div></div>'
    )


def render_condition(st, *, title: str, state: str, detail: str, meta: str = "") -> None:
    st.markdown(
        condition_html(title=title, state=state, detail=detail, meta=meta),
        unsafe_allow_html=True,
    )


def progress_html(*, passed: int, failed: int, unknown: int, total: int) -> str:
    if total <= 0:
        return ""
    p = max(0, min(total, passed))
    f = max(0, min(total-p, failed))
    u = max(0, min(total-p-f, unknown))
    return (
        '<div class="rz-progress-track" role="img" aria-label="'
        + _safe(f"{p} terpenuhi, {f} belum, {u} tidak valid dari {total}")
        + '"><div class="rz-progress-pass" style="width:' + str(100*p/total) + '%"></div>'
        '<div class="rz-progress-fail" style="width:' + str(100*f/total) + '%"></div>'
        '<div class="rz-progress-unknown" style="width:' + str(100*u/total) + '%"></div></div>'
        '<div class="rz-progress-label"><span>' + f"{p}/{total} terpenuhi" + '</span>'
        '<span>' + f"{f} belum · {u} data belum valid" + '</span></div>'
    )


def render_progress(st, *, passed: int, failed: int, unknown: int, total: int) -> None:
    st.markdown(
        progress_html(passed=passed, failed=failed, unknown=unknown, total=total),
        unsafe_allow_html=True,
    )
