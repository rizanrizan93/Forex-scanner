"""Independent causal SMC/ICT research checklist. Closed bars only; no orders."""
from datetime import UTC, datetime, timedelta
from .xau_decision_checklist_v1 import closed_bars, atr14, stamp

CONTRACT = 'RIZAN_XAU_TECHNICAL_V1_READONLY'
RULES = [
    ('h1', 'H1: struktur swing searah'),
    ('location', 'M15: discount BUY / premium SELL'),
    ('sweep', 'M5: sweep likuiditas lalu reclaim'),
    ('mss', 'M5: MSS + displacement setelah sweep'),
    ('fvg', 'M5: retest FVG yang masih valid'),
    ('rr', 'Target likuiditas memberi ruang minimal 2R'),
]


def pivots(bars):
    # Two right-hand closed bars confirm each pivot. No future/forming bar.
    highs, lows = [], []
    for i in range(2, len(bars)-2):
        window = bars[i-2:i] + bars[i+1:i+3]
        if all(bars[i]['h'] > b['h'] for b in window):
            highs.append(bars[i]['h'])
        if all(bars[i]['l'] < b['l'] for b in window):
            lows.append(bars[i]['l'])
    return highs, lows


def sequence(bars, side):
    """Latest valid chain within 45 minutes, chronological sweep/MSS/FVG/retest."""
    buy = side == 'BUY'
    out = {'sweep': False, 'mss': False, 'fvg': False}
    atr = atr14(bars)
    if atr is None:
        return out
    last = bars[-1]
    for s in range(len(bars)-3, max(12, len(bars)-10)-1, -1):
        b, prior = bars[s], bars[s-12:s]
        level = min(x['l'] for x in prior) if buy else max(x['h'] for x in prior)
        swept = b['l'] < level < b['c'] if buy else b['h'] > level > b['c']
        if not swept:
            continue
        out['sweep'] = True
        # Local structure at sweep time, not a swing detected with future data.
        trigger = max(x['h'] for x in bars[s-3:s]) if buy else min(x['l'] for x in bars[s-3:s])
        for m in range(s+1, len(bars)-1):
            c = bars[m]
            baseline = atr14(bars[:m])
            directional = c['c'] > max(trigger, c['o']) if buy else c['c'] < min(trigger, c['o'])
            if not directional or baseline is None or abs(c['c']-c['o']) < .8*baseline:
                continue
            out['mss'] = True
            for g in range(m+1, len(bars)-1):
                a, c = bars[g-2], bars[g]
                lo, hi = (a['h'], c['l']) if buy else (c['h'], a['l'])
                if hi <= lo or hi-lo < .1*baseline:
                    continue
                # No close through the distal edge after FVG creation.
                after = bars[g+1:]
                invalid = any(x['c'] < lo if buy else x['c'] > hi for x in after)
                retest = last['l'] <= hi and last['h'] >= lo
                confirm = last['c'] > (lo+hi)/2 and last['c'] > last['o'] if buy else last['c'] < (lo+hi)/2 and last['c'] < last['o']
                stop = min(x['l'] for x in bars[s:])-.1*atr if buy else max(x['h'] for x in bars[s:])+.1*atr
                # Structural sweep invalidation must not have traded through.
                broken = any(x['l'] < b['l'] if buy else x['h'] > b['h'] for x in bars[s+1:])
                if not invalid and not broken and retest and confirm:
                    return {**out, 'fvg': True, 'zone_low': lo, 'zone_high': hi,
                            'stop': stop, 'sweep_at': b['at'].isoformat(),
                            'mss_at': bars[m]['at'].isoformat(), 'fvg_at': c['at'].isoformat()}
    return out


def evaluate_technical(feed, *, now):
    if now.tzinfo is None:
        raise ValueError('NOW_MUST_BE_TIMEZONE_AWARE')
    now = now.astimezone(UTC)
    bars, errors = {}, []
    waiting_m5 = False
    at = stamp((feed or {}).get('as_of'))
    if at is None or not 0 <= (now-at).total_seconds() <= 600:
        errors.append('Snapshot candle kedaluwarsa/timestamp belum valid')
    for tf in ('H1', 'M15', 'M5'):
        series, error = closed_bars(feed, tf, now)
        # The M5 entry sequence must be contiguous. H1/M15 use actual observed
        # bars across sessions; never fill a market closure with synthetic candles.
        span = {'H1': 3600, 'M15': 900, 'M5': 300}[tf]
        tail = series[-24:] if tf != 'M5' else series[-30:]
        if tf == 'M5' and any((b['at']-a['at']).total_seconds() != span for a,b in zip(tail, tail[1:])):
            error = 'Candle '+tf+' terbaru memiliki gap; tunggu rangkaian lengkap'
        if tf == 'M5' and series and (now-series[-1]['at']).total_seconds() >= 300:
            error = 'Candle M5 melewati batas setup; tunggu candle terbaru'
            waiting_m5 = (300 <= (now-series[-1]['at']).total_seconds() <= 390
                          and at is not None and 0 <= (now-at).total_seconds() <= 90)
        if error:
            errors.append(tf+': '+error)
        bars[tf] = series
    result = {'contract': CONTRACT, 'as_of_utc': now.isoformat(),
              'execution_authority': False, 'execution_influence': False,
              'out_of_sample_validated': False, 'errors': errors, 'direction': 'WAIT'}
    for side in ('BUY', 'SELL'):
        if errors:
            rows = [{'key':k,'name':n,'state':'UNKNOWN','why':'; '.join(errors)} for k,n in RULES]
            waiting = waiting_m5 and len(errors) == 1 and bool(bars['H1']) and bool(bars['M15'])
            if waiting:
                highs, lows = pivots(bars['H1'][-72:])
                buy = side == 'BUY'
                trend = (len(highs)>=2 and len(lows)>=2 and
                         (highs[-1]>highs[-2] and lows[-1]>lows[-2] if buy else highs[-1]<highs[-2] and lows[-1]<lows[-2]))
                rows[0].update(state='PASS' if trend else 'FAIL',
                               why='Swing H1 tervalidasi; menunggu publikasi candle M5 yang baru tertutup')
            result[side] = {'items':rows,'state':'WAIT_CANDLE' if waiting else 'WAIT_DATA',
                            'passed':sum(x['state']=='PASS' for x in rows),'plan':None}
            continue
        buy = side == 'BUY'
        h1, m15, m5 = bars['H1'], bars['M15'], bars['M5']
        highs, lows = pivots(h1[-72:])
        trend = (len(highs)>=2 and len(lows)>=2 and
                 (highs[-1]>highs[-2] and lows[-1]>lows[-2] if buy else highs[-1]<highs[-2] and lows[-1]<lows[-2]))
        high, low = max(x['h'] for x in m15[-32:-1]), min(x['l'] for x in m15[-32:-1])
        mid, entry = (high+low)/2, m5[-1]['c']
        location = low <= entry <= mid if buy else mid <= entry <= high
        seq = sequence(m5, side)
        target_levels = [x['h'] if buy else x['l'] for x in m15[-32:-1]]
        opposing = [v for v in target_levels if v > entry] if buy else [v for v in target_levels if v < entry]
        target = (min(opposing) if buy else max(opposing)) if opposing else None
        stop = seq.get('stop')
        risk = abs(entry-stop) if stop is not None else 0
        rr = abs(target-entry)/risk if target is not None and risk>0 else None
        passed = [trend, location, seq['sweep'], seq['mss'], seq['fvg'], rr is not None and rr>=2]
        details = [
            'Swing H1 terkonfirmasi 2 candle kanan: HH+HL BUY / LH+LL SELL',
            'Range M15 31 candle observasi (lintas sesi): %.2f–%.2f; equilibrium %.2f; close M5 %.2f' % (low,high,mid,entry),
            'Wick menembus ekstrem 12 candle sebelumnya lalu close kembali di dalam range',
            'Close melewati ekstrem 3 candle sebelum sweep; body ≥0.8 ATR14 sebelum displacement',
            'FVG ≥0.1 ATR; terbentuk setelah MSS; candle terakhir retest + close melewati midpoint; belum invalid',
            'R/R ke likuiditas M15 terdekat: '+('%.2fR' % rr if rr is not None else 'belum ada setup lengkap'),
        ]
        rows = [{'key':k,'name':n,'state':'PASS' if ok else 'FAIL','why':why}
                for (k,n),ok,why in zip(RULES,passed,details)]
        ready = all(passed)
        result[side] = {'items':rows,'passed':sum(passed), 'state':'SETUP_CONFIRMED' if ready else 'WAIT_SETUP',
                        'plan':{'reference_close':entry,'invalidation':stop,'target_liquidity':target,
                                'rr_before_costs':rr,'fvg':[seq['zone_low'],seq['zone_high']],
                                'valid_until':(m5[-1]['at']+timedelta(minutes=5)).isoformat(),
                                'basis':'Closed M5 reference, not executable bid/ask'} if ready else None}
        if ready:
            result['direction'] = side
    return result


def compare_macro(report, usd, yields):
    technical = report['direction']
    u, y = usd.get('usd_direction'), yields.get('yield_direction')
    if technical == 'WAIT' or u not in ('UP_WATCH','DOWN_WATCH') or yields.get('state') != 'CONCORDANT_PROXY':
        return 'WAIT — teknikal atau makro/yield belum lengkap'
    aligned = (technical=='BUY' and u=='DOWN_WATCH' and y=='DOWN') or (technical=='SELL' and u=='UP_WATCH' and y=='UP')
    return 'SELARAS — '+technical+' (riset, bukan izin order)' if aligned else 'KONFLIK — makro dan teknikal berbeda; tunggu'
