"""Candidates per vendor mode: shown to a router that opts in with ``route_modes``, each priced on its own request.

Offline: the members are read from their classes and the shipped price list; nothing is sent.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.candidates_helpers import Shown, clear_keys, ids, set_keys
from web_router import Budget, Candidate, RouteDecision, RouteRequest, WebRouter
from web_router.exceptions import ConfigurationError
from web_router.providers._modes import offers
from web_router.providers._pinning import pinned_request
from web_router.registry import get_provider_class
from web_router.routing.attempts import Attempt
from web_router.routing.candidates import build_candidates
from web_router.routing.cheapest import cheapest_first
from web_router.routing.decider_llm import LLMDecider
from web_router.routing.decider_router import DeciderRouter
from web_router.routing.decider_systemone import SystemOneDecider
from web_router.routing.params import map_effort
from web_router.routing.pricing import attempt_cost, attempt_p90
from web_router.types import SearchRequest

CHAIN = {"auto": {"chain": {"search": ["exa", "tavily"]}}}
SEARCH = {"search": SearchRequest(query="q")}


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Exa and Tavily keyed, nothing else."""
    set_keys(clear_keys(monkeypatch), "exa", "tavily")
    return monkeypatch


def shown(router: Shown, **kwargs: Any) -> list[str]:
    """The candidate ids ``router`` is shown for a search plan, attached with ``kwargs``."""
    with WebRouter(provider_config=CHAIN, router=router, **kwargs) as wr:
        wr.plan("q", tool="search")
    return router.ids


def test_route_modes_shows_one_candidate_per_offered_mode_each_priced_on_its_own_request(keys: Any) -> None:
    router = Shown()
    assert shown(router) == ["search:exa", "search:tavily"], "off by default: backends only"
    shown(router, route_modes=True)
    candidates = {c.id: c for c in router.reqs[-1].candidates}
    exa = get_provider_class("exa")()
    moded_by_id = {f"search:exa:{m.mode}": m for m in (pinned_request(exa, SEARCH["search"], o) for o in offers(exa))}
    modes = [cid for cid in candidates if cid.startswith("search:exa:")]
    # Every one offered, but a depth that sends what the default sends: that one is the backend's own candidate.
    assert set(modes) == set(moded_by_id) - {"search:exa:deep"}
    for cid in modes:
        candidate, moded = candidates[cid], moded_by_id[cid]
        attempt = Attempt(tool="search", provider="exa", request=moded)
        assert (candidate.mode, candidate.est_cost_usd) == (moded.mode, attempt_cost(attempt))
        assert candidate.est_latency_s == attempt_p90(attempt)
    assert candidates["search:exa:exa-instant"].est_cost_usd != candidates["search:exa"].est_cost_usd
    ordered = list(candidates)
    assert ordered.index("search:tavily") > max(i for i, cid in enumerate(ordered) if cid.startswith("search:exa:"))


def test_the_caller_wins_over_the_router_and_a_router_may_opt_in_itself(keys: Any) -> None:
    assert any(cid.count(":") == 2 for cid in shown(Shown(route_modes=True)))
    assert shown(Shown(route_modes=True), route_modes=False) == ["search:exa", "search:tavily"]


@pytest.mark.parametrize("router", ["rules", "cheapest_first"])
def test_a_built_in_router_is_shown_backends_only_unless_the_caller_asks(keys: Any, router: str) -> None:
    assert WebRouter(router=router)._route_modes is False
    assert WebRouter(router=router, route_modes=True)._route_modes is True


@pytest.mark.parametrize("decider", [LLMDecider, SystemOneDecider])
def test_a_built_in_decider_attached_is_shown_backends_only(keys: Any, decider: type) -> None:
    fake = type("Fake", (), {"route_modes": decider.route_modes, "decide": lambda self, question: None})()
    assert WebRouter(router=DeciderRouter(fake))._route_modes is False


def test_cheapest_first_ranks_backends_at_their_default_price_whatever_their_modes_cost(keys: Any) -> None:
    cheap = Candidate(tool="search", provider="exa", mode="exa-instant", est_cost_usd=0.001)
    backends = (Candidate(tool="search", provider="exa", est_cost_usd=0.02), cheap)
    req = RouteRequest(
        prompt="q",
        candidates=(*backends, Candidate(tool="search", provider="tavily", est_cost_usd=0.01)),
        deadline_s=1.0,
    )
    assert cheapest_first(req).providers == {"search": ["tavily", "exa"]}


def test_a_router_shown_only_modes_is_not_asked(keys: Any) -> None:
    router, cap = Shown(), Budget(max_cost_usd=0.015)  # Exa's default is over it, its instant mode is not
    with WebRouter(provider_config={"auto": {"chain": {"search": ["exa"]}}}, router=router, route_modes=True) as wr:
        found = build_candidates(wr, SEARCH, budget=cap, modes=True)
        wr.plan("q", tool="search", budget=cap)
    assert ids(found) == ["search:exa:exa-instant"] and router.reqs == []


@pytest.mark.parametrize("value", ["yes", 1, [True]])
def test_a_route_modes_that_is_not_a_bool_is_refused(keys: Any, value: Any) -> None:
    with pytest.raises(ConfigurationError, match="route_modes"):
        WebRouter(router=Shown(), route_modes=value)
    with pytest.raises(ConfigurationError, match="route_modes attribute"):
        WebRouter(router=Shown(route_modes=value))


def test_a_mode_the_member_refuses_is_dropped_with_why_and_nothing_raises(keys: Any) -> None:
    deep = {"search": SearchRequest(query="q", search_depth="deep")}
    found = build_candidates(WebRouter(provider_config=CHAIN), deep, modes=True)
    assert "search:exa:lite" not in ids(found) and "refuses this mode" in found.dropped["search:exa:lite"]
    assert "search:exa:exa-instant+deep" in ids(found), "a tier composes with the depth asked"
    assert not any(cid.startswith("search:tavily:tavily-fast") for cid in ids(found)), "it writes search_depth"


def test_modes_are_unmeasured_and_never_run_by_name(keys: Any) -> None:
    router = WebRouter(provider_config=CHAIN, router=Shown(), route_modes=True)
    with router:
        plan = router.plan("q", tool="search")
    found = build_candidates(router, SEARCH, modes=True)
    assert all(cid in found.unmeasured for cid in ids(found) if cid.count(":") == 2)
    assert plan.providers == {"search": ("exa", "tavily")}, "the order to run is the backends'"


def test_under_a_cost_cap_modes_keep_their_backends_place_in_the_cost_order(keys: Any) -> None:
    cap, router = Budget(max_cost_usd=0.05), WebRouter(provider_config=CHAIN)
    off = build_candidates(router, SEARCH, budget=cap)
    assert build_candidates(router, SEARCH, budget=cap, modes=False) == off, "off is the order without modes"
    on = build_candidates(router, SEARCH, budget=cap, modes=True)
    assert on.cost_order == off.cost_order
    assert [c.id for c in on.candidates if c.mode is None] == ids(off)
    backends = [c.provider for c in on.candidates]
    assert backends == sorted(backends, key=[c.provider for c in off.candidates].index), "each mode after its own"


def test_research_under_a_budget_with_a_router_that_times_out_runs_the_shared_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_keys(clear_keys(monkeypatch), "parallel")
    cap = Budget(max_cost_usd=0.01)

    def late(req: RouteRequest) -> RouteDecision:
        time.sleep(0.2)
        return RouteDecision(params={"research": {"effort": "high"}})

    late.timeout_s = 0.01  # type: ignore[attr-defined]
    with WebRouter(router=late, route_modes=True) as wr:
        plan = wr.plan("q", tool="research", budget=cap)
    assert plan.decision.router_timeout is True
    assert plan.params["effort"] == map_effort("parallel", cap).effort == "low", "today's shared_effort pick"
