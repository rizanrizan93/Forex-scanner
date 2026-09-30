from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def test_v240_dashboard_has_canonical_decision_map() -> None:
    assert "##### V240 — Canonical XAU Decision Map" in SOURCE
    assert "Satu sumber kebenaran untuk arah, Depth Candidate, entry, SL, TP" in SOURCE
    for label in (
        "Apa yang harus dilakukan sekarang",
        "Arah aktif V182",
        "Struktur aktif — bukan locator historis",
        "Demand terdekat",
        "Supply terdekat",
        "M15 confirmation",
        "M5 timing",
        "Entry riset historis — BUKAN ORDER",
        "Historical entry band",
        "Historical reference",
        "7 • Entry resmi",
        "7 • Zone watch (BUKAN ENTRY)",
        "8 • Dynamic Depth",
        "9 • Pressure / DOM",
        "10 • Execution Admission",
        "11 • SL resmi",
        "12 • TP order resmi",
        "13 • Path target (BUKAN TP order)",
        "14 • WAIT / BLOCK reason",
        "15 • Lifecycle",
        "16 • Session WIB",
    ):
        assert label in SOURCE


def test_v240_dashboard_uses_canonical_builder() -> None:
    assert "build_canonical_xau_decision" in SOURCE
    assert "v226_evaluation=v226_eval" in SOURCE
    assert "atlas_evaluation=dc_sd_eval" in SOURCE
    assert "price_now=dc_reference_price" in SOURCE


def test_v240_chart_uses_canonical_entry_and_structural_targets() -> None:
    assert "chart_structural_targets = list(v240_targets)" in SOURCE
    assert "direction=v240_direction" in SOURCE
    assert "dict(v240_entry_zone) if v240_effective_entry_authorized else {}" in SOURCE
    assert "entry_zone=chart_entry_zone" in SOURCE
    assert "structural_targets=chart_structural_targets" in SOURCE
    assert "current_direction=v240_direction" in SOURCE


def test_v240_stale_or_conflict_is_explicit_fail_closed() -> None:
    assert "**CONFLICT WAIT:**" in SOURCE
    assert "**STALE WAIT:**" in SOURCE
    assert "Jangan mengisi SL/TP dari panel lama secara manual." in SOURCE


def test_v240_reaction_metrics_are_not_mislabeled_as_trading_winrate() -> None:
    assert "Angka ini adalah reaction evidence, bukan win rate trading atau profit factor." in SOURCE



def test_v2401_dashboard_surfaces_primary_reversal_watch_without_overclaiming() -> None:
    assert "Primary Reversal Watch — area tujuan sebelum potensi reversal" in SOURCE
    assert "Area reversal utama" in SOURCE
    assert "P touch (research)" in SOURCE
    assert "P reaksi ≥0.50 ATR" in SOURCE
    assert "Touch×Reaction score" in SOURCE
    assert "bukan probabilitas terkalibrasi dan bukan izin entry" in SOURCE
    assert "Dashboard tidak mengarang probabilitas reversal." in SOURCE


def test_v249_pressure_transition_is_visible_in_canonical_dashboard():
    assert "Buyer / Seller Pressure — timing masuk zona" in SOURCE
    assert "Pressure transition" in SOURCE
    assert "Pre-touch DEMO" in SOURCE
    assert "M5-confirm DEMO" in SOURCE
    assert "evaluate_pressure_transition" in SOURCE


def test_v251_dynamic_depth_hazard_is_visible_in_canonical_dashboard():
    assert "Dynamic Depth Hazard — next depth / reversal window" in SOURCE
    assert "Next reversal band" in SOURCE
    assert "Hazard action" in SOURCE
    assert "build_dynamic_depth_hazard" in SOURCE


def test_v252_dashboard_surfaces_current_lifecycle_and_demo_execution():
    assert "Current Supply/Demand Lifecycle" in SOURCE
    assert "Riset lifecycle V226 historis" in SOURCE
    assert "current V182/V240" in SOURCE
    assert "V229 DEMO Execution — producer + child executor" in SOURCE
    assert "Execution phase" in SOURCE
    assert "Aksi child executor terbaru:" in SOURCE
    assert "Prior scope:" in SOURCE


def test_v240_mobile_operational_strip_has_price_session_gate_and_children() -> None:
    assert 'metric("Harga XAU sekarang"' in SOURCE
    assert 'metric("16 • Session WIB"' in SOURCE
    assert '"14 • WAIT / BLOCK reason"' in SOURCE
    assert "Child L1–L4 — status eksekusi DEMO" in SOURCE
    for slot in ("L1", "L2", "L3", "L4"):
        assert f'metric("{slot}"' in SOURCE


def test_v240_smartphone_sequence_matches_operational_contract() -> None:
    section_start = SOURCE.index("##### V240 — Canonical XAU Decision Map")
    section_end = SOURCE.index("##### V226 — RIZAN Depth Map")
    section = SOURCE[section_start:section_end]
    assert "Apa yang harus dilakukan sekarang" in section
    assert "Struktur aktif — bukan locator historis" in section
    assert "Entry → Dynamic Depth → Admission" in section
    assert "Risk & target" in section

    ordered = (
        "Apa yang harus dilakukan sekarang",
        "Struktur aktif — bukan locator historis",
        "Demand terdekat",
        "Supply terdekat",
        "M15 confirmation",
        "M5 timing",
        "Entry → Dynamic Depth → Admission",
        "8 • Dynamic Depth",
        "9 • Pressure / DOM",
        "10 • Execution Admission",
        "Risk & target",
        "11 • SL resmi",
        "12 • TP order resmi",
        "13 • Path target (BUKAN TP order)",
        "14 • WAIT / BLOCK reason",
        "15 • Lifecycle",
        "16 • Session WIB",
    )
    positions = [section.index(label) for label in ordered]
    assert positions == sorted(positions)


def test_v260_operational_cards_use_mobile_readable_layout() -> None:
    section_start = SOURCE.index("##### V240 — Canonical XAU Decision Map")
    section_end = SOURCE.index("##### V226 — RIZAN Depth Map")
    section = SOURCE[section_start:section_end]
    assert "flow1, flow2, flow3, flow4, flow5 = st.columns(5)" not in section
    assert "pr1, pr2, pr3, pr4 = st.columns(4)" not in section
    assert "hz1, hz2, hz3, hz4 = st.columns(4)" not in section
    assert "l1, l2, l3, l4 = st.columns(4)" not in section
    assert "**Alasan keputusan saat ini:**" in section
    assert "Penetration detail:" in section


def test_v261_historical_entry_is_visibly_non_operational() -> None:
    assert "Entry riset historis — BUKAN ORDER" in SOURCE
    assert "Ini hasil pemetaan riset V225/V226 pada source V182 aktif" in SOURCE
    assert "bukan order broker dan bukan win rate trading" in SOURCE
    assert "DEMO tetap menunggu pressure + fresh M5" in SOURCE
    assert "confirmation sebelum child order boleh dikirim." in SOURCE


def test_v262_dashboard_explains_rr_fail_closed_in_plain_language() -> None:
    assert "WAIT_TERMINAL_RR_BELOW_MINIMUM" in SOURCE
    assert "RR terminal struktural < 1,50R — NO ORDER" in SOURCE
    assert "**DEMO belum boleh entry karena RR struktural.**" in SOURCE
    assert "Scanner sengaja fail-closed" in SOURCE
    assert "WAIT_NO_FORWARD_STRUCTURAL_TARGET" in SOURCE


def test_v263_dashboard_separates_historical_entry_from_rr_confirmation_window() -> None:
    assert "RR-eligible M5 confirmation window" in SOURCE
    assert "RR threshold entry" in SOURCE
    assert "**Belum ada order.** Window ini hanya menunjukkan area" in SOURCE
    assert "L2 tetap OFF" in SOURCE
    assert "DEMO calibration probe" in SOURCE
    assert "L3/L4 tetap jalur strict" in SOURCE
    assert "TP/SL selalu dihitung dari struktur aktual" in SOURCE
    assert "CONFIRMATION_WINDOW_ARMED" in SOURCE
    assert "WAIT_NO_RR_ELIGIBLE_CONFIRMATION_WINDOW" in SOURCE


def test_v265_dashboard_has_four_layer_entry_map_and_overlap_status() -> None:
    assert "Peta Entry — riset → M5 → DEMO → broker" in SOURCE
    assert "1 • Historical research entry" in SOURCE
    assert "2 • M5 pocket saat ini" in SOURCE
    assert "3 • RR-eligible DEMO window" in SOURCE
    assert "4 • Official broker entry" in SOURCE
    assert "BELOW WINDOW • M5 masih terlalu dangkal untuk RR ≥1,50R" in SOURCE
    assert "OVERLAP • M5 sudah menyentuh RR-eligible window" in SOURCE
    assert "historical entry = prior riset" in SOURCE
    assert '"DEMO window = area yang secara struktural masih bisa memenuhi RR, official "' in SOURCE
    assert '"broker entry = baru ada setelah semua gate lolos. "' in SOURCE


def test_v266_dashboard_keeps_m5_visible_and_colors_reversal_heatmap() -> None:
    assert "PROJECTED_M5_WATCH" in SOURCE
    assert "Projected M5 Watch Pocket" in SOURCE
    assert "narrowing H4→H1→M15" in SOURCE
    assert "bukan entry broker" in SOURCE
    assert "Historical Reversal Depth Heatmap — V225.2 (2012–2026)" in SOURCE
    assert "is_highest_hazard" in SOURCE
    assert "#166534" in SOURCE
    assert "#65a30d" in SOURCE
    assert "#ca8a04" in SOURCE
    assert "#b91c1c" in SOURCE
    assert "Hazard adalah conditional reversal rate per depth band, bukan win rate order." in SOURCE
    assert "merah = reversal hazard rendah / NO-CHASE." in SOURCE


def test_v266_dashboard_explains_probe_and_strict_execution_lanes() -> None:
    assert "DEMO calibration probe 0,01 lot" in SOURCE
    assert "RR ≥1,00R" in SOURCE
    assert "post-rejection LIMIT retest" in SOURCE
    assert "maksimum 60 menit" in SOURCE
    assert "L3/L4 tetap jalur strict ≥1,50R" in SOURCE
    assert "L2 tetap OFF" in SOURCE


def test_v269_dashboard_separates_probe_no_chase_from_strict_confirmation() -> None:
    assert "PROBE NO-CHASE" in SOURCE
    assert "calibration_probe_depth_action" in SOURCE
    assert "calibration_probe_depth_eligible" in SOURCE
    assert "calibration_probe_depth_ceiling" in SOURCE
    assert "Status probe terpisah dari strict L3/L4" in SOURCE
    assert "strict masih wajib M5 reclaim/MSS" in SOURCE
    assert "Research ceiling L1 adalah 85%" in SOURCE


def test_v270_dashboard_explains_post_rejection_demo_retest_without_relaxing_strict_path() -> None:
    assert "post-rejection LIMIT retest" in SOURCE
    assert "closed M5 sudah reject keluar dari pocket" in SOURCE
    assert "Research ceiling L1 adalah 85%" in SOURCE
    assert "L3/L4 tetap jalur strict ≥1,50R" in SOURCE
    assert "opposing-zone RR ≥1,00R" in SOURCE


def test_v271_dashboard_separates_single_sample_demo_pressure_from_strict_transition() -> None:
    assert "current_sample_fresh" in SOURCE
    assert "calibration_entry_allowed" in SOURCE
    assert "DEMO CAL OK" in SOURCE
    assert "DEMO calibration pressure eligible" in SOURCE
    assert "strict L3/L4 tetap BLOCK sampai dua-sample transition valid" in SOURCE
    assert "absolute opposing pressure masih terlalu kuat" in SOURCE


def test_v275_dashboard_separates_fresh_l1_calibration_from_strict_slots() -> None:
    assert "V275/V276: fresh first-touch memakai radius arm adaptif." in SOURCE
    assert "Base ≤0,50 ATR" in SOURCE
    assert "sampai ≤1,00 ATR" in SOURCE
    assert "M30 parent overlap ≥70%" in SOURCE
    assert "composite pressure mendukung arah yang sama" in SOURCE
    assert "L1 DEMO 0,01 lot boleh" in SOURCE
    assert "L2/L3/L4 tetap strict" in SOURCE
    assert "FRESH_FIRST_TOUCH_CALIBRATION_ARMED" in SOURCE
    assert "L1 DEMO calibration armed — L2/L3/L4 tetap strict" in SOURCE


def test_v276_dashboard_explains_adaptive_early_arm_without_relaxing_strict_slots() -> None:
    assert "radius arm adaptif" in SOURCE
    assert "Base ≤0,50 ATR" in SOURCE
    assert "M30 parent overlap ≥70%" in SOURCE
    assert "composite pressure mendukung arah yang sama" in SOURCE
    assert "L2/L3/L4 tetap strict" in SOURCE


def test_v279_dashboard_uses_fresh_price_failover_instead_of_stale_prepared_only() -> None:
    assert "Price source=" in SOURCE
    assert "FP_MARKETS_CTRADER_QUOTE" in SOURCE
    assert "V182_LAST_CLOSED_M15" in SOURCE
    assert "V226_PRICE_REFERENCE" in SOURCE
    assert "PREPARED_LIVE_PRICE" in SOURCE
    assert "dc_price_candidates.sort" in SOURCE
    assert "dc_reference_price = (" in SOURCE
    assert "live_price = dc_reference_price" in SOURCE
    assert "execution authority tetap ForexRizan" in SOURCE


def test_v279_standalone_quote_overlay_loads_even_when_canonical_backend_exists() -> None:
    assert "Quote overlay is always loaded when available." in SOURCE
    assert "backend_error = direct_backend_error if backend is None else None" in SOURCE
    assert "standalone = _load_standalone_bridge(standalone_url)" in SOURCE


def test_v280_dashboard_shows_reversal_stages_and_no_chase_contract() -> None:
    assert "Tahap Reversal V280 — RISET/FORECAST → DEMO" in SOURCE
    assert "REVERSAL WATCH" in SOURCE
    assert "REAKSI TERLIHAT" in SOURCE
    assert "KONFIRMASI M5" in SOURCE
    assert "ENTRY DEMO DIIZINKAN" in SOURCE
    assert "BREAK RISK" in SOURCE
    assert "SETUP INVALID" in SOURCE
    assert "MISSED ENTRY — WAIT NEXT SETUP" in SOURCE
    assert "v240_effective_entry_authorized" in SOURCE
    assert "V225 tetap prior historis first-touch" in SOURCE


def test_v285_dashboard_shows_competing_risk_without_retest_probability_leak() -> None:
    assert "V281 Competing Risk — reversal vs break (RISET FIRST-TOUCH)" in SOURCE
    assert "Historical reversal ≥0,50 ATR" in SOURCE
    assert "Historical break / invalid" in SOURCE
    assert "Band pertama break historis mengungguli reversal" in SOURCE
    assert "conditional historical frequency, bukan" in SOURCE
    assert "V281 tidak dipakai sebagai peluang pada zona retest." in SOURCE
    assert "Historical pressure stratification memakai causal M1 OHLC proxy" in SOURCE
    assert "DOM live tetap sumber terpisah" in SOURCE


def test_v286_dashboard_surfaces_contextual_competing_risk_as_research_only() -> None:
    assert "V286 Contextual Competing Risk — RISET FIRST-TOUCH" in SOURCE
    assert "evaluate_v281_contextual_competing_risk" in SOURCE
    assert "Pressure proxy historis" in SOURCE
    assert "marginal contextual splits" in SOURCE
    assert "semantic bridge only" in SOURCE
    assert "Historical pressure memakai causal M1 OHLC proxy" in SOURCE
    assert "DOM live tetap cTrader Level-II" in SOURCE
    assert "tidak memberi execution authority/influence" in SOURCE
    assert "contextual prior tidak berlaku pada retest/reused zone" in SOURCE


def test_v287_dashboard_surfaces_forward_latency_without_claiming_performance() -> None:
    assert '"ctrader_demo_xau_prepared_plan_lifecycle"' in SOURCE
    assert "V282 Forward Latency — observability DEMO" in SOURCE
    assert "Touch → konfirmasi" in SOURCE
    assert "Konfirmasi → ready" in SOURCE
    assert "Ready → order accepted" in SOURCE
    assert "V280 entry dicegah" in SOURCE
    assert "Forward sample belum cukup untuk inferensi performa." in SOURCE
    assert "bukan untuk menyimpulkan win rate/PF/expectancy" in SOURCE
    assert "support cadence 1 jam" in SOURCE
    assert "Tidak ada polling baru per 60 detik." in SOURCE


def test_v289_all_official_broker_surfaces_obey_v280_effective_authorization() -> None:
    assert "v240_effective_entry_authorized" in SOURCE
    assert "V280 effective authorization veto" in SOURCE
    assert 'order_targets_authorized=v240_effective_entry_authorized' in SOURCE
    assert 'if not v240_effective_entry_authorized:' in SOURCE

    official_block = SOURCE[SOURCE.index('"4 • Official broker entry"'):]
    official_block = official_block[:900]
    assert "if v240_effective_entry_authorized" in official_block
    assert "if v240_entry_authorized" not in official_block

    chart_block = SOURCE[SOURCE.index("chart_entry_zone ="):]
    chart_block = chart_block[:8500]
    assert "v240_effective_entry_authorized" in chart_block
    assert "order_targets_authorized=v240_entry_authorized" not in chart_block

    execution_block = SOURCE[SOURCE.index('"### 3 • Eksekusi Sekarang"'):]
    execution_block = execution_block[:7500]
    assert '"Entry resmi"' in execution_block
    assert "v240_effective_entry_authorized" in execution_block
    assert "if v240_entry_authorized and v240_children" not in execution_block

    effective_block = SOURCE[SOURCE.index("v240_effective_entry_authorized = bool("):]
    effective_block = effective_block[:1100]
    assert 'v240_admission_label = (' in effective_block
    assert '"INVALIDATED" if v280_stage == "SETUP_INVALID" else "BLOCKED"' in effective_block
    assert 'v240_route_label = "NO ORDER"' in effective_block
