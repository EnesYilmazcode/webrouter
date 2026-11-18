"""LiteParse provider: a document's text, parsed on this machine.

Downloads the file the URL points at and parses it in process with
`LiteParse <https://github.com/run-llama/liteparse>`_, so it needs no key and
sends the file nowhere. Install with the ``extract`` extra.

PDFs parse on their own. Word, PowerPoint and Excel files are converted with
LibreOffice first, and fail without it. A URL that serves a web page rather
than a file fails too: this reads documents, and extract ``auto`` sends it
only the URLs that name one (:mod:`web_router.providers._auto_documents`).
:meth:`parse_bytes` parses a file already in hand.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx
from liteparse import LiteParse, ParseResult

from web_router.constants import PROVIDER_LITEPARSE
from web_router.constants_liteparse import (
    LITEPARSE_ACCEPT,
    LITEPARSE_EXTRACT_DEFAULT_FORMAT,
    LITEPARSE_EXTRACT_FORMATS,
    LITEPARSE_GONE_STATUSES,
    MSG_LITEPARSE_FAILED,
)
from web_router.exceptions import ProviderError
from web_router.providers._http_base import _HttpProvider
from web_router.providers._utils import compact
from web_router.providers.base import ExtractProvider
from web_router.types import EXTRACT_FORMAT_ONLY, ExtractedDocument, ExtractFormat, ExtractRequest, ExtractResponse
from web_router.types_errors import ERROR_KIND_TARGET


class LiteParseExtractProvider(_HttpProvider, ExtractProvider):
    """Fetches a document and parses it locally with LiteParse."""

    name: ClassVar[str] = PROVIDER_LITEPARSE
    supported_parameters: ClassVar[frozenset[str]] = EXTRACT_FORMAT_ONLY
    supported_formats: ClassVar[frozenset[ExtractFormat]] = frozenset(LITEPARSE_EXTRACT_FORMATS)
    default_format: ClassVar[ExtractFormat] = LITEPARSE_EXTRACT_DEFAULT_FORMAT
    base_url: ClassVar[str] = ""

    def __init__(self, **kwargs: Any) -> None:
        """
        Args:
            **kwargs: As :class:`~web_router.providers.HttpExtractProvider`.
                Redirects are followed unless ``follow_redirects=False``: no
                credential is sent, and file links often redirect to storage.
        """
        headers = {"Accept": LITEPARSE_ACCEPT, **(kwargs.pop("headers", None) or {})}
        kwargs.setdefault("follow_redirects", True)
        super().__init__(headers=headers, **kwargs)

    def _extract(self, request: ExtractRequest, urls: list[str]) -> ExtractResponse:
        response = self._client.get(urls[0], **self._clamped())
        self._raise_for_status(response)
        return self._to_response(request, urls[0], self._parse(request, urls[0], response.content), response)

    async def _aextract(self, request: ExtractRequest, urls: list[str]) -> ExtractResponse:
        response = await self._async_client.get(urls[0], **self._clamped())
        self._raise_for_status(response)
        result = await asyncio.to_thread(self._parse, request, urls[0], response.content)
        return self._to_response(request, urls[0], result, response)

    def parse_bytes(self, data: bytes, *, url: str, format: ExtractFormat | None = None) -> ExtractResponse:
        """Parse a file already in hand, for one fetched some other way (a proxy, say); ``url`` labels the document."""
        request = ExtractRequest(urls=[url], format=format)
        self.validate(request)
        return self._to_response(request, url, self._parse(request, url, data))

    def _error_kind(self, exc: httpx.HTTPStatusError) -> str | None:
        """The URL fetched is the file itself, not an API, so a 404 is the target's and not worth another backend."""
        return ERROR_KIND_TARGET if exc.response.status_code in LITEPARSE_GONE_STATUSES else None

    def _parse(self, request: ExtractRequest, url: str, data: bytes) -> ParseResult:
        parser = LiteParse(output_format=LITEPARSE_EXTRACT_FORMATS[self.format_of(request)], quiet=True)
        try:
            return parser.parse(data)
        except Exception as exc:
            raise ProviderError(self.name, MSG_LITEPARSE_FAILED.format(url=url, error=exc), original=exc) from exc
        finally:
            parser.close()

    def _to_response(
        self, request: ExtractRequest, url: str, result: ParseResult, response: httpx.Response | None = None
    ) -> ExtractResponse:
        content_type = response.headers.get("content-type") if response is not None else None
        document = ExtractedDocument(
            url=url,
            content=result.text,
            format=self.format_of(request),
            status_code=response.status_code if response is not None else None,
            extra=compact({"total_pages": result.total_pages, "content_type": content_type}),
        )
        return ExtractResponse(provider=self.name, documents=[document])
