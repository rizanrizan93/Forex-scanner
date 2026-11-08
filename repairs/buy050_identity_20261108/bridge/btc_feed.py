"""Pinned Bitstamp M1 seed plus verified contiguous completed-minute extension."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CONTRACT = "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND"
SEED_END = 1792108800
SEED_HASH = "e041102102e4ae2768e06f0261b4bfbfabc056ffa5decde21e161d8904179030"

def get_minutes(start, end):
    query = urlencode({"step": 60, "limit": 1000, "start": start, "end": end - 1, "exclude_current_candle": "true"})
    request = Request("https://www.bitstamp.net/api/v2/ohlc/btcusd/?" + query, headers={"User-Agent": "Rizan-R3-readonly-feed/3.0"})
    with urlopen(request, timeout=20) as response:
        data = response.read(2000001)
    if len(data) > 2000000:
        raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
    return json.loads(data)["data"]["ohlc"]

class BtcFeed:
    def __init__(self, seed_path, db_path, *, clock=time.time, fetch=get_minutes):
        self.seed = json.loads(Path(seed_path).read_text())
        if self.seed.get("contract") != CONTRACT or self.seed.get("source") != "BITSTAMP_BTCUSD_M1" or self.seed.get("through") != SEED_END:
            raise ValueError("SEED_CONTRACT")
        bars = self.seed["bars"]
        digest = hashlib.sha256()
        last = -1
        for row in bars:
            if len(row) != 6:
                raise ValueError("SEED_BAR")
            at, o, h, l, c, n = row
            if type(at) is not int or at % 3600 or at <= last or at + 3600 > SEED_END or type(n) is not int or not 1 <= n <= 60:
                raise ValueError("SEED_BAR")
            if any(not math.isfinite(x) or x <= 0 for x in (o, h, l, c)) or h < max(o, c) or l > min(o, c) or l > h:
                raise ValueError("SEED_BAR")
            digest.update(struct.pack("<qddddi", at, o, h, l, c, n))
            last = at
        if len(bars) != 68280 or bars[0][0] != 1546300800 or last + 3600 != SEED_END or digest.hexdigest() != SEED_HASH:
            raise ValueError("SEED_HASH_OR_COVERAGE")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.is_symlink():
            raise ValueError("DB_PATH")
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS minutes(at INTEGER PRIMARY KEY,o REAL NOT NULL,h REAL NOT NULL,l REAL NOT NULL,c REAL NOT NULL)")
        os.chmod(self.db_path, 0o600)
        self.clock, self.fetch = clock, fetch
        self.lock = threading.Lock()

    @staticmethod
    def minute(row):
        at = int(row["timestamp"])
        values = tuple(float(row[k]) for k in ("open", "high", "low", "close"))
        o, h, l, c = values
        if at % 60 or any(not math.isfinite(x) or x <= 0 for x in values) or h < max(o, c) or l > min(o, c) or l > h:
            raise ValueError("MINUTE_INVALID")
        return (at, *values)

    def packet(self):
        with self.lock:
            return self._packet()

    def _packet(self):
        through = int(self.clock()) // 3600 * 3600
        if through < SEED_END or through > SEED_END + 100000 * 3600:
            raise ValueError("CLOCK_OUTSIDE_SUPPORTED_COVERAGE")
        with sqlite3.connect(self.db_path, timeout=20) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            rows = db.execute("SELECT at,o,h,l,c FROM minutes WHERE at>=? AND at<? ORDER BY at", (SEED_END, through)).fetchall()
            expected = SEED_END
            for row in rows:
                if row[0] != expected:
                    break
                expected += 60
            requests = 0
            while expected < through:
                if requests >= 30:
                    raise ValueError("BACKFILL_CONTINUES_NEXT_POLL")
                end = min(through, expected + 1000 * 60)
                received = self.fetch(expected, end)
                candidate = {}
                for item in received:
                    row = self.minute(item)
                    if not expected <= row[0] < end:
                        continue
                    if row[0] in candidate and candidate[row[0]] != row:
                        raise ValueError("DUPLICATE_MINUTE_CONFLICT")
                    candidate[row[0]] = row
                # Never fill missing minutes or advance a watermark past a gap.
                for at in range(expected, end, 60):
                    if at not in candidate:
                        raise ValueError("SOURCE_MINUTE_GAP")
                    old = db.execute("SELECT at,o,h,l,c FROM minutes WHERE at=?", (at,)).fetchone()
                    if old is not None and old != candidate[at]:
                        raise ValueError("CACHED_MINUTE_CONFLICT")
                    db.execute("INSERT OR IGNORE INTO minutes VALUES(?,?,?,?,?)", candidate[at])
                db.commit()
                expected = end
                requests += 1
            rows = db.execute("SELECT at,o,h,l,c FROM minutes WHERE at>=? AND at<? ORDER BY at", (SEED_END, through)).fetchall()
        if len(rows) != (through - SEED_END) // 60:
            raise ValueError("CACHE_MINUTE_GAP")
        extension = []
        for index in range(0, len(rows), 60):
            hour = rows[index:index + 60]
            at = SEED_END + index * 60
            if len(hour) != 60 or any(row[0] != at + i * 60 for i, row in enumerate(hour)):
                raise ValueError("HOURLY_MINUTE_GAP")
            extension.append([at, hour[0][1], max(row[2] for row in hour), min(row[3] for row in hour), hour[-1][4], 60])
        # If the hour rolled during backfill, do not label an older packet fresh.
        if int(self.clock()) // 3600 * 3600 != through:
            raise ValueError("CLOCK_ROLLED_DURING_FETCH")
        return {"type": "feed", "contract": CONTRACT, "source": "BITSTAMP_BTCUSD_M1", "through": through, "bars": self.seed["bars"] + extension}
