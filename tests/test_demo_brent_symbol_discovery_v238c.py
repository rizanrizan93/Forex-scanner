from pathlib import Path

from fx_scanner.demo_brent_symbol_discovery_v238c import (
    rank_brent_candidates,
    resolve_unique_brent_candidate,
)
from fx_scanner.execution.ctrader_research import CTraderResearchFeed

ROOT = Path(__file__).resolve().parents[1]


class FakeCatalogueSession:
    def health(self):
        return True

    def ensure_connected(self):
        return None

    def symbol_catalogue(self):
        return (
            (1, "XAU/USD"),
            (2, "USOIL"),
            (3, "UKOIL"),
        )

    def load_symbols(self, symbols):
        self.loaded = tuple(symbols)

    def close(self):
        return None


def test_v238c_research_feed_exposes_catalogue_read_only() -> None:
    feed = CTraderResearchFeed(FakeCatalogueSession(), ("XAUUSD",))
    assert feed.symbol_catalogue() == (
        (1, "XAU/USD"),
        (2, "USOIL"),
        (3, "UKOIL"),
    )


def test_v238c_ranks_uk_oil_above_generic_oil() -> None:
    rows = rank_brent_candidates(
        (
            (10, "USOIL"),
            (11, "UKOIL"),
            (12, "XAUUSD"),
        )
    )
    assert [row["symbol_name"] for row in rows] == ["UKOIL", "USOIL"]
    resolved = resolve_unique_brent_candidate(rows)
    assert resolved is not None
    assert resolved["symbol_name"] == "UKOIL"


def test_v238c_multiple_strong_brent_aliases_remain_unresolved() -> None:
    rows = rank_brent_candidates(
        (
            (20, "UKOIL"),
            (21, "Brent.cash"),
            (22, "BCO/USD"),
        )
    )
    assert rows[0]["symbol_name"] == "Brent.cash"
    assert resolve_unique_brent_candidate(rows) is None


def test_v238c_single_strong_candidate_can_resolve() -> None:
    rows = rank_brent_candidates(
        (
            (20, "USOIL"),
            (21, "UKOIL"),
        )
    )
    resolved = resolve_unique_brent_candidate(rows)
    assert resolved is not None
    assert resolved["symbol_name"] == "UKOIL"


def test_v238c_tied_top_candidates_fail_closed() -> None:
    rows = rank_brent_candidates(
        (
            (30, "BRENT"),
            (31, "BRENT.cash"),
            (32, "UKOIL"),
        )
    )
    assert rows[0]["score"] == rows[1]["score"] == 100
    assert resolve_unique_brent_candidate(rows) is None


def test_v238c_research_feed_can_load_metadata_without_subscription() -> None:
    session = FakeCatalogueSession()
    feed = CTraderResearchFeed(session, ("XAUUSD",))
    feed.load_symbol_metadata(("BRENT", "XBRUSD"))
    assert session.loaded == ("BRENT", "XBRUSD")


def test_v238c_discovery_module_has_no_execution_authority() -> None:
    source = (
        ROOT / "src/fx_scanner/demo_brent_symbol_discovery_v238c.py"
    ).read_text(encoding="utf-8")
    assert '"execution_authority": False' in source
    assert '"live_execution_enabled": False' in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert "build_broker_gateway" not in source
