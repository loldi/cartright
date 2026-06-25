import pytest

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)


@pytest.fixture
def engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(),
    )


def test_recorded_preference_is_read_back_as_explicit(engine: ShoppingEngine) -> None:
    engine.recordPreference("paper-towels", {"brand": "Bounty"})

    pref = engine.getPreference("paper-towels")

    assert pref is not None
    assert pref.item_id == "paper-towels"
    assert pref.attributes == {"brand": "Bounty"}
    assert pref.source == "explicit"


def test_unknown_item_has_no_preference(engine: ShoppingEngine) -> None:
    assert engine.getPreference("never-recorded") is None


def test_latest_explicit_preference_wins(engine: ShoppingEngine) -> None:
    engine.recordPreference("paper-towels", {"brand": "Bounty"})
    engine.recordPreference("paper-towels", {"brand": "Store Brand"})

    pref = engine.getPreference("paper-towels")

    assert pref is not None
    assert pref.attributes == {"brand": "Store Brand"}


def test_explicit_overrides_existing_inferred(engine: ShoppingEngine) -> None:
    engine.recordPreference("paper-towels", {"brand": "Store Brand"}, source="inferred")
    engine.recordPreference("paper-towels", {"brand": "Bounty"}, source="explicit")

    pref = engine.getPreference("paper-towels")

    assert pref is not None
    assert pref.attributes == {"brand": "Bounty"}
    assert pref.source == "explicit"


def test_inferred_does_not_clobber_existing_explicit(engine: ShoppingEngine) -> None:
    engine.recordPreference("paper-towels", {"brand": "Bounty"}, source="explicit")
    engine.recordPreference("paper-towels", {"brand": "Store Brand"}, source="inferred")

    pref = engine.getPreference("paper-towels")

    assert pref is not None
    assert pref.attributes == {"brand": "Bounty"}
    assert pref.source == "explicit"
