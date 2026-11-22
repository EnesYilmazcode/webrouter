"""The hops LiteParse's fetch may take, and the caller headers each one gets.

Kept apart from :mod:`web_router.providers.liteparse` so that file stays short.

:func:`~web_router.routing.url_policy.public_only` reads the host as written, so
a public-looking name that points at ``127.0.0.1`` passes it. A cloud backend
fetches from its own network and never reaches this machine's; LiteParse
fetches from here, so it looks each name up first.
"""

from __future__ import annotations

import socket

import httpx

from web_router._hosts import host_address, is_loopback, is_metadata, is_private
from web_router.constants import PROVIDER_LITEPARSE
from web_router.constants_liteparse import MSG_LITEPARSE_PRIVATE_HOP, MSG_LITEPARSE_PRIVATE_NAME
from web_router.constants_urls import MSG_URL_LOOPBACK, MSG_URL_METADATA, MSG_URL_PRIVATE
from web_router.exceptions import ProviderError
from web_router.routing.url_policy import any_web_url, public_only
from web_router.types_errors import ERROR_KIND_TARGET


def admit(url: str, hop: str) -> None:
    """Refuse ``hop`` when ``url`` looks public but ``hop``'s name resolves to a private address.

    Refusing ``url`` itself is no fault of the file's, so a chain may still try it; a redirect is the target's.
    """
    if public_only(url) is None and (why := resolved_refusal(hop)) is not None:
        if hop == url:
            raise ProviderError(PROVIDER_LITEPARSE, MSG_LITEPARSE_PRIVATE_NAME.format(url=url, why=why))
        raise _private_hop(url, why)


def next_hop(url: str, response: httpx.Response, *, follow: bool) -> str | None:
    """Where a redirect points, or ``None`` when ``response`` is the file; raises for a hop it may not take.

    A public URL may not redirect to a private host: a caller handing in a
    public link never meant this machine to fetch its own network.
    """
    if not (follow and response.is_redirect):
        return None
    target = str(response.url.join(response.headers["location"]))
    why = public_only(target) if public_only(url) is None else any_web_url(target)
    if why is not None:
        raise _private_hop(url, why)
    return target


def headers_for(headers: dict[str, str], url: str, hop: str) -> dict[str, str]:
    """``headers`` while the fetch keeps ``url``'s scheme and host; none once a redirect leaves either."""
    u, h = httpx.URL(url), httpx.URL(hop)
    return headers if (u.scheme, u.netloc) == (h.scheme, h.netloc) else {}


def resolved_refusal(url: str) -> str | None:
    """Why ``url``'s host resolves to an address that is not public, or ``None``.

    A literal address, or a name that does not resolve here, gives ``None``:
    the first was judged as written, and the second reaches nothing.
    """
    try:
        # The name httpx connects to: IDNA 2008, where getaddrinfo's own encoding of a unicode name is IDNA 2003.
        host = httpx.URL(url).raw_host.decode("ascii")
    except (httpx.InvalidURL, UnicodeError):
        return None
    if not host or host_address(host) is not None:
        return None
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return None
    for answer in answers:
        address = str(answer[4][0]).split("%", 1)[0].lower()
        if is_metadata(address):
            return MSG_URL_METADATA
        if is_loopback(address):
            return MSG_URL_LOOPBACK
        if is_private(address):
            return MSG_URL_PRIVATE
    return None


def _private_hop(url: str, why: str) -> ProviderError:
    return ProviderError(PROVIDER_LITEPARSE, MSG_LITEPARSE_PRIVATE_HOP.format(url=url, why=why), kind=ERROR_KIND_TARGET)
