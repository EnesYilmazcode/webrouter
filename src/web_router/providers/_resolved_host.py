"""Why a URL's host name resolves somewhere a backend fetching from this machine may not go.

:func:`~web_router.routing.url_policy.public_only` reads the host as written, so
a public-looking name that points at ``127.0.0.1`` passes it. A cloud backend
fetches from its own network and never reaches this machine's; LiteParse
fetches from here, so it looks the name up first.
"""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

from web_router._hosts import host_address, is_loopback, is_metadata, is_private
from web_router.constants_urls import MSG_URL_LOOPBACK, MSG_URL_METADATA, MSG_URL_PRIVATE


def resolved_refusal(url: str) -> str | None:
    """Why ``url``'s host resolves to an address that is not public, or ``None``.

    A literal address, or a name that does not resolve here, gives ``None``:
    the first was judged as written, and the second reaches nothing.
    """
    try:
        host = urlsplit(url).hostname
    except ValueError:
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
