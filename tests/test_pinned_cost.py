"""A pinned mode is priced as that mode, on the response and in a budget; and what a backend offers a router."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import httpx
import pytest

from web_router import Budget, WebRouter, prices_modes
from web_router.modes import Content, Flag, ModeDeclarations, Tier
from web_router.providers._modes import offers
from web_router.routing.attempts import Attempt
from web_router.routing.pricing import attempt_cost
from web_router.types import SearchRequest

INSTANT = prices_modes.mode_price("exa", "search", "exa-instant")


def _mocked(router: WebRouter, provider: str) -> None:
    def answer(method: str, path: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json={"results": []}, request=httpx.Request(method, "https://api.exa.ai" + path))

    router.get_provider(provider)._client.request = answer  # type: ignore[attr-defined]


def test_the_mode_has_its_own_price_to_check_against() -> None:
    assert INSTANT is not None and prices_modes.mode_price("exa", "search", None) != INSTANT


def test_a_pinned_response_carries_the_modes_estimated_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "k")
    with WebRouter() as router:
        _mocked(router, "exa:exa-instant")
        response = router.search("q", provider="exa:exa-instant")
    assert (response.provider, response.cost_usd, response.cost_source) == ("exa", INSTANT, "estimated")


def test_a_budget_charges_the_pinned_modes_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "k")
    with WebRouter() as router:
        _mocked(router, "exa:exa-instant")
        with router.budget(Budget(max_cost_usd=1.0)) as shared:
            shared.search("q", provider="exa:exa-instant")
        assert shared.status().spent_usd == pytest.approx(INSTANT)


def test_a_chain_entry_that_pins_a_mode_is_priced_as_that_mode() -> None:
    entry = Attempt(tool="search", provider="exa:exa-instant", request=SearchRequest(query="q"))
    assert attempt_cost(entry) == INSTANT


class Acme(ModeDeclarations):
    name = "acme"
    supported_parameters: ClassVar[frozenset[str]] = frozenset({"search_depth"})
    depth_levels: ClassVar[frozenset[str]] = frozenset({"lite", "deep"})
    tiers: ClassVar[Mapping[str, Tier]] = {
        "acme-pro": Tier(wire={"tier": "pro"}),
        "acme-turbo": Tier(wire={"tier": "turbo"}),
    }
    contents: ClassVar[Mapping[str, Content]] = {"acme-snips": Content(as_depth="lite", wire={"body": "snips"})}
    flags: ClassVar[Mapping[str, Flag]] = {"acme-extra": Flag(wire={"extra": True})}


def test_offers_are_each_tier_at_the_default_depth_then_each_depth_and_content_then_each_flag() -> None:
    assert offers(Acme) == ("acme-pro", "acme-turbo", "lite", "deep", "acme-snips", "acme-extra")


def test_a_tier_that_is_the_default_is_not_offered_twice_and_a_class_may_set_its_own() -> None:
    assert "acme-pro" not in offers(type("Pro", (Acme,), {"default_tier": "acme-pro"}))
    assert offers(type("Own", (Acme,), {"offers": ("acme-turbo+deep",)})) == ("acme-turbo+deep",)
