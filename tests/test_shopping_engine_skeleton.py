from collections.abc import Callable

import pytest

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
    FixtureTwilioAdapter,
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


@pytest.mark.parametrize(
    "call",
    [
        lambda engine: engine.getReorderCandidates(),
        lambda engine: engine.evaluateDeal("paper-towels"),
        lambda engine: engine.buildCart(["paper-towels"]),
        lambda engine: engine.recordPreference("paper-towels", {"brand": "Bounty"}),
        lambda engine: engine.getPreference("paper-towels"),
    ],
)
def test_public_methods_are_stubbed(
    engine: ShoppingEngine, call: Callable[[ShoppingEngine], object]
) -> None:
    with pytest.raises(NotImplementedError):
        call(engine)


def test_fixture_twilio_adapter_records_sent_sms() -> None:
    twilio = FixtureTwilioAdapter()

    twilio.send_sms(to="+15555550123", body="Bounty is on sale, want it?")

    assert twilio.sent == [{"to": "+15555550123", "body": "Bounty is on sale, want it?"}]


def test_fixture_twilio_adapter_queues_and_drains_inbound_sms() -> None:
    twilio = FixtureTwilioAdapter()
    twilio.queue_inbound(frm="+15555550123", body="always get Bounty")

    received = twilio.receive_sms()

    assert received == [{"from": "+15555550123", "body": "always get Bounty"}]
    assert twilio.receive_sms() == []
