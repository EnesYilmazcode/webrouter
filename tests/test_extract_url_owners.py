"""Which requested URL a page or failure answers, in a batch and on ``auto``'s retry, and what a retry costs."""

from __future__ import annotations

from web_router.providers._auto_extract_chain import _merged
from web_router.providers._error_pages import split_error_pages
from web_router.providers._url_match import owners
from web_router.routing.metered import combined_cost
from web_router.types import ExtractedDocument, ExtractFailure, ExtractRequest, ExtractResponse

A, B, C = "https://a.test/p", "https://b.test/q", "https://c.test/r"
LOGIN = "https://www.linkedin.com/authwall?trk=redirect"
TEXT = "A page with enough text in it to count as the page that was asked for, not a shell."


def test_a_batch_names_a_redirected_login_wall_by_the_one_url_left_unanswered() -> None:
    pages = [ExtractedDocument(url=A, content=TEXT), ExtractedDocument(url=LOGIN, content="Sign in")]

    kept, failures = split_error_pages(pages, [A, B])

    assert [page.url for page in kept] == [A]
    assert [failure.url for failure in failures] == [B]


def test_a_batch_cannot_name_a_redirect_two_urls_could_have_made() -> None:
    assert owners([LOGIN], [A, B]) == [None]
    assert owners([LOGIN], [A, B], also_claimed=[A]) == [B]  # the backend reported A failed itself
    assert owners([LOGIN, "https://elsewhere.test/"], [A, B, C], also_claimed=[A]) == [None, None]


def test_a_retry_leaves_out_a_page_no_url_it_was_sent_for_can_be_told() -> None:
    first = ExtractResponse(
        provider="one", failures=[ExtractFailure(url=A, error="down"), ExtractFailure(url=B, error="down")]
    )
    # Two URLs went out and one page came back under a third address: it could be either one's.
    second = ExtractResponse(provider="two", documents=[ExtractedDocument(url="https://x.test/", content=TEXT)])

    merged = _merged(first, second, [A, B], ExtractRequest(urls=[A, B]))

    assert merged.documents == []
    assert [failure.url for failure in merged.failures] == [A, B]


def test_a_single_url_retry_counts_a_redirected_page_as_read() -> None:
    first = ExtractResponse(provider="one", failures=[ExtractFailure(url=A, error="down")])
    second = ExtractResponse(provider="two", documents=[ExtractedDocument(url=A + "/landed", content=TEXT)])

    merged = _merged(first, second, [A], ExtractRequest(urls=[A]))

    assert merged.failures == []
    assert len(merged.documents) == 1


def test_a_retry_adds_the_second_backends_cost() -> None:
    first = ExtractResponse(
        provider="one",
        documents=[ExtractedDocument(url=A, content=TEXT)],
        failures=[ExtractFailure(url=B, error="down")],
        cost_usd=0.002,
        cost_source="reported",
    )
    second = ExtractResponse(
        provider="two", documents=[ExtractedDocument(url=B, content=TEXT)], cost_usd=0.001, cost_source="reported"
    )

    merged = _merged(first, second, [A, B], ExtractRequest(urls=[A, B]))

    assert merged.cost_usd == 0.003
    assert merged.cost_source == "reported"


def test_a_combined_cost_is_estimated_unless_every_part_reported_and_unknown_if_any_part_is() -> None:
    request = ExtractRequest(urls=[A])
    reported = ExtractResponse(provider="one", cost_usd=0.002, cost_source="reported")
    estimated = ExtractResponse(provider="two", cost_usd=0.001, cost_source="estimated")

    assert combined_cost("extract", [(reported, request), (estimated, request)])["cost_source"] == "estimated"
    assert combined_cost("extract", [(reported, request), (ExtractResponse(provider="unpriced"), request)]) == {}
