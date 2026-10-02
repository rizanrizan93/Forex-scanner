from __future__ import annotations

from typing import Any

import streamlit as st

from fx_scanner.xau_public_hot_v362 import fetch_public_hot_snapshot


def num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def px(value: Any) -> str:
    value = num(value)
    return "—" if value is None else f"{value:,.2f}"


def reaction_cluster(evaluation: dict[str, Any]) -> dict[str, Any]:
    price = num(evaluation.get("price_now"))
    levels = list(
        dict(evaluation.get("support_resistance_map") or {}).get("levels") or []
    )
    if price is None:
        return {}
    rows = []
    for raw in levels:
        row = dict(raw or {})
        level = num(row.get("price"))
        role = str(row.get("current_role") or row.get("kind") or "").upper()
        if level is None or level > price:
            continue
        if role in {"SUPPORT", "FLIP", "SUPPORT_FLIP_CANDIDATE"}:
            rows.append(row)
    if not rows:
        return {}
    rows.sort(
        key=lambda row: (
            abs(float(row.get("price") or 0.0) - price),
            -float(row.get("strength") or 0.0),
        )
    )
    anchor = rows[0]
    anchor_px = float(anchor["price"])
    lo = num(anchor.get("band_low"))
    hi = num(anchor.get("band_high"))
    width = max((hi - lo) if lo is not None and hi is not None else 1.0, 1.0)
    atr_estimate = width / 0.11
    group = [
        row
        for row in rows
        if abs(float(row.get("price") or 0.0) - anchor_px) <= 0.80 * atr_estimate
    ]
    return {
        "low": min(num(row.get("band_low")) or float(row["price"]) for row in group),
        "high": max(num(row.get("band_high")) or float(row["price"]) for row in group),
        "anchor": anchor_px,
        "levels": [float(row["price"]) for row in group],
        "states": sorted(
            {str(row.get("lifecycle_state") or "UNKNOWN") for row in group}
        ),
    }


def next_main_demand(evaluation: dict[str, Any]) -> dict[str, Any]:
    ladder = dict(evaluation.get("failure_destination_ladder") or {})
    primary = dict(ladder.get("primary") or {})
    if str(primary.get("direction") or "").upper() == "LONG":
        return primary
    path = dict(evaluation.get("failure_path") or {})
    for raw in list(path.get("checkpoints") or []):
        row = dict(raw or {})
        if row.get("type") != "ZONE":
            continue
        if str(row.get("direction") or "LONG").upper() == "LONG":
            return row
    return {}


st.set_page_config(page_title="RIZAN Demand Map", layout="wide")
st.title("RIZAN — Peta Demand Bertingkat")
st.caption(
    "Reaction support, main H4 reversal demand, dan demand berikutnya dipisahkan "
    "agar level reaksi dekat tidak hilang ketika parent H4 berpindah."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Public HOT snapshot belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

heartbeat = {}
for raw in list(snapshot.get("heartbeats") or []):
    row = dict(raw or {})
    if row.get("worker_name") == "ctrader_demo_xau_sd_liquidity_v342":
        heartbeat = row
        break

evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
if not evaluation:
    st.warning("Snapshot V342 belum tersedia.")
    st.stop()

price = evaluation.get("price_now")
reaction = reaction_cluster(evaluation)
main = dict(evaluation.get("main_reversal_zone") or evaluation.get("decision_zone") or {})
if str(main.get("direction") or "").upper() != "LONG":
    main = {}
next_main = next_main_demand(evaluation)

st.metric("Harga XAU snapshot", px(price))
c1, c2, c3 = st.columns(3)
c1.metric(
    "1 • Nearest reaction support",
    f"{px(reaction.get('low'))}–{px(reaction.get('high'))}" if reaction else "—",
)
c2.metric(
    "2 • Main reversal demand",
    f"{px(main.get('low'))}–{px(main.get('high'))}" if main else "—",
)
c3.metric(
    "3 • Next main jika gagal",
    f"{px(next_main.get('low'))}–{px(next_main.get('high'))}"
    if next_main
    else "belum terpetakan",
)

if reaction:
    st.info(
        f"Reaction cluster {px(reaction.get('low'))}–{px(reaction.get('high'))} "
        f"berisi level {', '.join(px(v) for v in reaction.get('levels') or [])}. "
        "Ini area reaksi struktural, bukan otomatis main reversal."
    )
if main:
    st.success(
        f"Main H4 demand aktif: {px(main.get('low'))}–{px(main.get('high'))} • "
        f"condition={main.get('condition','—')} • "
        f"quality={num(main.get('main_reversal_score')) or 0.0:.1f}."
    )
if not next_main:
    st.caption(
        "Belum ada demand H4 lebih bawah yang memenuhi syarat pada snapshot HOT saat ini. "
        "Tidak ada level tambahan yang dipaksakan."
    )

with st.expander("Detail lifecycle reaction support"):
    st.write(reaction.get("states") or [])
