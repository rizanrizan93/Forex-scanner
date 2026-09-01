from types import SimpleNamespace

import pytest

from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession


class FakeProtobuf:
    @staticmethod
    def extract(message):
        if getattr(message, "bad", False):
            raise ValueError("bad proto")
        return message.decoded


def session():
    value = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    value.Protobuf = FakeProtobuf
    return value


def test_decode_openapipy_container_extracts_business_response():
    s = session()
    business = SimpleNamespace(ctidTraderAccount=[SimpleNamespace(ctidTraderAccountId=123)])
    raw = SimpleNamespace(payload=b"wire", payloadType=2100, decoded=business)
    assert s._decode_response(raw) is business


def test_decode_already_decoded_response_is_unchanged():
    s = session()
    business = SimpleNamespace(accessToken="new-token")
    assert s._decode_response(business) is business


def test_decode_generic_api_error_fails_closed():
    s = session()
    error = type("ProtoOAErrorRes", (), {})()
    error.errorCode = "OA_AUTH_TOKEN_EXPIRED"
    error.description = "expired"
    raw = SimpleNamespace(payload=b"wire", payloadType=2142, decoded=error)
    with pytest.raises(CollectorUnavailable, match="OA_AUTH_TOKEN_EXPIRED"):
        s._decode_response(raw)


def test_decode_malformed_container_fails_closed():
    s = session()
    raw = SimpleNamespace(payload=b"bad", payloadType=2100, bad=True)
    with pytest.raises(CollectorUnavailable, match="protobuf decode failed"):
        s._decode_response(raw)
