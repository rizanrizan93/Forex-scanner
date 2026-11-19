"""R8-L provenance negative tests. Fixtures are synthetic, not market data."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from r8l_vendor_provenance_manifest import verify

class VendorManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "sample.bi5"
        self.raw.write_bytes(b"synthetic fixture - not Dukascopy data")
        self.manifest = self.root / "manifest.json"
        self.meta = {
            "vendor": "Dukascopy", "instrument": "dollaridxusd",
            "source_url": "https://example.invalid/sample.bi5",
            "retrieved_at_utc": "2026-11-19T00:00:00Z",
            "raw_sha256": hashlib.sha256(self.raw.read_bytes()).hexdigest(),
            "raw_size_bytes": self.raw.stat().st_size,
            "raw_file_name": self.raw.name,
            "transform_code_sha256": "a" * 64,
            "timezone_basis": "UTC", "bar_timestamp_semantics": "M1_OPEN"}
    def check(self, changes=None):
        m = dict(self.meta)
        m.update(changes or {})
        self.manifest.write_text(json.dumps(m), encoding="utf-8")
        return verify(self.manifest, self.raw)
    def test_matching_bytes_only_not_vendor_authentication(self):
        self.assertEqual(self.check()["status"], "RAW_BYTES_MATCH_MANIFEST_ONLY")
    def test_modified_raw_rejected(self):
        self.raw.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "RAW_BYTES_MISMATCH"):
            self.check()
    def test_wrong_timezone_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_TIME_SEMANTICS"):
            self.check({"timezone_basis": "Europe/London"})
    def test_missing_source_url_rejected(self):
        with self.assertRaisesRegex(ValueError, "MISSING_PROVENANCE_FIELDS"):
            self.check({"source_url": ""})
    def test_invalid_transform_hash_charset_must_be_rejected(self):
        with self.assertRaisesRegex(ValueError, "BAD_TRANSFORM_HASH"):
            self.check({"transform_code_sha256": "z" * 64})
    def test_future_retrieval_timestamp_must_be_rejected(self):
        with self.assertRaisesRegex(ValueError, "RETRIEVAL_TIME_IN_FUTURE"):
            self.check({"retrieved_at_utc": "2999-01-01T00:00:00Z"})
    def test_bad_raw_sha_rejected(self):
        with self.assertRaisesRegex(ValueError, "BAD_RAW_HASH"):
            self.check({"raw_sha256": "z" * 64})
    def test_boolean_raw_size_rejected(self):
        with self.assertRaisesRegex(ValueError, "BAD_RAW_SIZE"):
            self.check({"raw_size_bytes": True})
    def test_non_https_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "BAD_SOURCE_URL"):
            self.check({"source_url": "http://example.invalid/sample.bi5"})

if __name__ == "__main__":
    unittest.main()
