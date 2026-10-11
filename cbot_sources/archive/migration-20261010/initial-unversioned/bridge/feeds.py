"""Read-only macro/news adapter. No trading credentials or execution functions."""
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import re
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from icalendar import Calendar

UTC = timezone.utc
_CACHE = {}
FF = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
BLS = 'https://www.bls.gov/schedule/news_release/bls.ics'

def fetch(url, now, ttl):
    cached = _CACHE.get(url)
    if cached and timedelta(0) <= now - cached[0] < ttl:
        return cached[1]
    request = Request(url, headers={'User-Agent': 'Rizan-cBot-data-bridge/1.0', 'Accept': '*/*'})
    with urlopen(request, timeout=15) as response:
        body = response.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError('SOURCE_TOO_LARGE')
    _CACHE[url] = (now, body)
    return body

def category(title):
    text = re.sub(r'\s+', ' ', str(title)).upper()
    for name, pattern in (
        ('PPI', r'PRODUCER PRICE INDEX|\bPPI\b'),
        ('JOLTS', r'JOB OPENINGS|JOLTS'),
        ('ECI', r'EMPLOYMENT COST INDEX|\bECI\b'),
        ('CPI', r'CONSUMER PRICE INDEX|\bCPI\b'),
        ('NFP', r'EMPLOYMENT SITUATION|NON-FARM|NONFARM|PAYROLL|AVERAGE HOURLY EARNINGS|UNEMPLOYMENT RATE'),
        ('FOMC', r'FOMC|FEDERAL FUNDS RATE|FED FUNDS RATE'),
    ):
        if re.search(pattern, text):
            return name
    return None

def macro_point(body, series, now):
    frame = pd.read_csv(StringIO(body.decode())).rename(columns={'observation_date': 'DATE'})
    values = pd.to_numeric(frame[series], errors='coerce').dropna().tail(90)
    dates = pd.to_datetime(frame.loc[values.index, 'DATE']).dt.normalize()
    days = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    available = pd.DatetimeIndex([d + 2 * days for d in dates]).tz_localize('America/New_York').tz_convert('UTC')
    rows = pd.DataFrame({'delta': values.diff().to_numpy(), 'available': available})
    known = rows[rows.available <= pd.Timestamp(now)]
    if known.empty:
        raise ValueError('MACRO_NOT_AVAILABLE')
    last = known.iloc[-1]
    if pd.isna(last.delta) or now - last.available > timedelta(days=7):
        raise ValueError('MACRO_STALE')
    return {'Delta': float(last.delta), 'AvailableUtc': last.available.isoformat()}

def ff_events(body, now):
    rows = json.loads(body)
    if not isinstance(rows, list) or not rows:
        raise ValueError('FF_EMPTY_OR_INVALID_CALENDAR')
    # Provider endpoint explicitly denotes this week; verify its dates rather
    # than treating an old cached weekly calendar as current coverage.
    local = now.astimezone(ZoneInfo('America/New_York'))
    sunday = (local - timedelta(days=(local.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = sunday.astimezone(UTC), (sunday + timedelta(days=7)).astimezone(UTC)
    parsed = []
    for row in rows:
        raw = row.get('date')
        if not raw:
            raise ValueError('FF_UNTIMED_EVENT')
        at = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if at.tzinfo is None:
            raise ValueError('FF_TIMEZONE_REQUIRED')
        parsed.append((row, at.astimezone(UTC)))
    if not any(start <= at < end for _, at in parsed) or any(not start <= at < end for _, at in parsed):
        raise ValueError('FF_WEEK_MISMATCH')
    events = [{'AtUtc': at.isoformat(), 'Category': cat} for row, at in parsed
              if row.get('country') == 'USD' and (cat := category(row.get('title', '')))]
    return events, start, end

def bls_events(body, start, end):
    calendar = Calendar.from_ical(body)
    events, dates = [], []
    for component in calendar.walk('VEVENT'):
        at = component.decoded('DTSTART', None)
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError('BLS_UNTIMED_EVENT')
        at = at.astimezone(UTC)
        dates.append(at)
        cat = category(str(component.get('SUMMARY', '')))
        if cat:
            events.append({'AtUtc': at.isoformat(), 'Category': cat})
    # Weekly FF coverage is accepted only inside the official calendar's span.
    if not dates or min(dates) > start or max(dates) < end:
        raise ValueError('BLS_CALENDAR_COVERAGE_INCOMPLETE')
    return events

def snapshot(now=None):
    now = now or datetime.now(UTC)
    errors = []
    result = {'ProducedUtc': now.isoformat(), 'CoverageFromUtc': now.isoformat(),
              'CoverageToUtc': now.isoformat(), 'ForexFactoryOk': False, 'BlsOk': False,
              'Dgs10': None, 'Dfii10': None, 'Events': [], 'Errors': errors}
    for series, key in [('DGS10', 'Dgs10'), ('DFII10', 'Dfii10')]:
        try:
            # Fixed date-free URL keeps the cache key stable across midnight.
            url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=' + series
            result[key] = macro_point(fetch(url, now, timedelta(hours=1)), series, now)
        except Exception as exc:
            errors.append(series + ':' + type(exc).__name__)
    try:
        events, start, end = ff_events(fetch(FF, now, timedelta(minutes=15)), now)
        result.update(ForexFactoryOk=True, CoverageFromUtc=start.isoformat(), CoverageToUtc=end.isoformat(), Events=events)
    except Exception as exc:
        errors.append('FF:' + type(exc).__name__)
        return result
    try:
        result['Events'] += bls_events(fetch(BLS, now, timedelta(minutes=15)), start, end)
        result['BlsOk'] = True
    except Exception as exc:
        errors.append('BLS:' + type(exc).__name__)
    return result

if __name__ == '__main__':
    print(json.dumps(snapshot(), indent=2, allow_nan=False))
