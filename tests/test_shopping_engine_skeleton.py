import pytest

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)


@pytest.fixture
def engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(),
    )


def test_schema_is_initialized_on_construction(engine: ShoppingEngine) -> None:
    tables = engine._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()

    assert any(row["name"] == "preferences" for row in tables)


def test_fixture_messenger_records_sent_messages() -> None:
    messenger = FixtureMessenger()

    messenger.send_message(to="987654321", body="Bounty is on sale, want it?")

    assert [{"to": s["to"], "body": s["body"]} for s in messenger.sent] == [
        {"to": "987654321", "body": "Bounty is on sale, want it?"}
    ]
