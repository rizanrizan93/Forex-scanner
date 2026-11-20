import datetime as dt
import lzma
import struct
import pytest
from scripts.r8_vendor_m1 import decode_day

def test_utc_candle_decode():
    raw=b''.join(struct.pack('>IIIIIf',s,100,101,99,102,1.0) for s in (0,60,120))
    output=decode_day(lzma.compress(raw),dt.date(2019,1,2))
    assert len(output)==3
    assert output[0][0].isoformat()=='2019-01-02T00:00:00+00:00'
    assert output[2][4]==101

def test_invalid_record_duplicate():
    raw=struct.pack('>IIIIIf',0,100,101,99,102,1.0)*2
    with pytest.raises(ValueError,match='DUPLICATE'):decode_day(lzma.compress(raw),dt.date(2019,1,2))

def test_invalid_ohlc():
    raw=struct.pack('>IIIIIf',0,100,101,102,103,1.0)
    with pytest.raises(ValueError,match='OHLC'):decode_day(lzma.compress(raw),dt.date(2019,1,2))

def test_bad_day_offset():
    raw=struct.pack('>IIIIIf',86400,100,101,99,102,1.0)
    with pytest.raises(ValueError,match='OFFSET'):decode_day(lzma.compress(raw),dt.date(2019,1,2))

def test_bad_payload():
    with pytest.raises((ValueError,lzma.LZMAError)):decode_day(lzma.compress(b'123'),dt.date(2019,1,2))
