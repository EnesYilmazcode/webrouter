"""LiteParse: the formats it returns and the URLs extract ``auto`` sends it.

Kept apart from :mod:`web_router.constants`, as the other newer backends' are,
so that file stops growing. The provider name stays there, beside every other
backend's.
"""

from __future__ import annotations

from web_router.types import ExtractFormat

LITEPARSE_EXTRACT_FORMATS: dict[ExtractFormat, str] = {"markdown": "markdown", "text": "text"}
"""Our format to LiteParse's ``output_format``. Its third, ``json``, is a layout dump rather than a page body."""

LITEPARSE_EXTRACT_DEFAULT_FORMAT: ExtractFormat = "markdown"

LITEPARSE_ACCEPT = "*/*"
"""Sent instead of the JSON ``Accept`` every API provider sends: this fetches the file itself."""

DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"})
"""URL path endings extract ``auto`` hands its document parser before the web chain.

PDFs parse in process. Office files need LibreOffice on the machine; without it
the parse fails and the URL goes on to the web chain like any other.
"""

LITEPARSE_GONE_STATUSES = frozenset({404, 410})
"""Statuses that are the file's own: no backend would fetch it either. A 403 or 429 may be this machine's, so not."""

MSG_LITEPARSE_FAILED = "LiteParse could not read the file at {url}: {error}"
