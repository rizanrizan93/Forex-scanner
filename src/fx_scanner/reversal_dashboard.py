"""Scanner-only reversal map, historical evidence and explicit data freshness."""
from datetime import UTC, datetime
import json
import re
from functools import lru_cache
from urllib.request import Request, urlopen
from .reversal_scanner import load_result
from .reversal_zones import CONTRACT

SNAPSHOT_URL="https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/scanner-reversal-snapshots/runtime/reversal_snapshot.json"


def validate_snapshot(snapshot, *, now=None):
    if snapshot.get("contract")!=CONTRACT or snapshot.get("symbol")!="XAUUSD" or snapshot.get("execution_authority") is not False:
        raise ValueError("REVERSAL_SNAPSHOT_CONTRACT_INVALID")
    observed=datetime.fromisoformat(snapshot["as_of"].replace("Z","+00:00"))
    if observed.tzinfo is None: raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    age=((now or datetime.now(UTC))-observed).total_seconds()
    if not -5<=age<=420 or snapshot.get("state") not in {"MAP_READY","NO_ACTIVE_VALIDATED_ZONE"}:
        raise ValueError("REVERSAL_SCANNER_STALE_OR_UNAVAILABLE")
    return snapshot


def _read_json(url):
    req=Request(url,headers={"User-Agent":"RIZAN-Reversal-Scanner","Cache-Control":"no-cache"})
    with urlopen(req,timeout=10) as response:
        data=response.read(256001)
    if len(data)>256000: raise ValueError("REVERSAL_SNAPSHOT_TOO_LARGE")
    return json.loads(data)


@lru_cache(maxsize=2)
def _snapshot_commit(bucket):
    # Resolve public branch metadata at most once/90s on stale CDN reads.
    ref=_read_json('https://api.github.com/repos/rizanrizan93/Forex-scanner/git/ref/heads/scanner-reversal-snapshots')
    sha=str(ref.get('object',{}).get('sha',''))
    if not re.fullmatch('[0-9a-f]{40}',sha): raise ValueError('INVALID_SNAPSHOT_COMMIT')
    return sha


def fetch_snapshot():
    snapshot=_read_json(SNAPSHOT_URL)
    try:
        return validate_snapshot(snapshot)
    except ValueError as exc:
        if str(exc)!='REVERSAL_SCANNER_STALE_OR_UNAVAILABLE': raise
        # Cache-Control alone does not invalidate mutable GitHub CDN branches.
        sha=_snapshot_commit(int(datetime.now(UTC).timestamp()//90))
        snapshot=_read_json('https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/'+sha+'/runtime/reversal_snapshot.json')
        return validate_snapshot(snapshot)


def _render_reversal_dashboard():
    import streamlit as st
    st.subheader("XAU · zona reversal & waktu terbaik")
    st.caption("Engine scanner terpisah · riset 2016–2025 · tidak mengirim order ke cBots.")
    try: result=load_result()
    except (OSError,ValueError):
        st.info("Riset 10 juta konfigurasi sedang disiapkan; probabilitas belum tersedia.")
        return
    selected=result.get("selected_by_side") or [result.get("selected")]
    try:
        snapshot=validate_snapshot(st.cache_data(ttl=60)(fetch_snapshot)())
    except Exception:
        snapshot=None
        st.warning("Zona harga live belum tersedia/fresh. Statistik historis tetap dapat dibaca; level harga lama tidak ditampilkan sebagai zona saat ini.")
    if snapshot:
        import pandas as pd
        stamp=pd.Timestamp(snapshot['last_m1_utc']).tz_convert('Asia/Jakarta')
        st.caption('Data XAU M1: '+stamp.strftime('%d/%m/%Y %H:%M WIB')+' · cTrader read-only')
        for zone in snapshot['zones']:
            with st.container(border=True):
                st.markdown('**'+zone['direction']+' · '+zone['state'].replace('_',' ')+'**')
                c1,c2=st.columns(2)
                c1.metric('Zona reversal',f"{zone['low']:,.2f}–{zone['high']:,.2f}")
                c2.metric('Batas invalidasi / SL riset',f"{zone['invalidation']:,.2f}")
                side=1 if zone['direction']=='BUY' else -1
                anchor=(zone['low']+zone['high'])/2
                target=anchor+side*zone['reaction_distance']
                stop_distance=abs(anchor-zone['invalidation'])
                c3,c4=st.columns(2)
                c3.metric('P reaksi OOS setelah konfirmasi',f"{100*zone['probability']:.1f}%" if zone.get('probability') is not None else 'Belum tervalidasi')
                c4.metric('Target reaksi / TP contoh',f"{target:,.2f}")
                st.caption(f"Contoh jika konfirmasi tepat di tengah zona {anchor:,.2f}: TP {zone['reaction_distance']:.2f} poin; SL {stop_distance:.2f} poin; reward/risk {zone['reaction_distance']/stop_distance:.2f}. Ini ilustrasi, bukan entry aktif.")
                tp_low=zone['low']+side*zone['reaction_distance'];tp_high=zone['high']+side*zone['reaction_distance']
                st.caption(f"Jika close konfirmasi berada di dalam zona: TP ilustratif {min(tp_low,tp_high):,.2f}–{max(tp_low,tp_high):,.2f}. TP aktual dihitung ulang dari close M5 yang memenuhi syarat; SL riset tetap di batas invalidasi snapshot.")
                st.caption('Jendela '+zone['session_wib']+' · '+('aktif' if zone['session_active'] else 'di luar jendela riset'))
                st.caption(f"Reaksi yang diuji: {zone['reaction_distance']:.2f} poin ({zone['reaction_atr']:g} ATR), dalam {zone['horizon_minutes']} menit setelah konfirmasi M5.")
        if not snapshot['zones']: st.info('Belum ada zona aktif yang sesuai konfigurasi riset.')
    st.markdown('**Bukti historis · probabilitas setelah konfirmasi M5**')
    rows=[]
    for winner in selected:
        if not winner: continue
        c=winner['config']; m=winner['holdout']; t=c['session_utc']
        row={'Arah':'BUY' if c['side']==1 else 'SELL','Jam WIB':f'{(t+7)%24:02d}:00–{(t+13)%24:02d}:00',
             'P reaksi OOS (%)':round(m['probability']*100,1),'N OOS':m['n'],
             'Target reaksi ATR':c['reaction_atr'],'Batas invalidasi ATR':c['invalidation_atr'],
             'Menit':c['horizon_minutes'],'Status':'Lolos kriteria riset' if winner['qualified'] else 'Riset saja'}
        rows.append(row)
        profile=winner.get('timing_profile',{})
        best=profile.get('best_hour_selected_before_holdout'); check=profile.get('best_hour_holdout')
        if best and check and check.get('probability') is not None:
            st.caption(f"{'BUY' if c['side']==1 else 'SELL'} · slot 1 jam dipilih dari validasi: {best['hour_wib']:02d}:00–{(best['hour_wib']+1)%24:02d}:00 WIB. Pengujian akhir: {100*check['probability']:.1f}% dari {check['n']} observasi; sampel lebih kecil.")
    st.dataframe(rows,hide_index=True,use_container_width=True)
    st.info('Probabilitas ini mengukur pantulan 0,5 ATR sebelum invalidasi 1 ATR dari anchor, maksimum 4 jam. Ini bukan win rate trading, bukan kepastian major reversal, dan bukan jam pasti harga berbalik.')
    if any(w and w.get('reaction_size_sensitivity') for w in selected):
        st.markdown('**Jika pantulan yang diminta lebih besar**')
        st.dataframe([{'Arah':'BUY' if w['config']['side']==1 else 'SELL',
                       'Reaksi ATR':m['reaction_atr'],'P reaksi OOS (%)':round(100*m['probability'],1),
                       'N':m['n']} for w in selected if w for m in w.get('reaction_size_sensitivity',[])],
                     hide_index=True,use_container_width=True)
    with st.expander('Metode, konfigurasi dan hasil per tahun'):
        st.caption('10.000.000 tuple parameter · pencarian 2016–2021 · seleksi 2022–2023 · pengujian akhir 2024–2025. Zona ekstrem H1 sudah terbentuk sebelum candle konfirmasi M5 dibuka.')
        for winner in selected:
            if winner:
                st.json({k:winner[k] for k in ['config','train','validation','holdout','qualified']})
                if winner.get('timing_profile'):
                    st.dataframe([{'Tahun':year,**metric} for year,metric in winner['timing_profile']['year_metrics'].items()],hide_index=True)
        st.caption('Interval Wilson dan bootstrap bulanan bersifat deskriptif; belum mengoreksi seluruh bias seleksi 10 juta konfigurasi. Forward validation tetap diperlukan.')
        st.download_button('Unduh hasil riset zona',json.dumps(result,indent=2),file_name='RIZAN_XAU_REVERSAL_10M.json',mime='application/json')


def render_reversal_dashboard():
    import streamlit as st
    # cache ttl alone does not refresh a browser that remains open. Revalidate
    # stale data every minute even when no widget interaction occurs.
    st.fragment(run_every='60s')(_render_reversal_dashboard)()
