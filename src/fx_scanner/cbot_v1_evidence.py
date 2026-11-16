"""Read-only broker evidence and necessary frozen V1 candle predicates.

Positive candle predicates never certify native warmup, guard readiness or a miss.
Rules pinned to 90172c2 / repairs/bootstrap125_v1_20261114/source.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


def stamp(value):
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def current(raw, contract, now, age=180):
    t = stamp(raw.get('observed_at')) if isinstance(raw, dict) else None
    return bool(t and -5 <= (now-t).total_seconds() <= age
                and raw.get('contract') == contract and raw.get('account_suffix') == '7903'
                and raw.get('read_only') is True and raw.get('execution_authority') is False)


def evidence(market, broker, symbol, phase, now):
    """Return measured predicates, with missing evidence distinct from failed rules."""
    rows = []
    def add(name, value, detail):
        rows.append((name, value, detail))
    market_ok = current(market, 'RIZAN_BOOTSTRAP125_MARKET_READONLY_V1', now)
    frames = market.get('bars', {}).get(symbol, {}) if market_ok else {}
    validated = {}
    for frame, minutes in (('M1', 1), ('M5', 5), ('H1', 60), ('H4', 240)):
        bars = frames.get(frame, [])
        times = [stamp(b.get('timestamp')) for b in bars if isinstance(b, dict)] if isinstance(bars, list) else []
        valid = bool(times) and len(times) == len(bars) and all(times)
        if valid:
            valid = all(isinstance(b.get(k), (float, int)) and not isinstance(b.get(k), bool)
                        and math.isfinite(b[k]) for b in bars for k in ('open', 'high', 'low', 'close', 'volume'))
        if valid:
            valid = all(b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high'] and b['volume'] >= 0 for b in bars)
            valid = valid and all(a < b for a,b in zip(times,times[1:]))
            # H4 broker session can be anchored at 22:00 UTC; do not force UTC midnight.
            valid = valid and all(t.second == 0 and t.microsecond == 0 and
                                 (t.minute % minutes == 0 if minutes <= 60 else t.minute == 0) for t in times)
            valid = valid and all(t + timedelta(minutes=minutes) <= stamp(market['observed_at']) for t in times)
        fresh_bars = valid and 0 <= (now-times[-1]-timedelta(minutes=minutes)).total_seconds() <= max(180, minutes*60)
        gaps = sum((b-a).total_seconds() != minutes*60 for a,b in zip(times,times[1:])) if valid else None
        if valid:
            validated[frame] = bars
        add('Candle broker ' + frame + ' tertutup dan baru', bool(fresh_bars) if market_ok and bars else None,
            (f"{len(bars)} bar; terakhir {times[-1].isoformat()}; interval tidak berurutan={gaps} (termasuk penutupan pasar)"
             if valid else 'Data candle tidak valid' if market_ok and bars else 'Sumber market belum tersedia/baru atau frame kosong'))
    m1 = validated.get('M1', [])
    add('History/warmup native V1 lengkap', None,
        f"Broker menyediakan {len(m1)} M1; belum membuktikan history, indikator dan state native terminal. "
        + ('BTC wajib seed BITSTAMP_BTCUSD_M1 7D; candle CFD broker tidak menggantikannya.' if symbol == 'BTCUSD' else
           'Volume broker adalah tick volume, bukan jumlah M1 penyusun H1/M5.'))
    if phase == 'GROWTH' and symbol == 'XAUUSD':
        h = validated.get('H1', [])
        if len(h) >= 11:
            b, prev = h[-1], h[-2]
            at = stamp(b['timestamp']) + timedelta(hours=1)
            allowed = at.weekday() < 5 and 5 <= at.hour < 17 and at.year >= 2019
            body = abs(b['close']-b['open'])
            minimum = 1.5*sum(abs(x['close']-x['open']) for x in h[-11:-1])/10
            buy = b['close'] > b['open'] and b['close'] > prev['high'] and b['high'] > b['low'] and (b['close']-b['low'])/(b['high']-b['low']) >= .55
            sell = b['close'] < b['open'] and b['close'] < prev['low'] and b['high'] > b['low'] and (b['high']-b['close'])/(b['high']-b['low']) >= .55
            add('Displacement: waktu close H1 diizinkan', allowed, at.isoformat() + '; evaluasi candle terakhir, bukan sinyal untuk candle berjalan')
            add('Displacement: body ≥ 1,5 × rerata 10 body', body >= minimum, f"Body {body:.5f}; batas {minimum:.5f}; close H1 {at.isoformat()}")
            add('Displacement: breakout dan posisi close BUY/SELL', buy or sell,
                f"BUY={buy}; SELL={sell}; close={b['close']}; high/low sebelumnya={prev['high']}/{prev['low']}")
            add('Displacement: ATR/RSI/EMA/efficiency dan kelengkapan native lolos', None,
                'Memerlukan indikator sesuai inisialisasi native serta 11 H1 berurutan, masing-masing 60 M1; belum dibuktikan endpoint ini.')
        allowed = now.weekday() < 5 and 12 <= now.hour < 17
        add('Compression: sesi entry terbuka', allowed, 'Hanya close M5 pukul 19:00–00:00 WIB pada hari kerja.')
        m = validated.get('M5', [])
        if allowed and len(m) >= 7:
            b, prior = m[-1], m[-7:-1]
            width = b['high']-b['low']
            body = (b['close']-b['open'])/width if width > 0 else 0
            hi, lo = max(x['high'] for x in prior), min(x['low'] for x in prior)
            buy, sell = width > 0 and b['close'] > hi and body > .5, width > 0 and b['close'] < lo and body <= -.7
            add('Compression: breakout 6 M5 dan body BUY/SELL', buy or sell,
                f"BUY={buy}; SELL={sell}; close={b['close']}; high/low 6 bar={hi}/{lo}; body={body:.3f}")
        add('Setup frozen compression/displacement terpenuhi', None,
            'Predikat candle diperiksa di atas; hasil positif belum mengesahkan setup penuh tanpa warmup, bias, ATR dan prioritas incumbent native.')
    elif symbol == 'EURUSD':
        if phase == 'GROWTH' and m1:
            groups = {}
            for bar in m1:
                at = stamp(bar['timestamp'])
                key = at.replace(minute=at.minute//15*15, second=0, microsecond=0)
                groups.setdefault(key, []).append(bar)
            m15 = []
            for at, group in sorted(groups.items()):
                if at + timedelta(minutes=15) <= stamp(market['observed_at']):
                    m15.append(dict(at=at, count=len(group), open=group[0]['open'], close=group[-1]['close'],
                                    high=max(b['high'] for b in group), low=min(b['low'] for b in group)))
            if len(m15) >= 9:
                b, prior = m15[-1], m15[-9:-1]
                at = b['at'] + timedelta(minutes=15)
                body = (b['close']-b['open'])/(b['high']-b['low']) if b['high'] > b['low'] else 0
                ph, pl = max(x['high'] for x in prior), min(x['low'] for x in prior)
                buy = b['low'] < pl and b['close'] > pl and body > .2
                sell = b['high'] > ph and b['close'] < ph and body < -.2
                add('EUR incumbent: waktu close M15 diizinkan',
                    7 <= at.hour < 12, at.isoformat() + '; incumbent 14:00–19:00 WIB; AsiaBuy memiliki syarat terpisah.')
                add('EUR incumbent: sweep/reclaim 8 M15 dan body', buy or sell,
                    f"BUY={buy}; SELL={sell}; body={body:.3f}; prior high/low={ph}/{pl}; close={b['close']}; M1 penyusun terakhir={b['count']}; belum memvalidasi bias/ATR.")
        add('Setup frozen EUR terpenuhi', None,
            'Memerlukan agregasi M15 native, bias H1, ATR dan Asia range; state virtual EUR tidak tersedia. ' +
            ('Pada GROWTH, incumbent mulai 14:00 WIB; AsiaBuy mulai 14:00 WIB.' if phase == 'GROWTH' else 'SEED: 512 M5/1.024 H4 saja belum membuktikan readiness native.'))
    else:
        add('Setup frozen original / Break40 terpenuhi', None, 'Feed Bitstamp native, seed tervalidasi dan acceptance terminal belum dipublikasikan; tidak dihitung memakai CFD broker.')
    broker_ok = current(broker, 'RIZAN_BOOTSTRAP125_BROKER_READONLY_V1', now) and broker.get('status') == 'OBSERVED'
    for field, label in (('orders_history_checked','Riwayat order broker berhasil diperiksa'), ('deals_history_checked','Riwayat deal broker berhasil diperiksa')):
        add(label, broker.get(field) if broker_ok and isinstance(broker.get(field), bool) else None,
            (f"Observasi {broker.get('observed_at')}; cakupan {broker.get('history_from')} — {broker.get('history_to')}" if broker_ok else 'Observasi broker belum tersedia/baru'))
    role = broker.get('roles', {}).get(symbol, {}) if broker_ok else {}
    add('Record V1 pada riwayat broker', None,
        (f"Order={role.get('orders')}; deal={role.get('deals')}; fill={role.get('entry_fills')}; reject={role.get('rejected_orders')}. "
         f"Deal seluruh akun belum terpetakan={broker.get('unmapped_deals')}; angka ini bukan bukti ada/tidaknya request sinyal tertentu."
         if broker_ok else 'Riwayat broker belum tersedia/baru'))
    foreign = broker.get('foreign_exposure_present') if broker_ok else None
    add('Akun bebas exposure di luar label V1 pada snapshot broker', not foreign if isinstance(foreign, bool) else None,
        ('foreign_exposure_present=' + str(foreign) + '; bukan bukti seluruh Guard47 lolos atau kondisi historis saat sinyal.' if broker_ok else 'Exposure broker belum tersedia/baru'))
    return rows
