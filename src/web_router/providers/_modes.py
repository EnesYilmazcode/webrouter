"""Vendor modes on the wire: pinning one, merging its parts into a payload, and what a backend offers a router.

A pinned id (``provider="exa:exa-instant"``, or a chain entry) builds the backend's class with
the mode stamped on every request: the depth slot fills ``search_depth`` (or ``effort``), and
the request's ``mode`` is the canonical string, so the price list prices it. When the payload
is built, a content replaces the fields its wire writes ("highlights instead of text"), a tier
or flag is merged into nested objects, and the caller's ``provider_options`` still go last.

A mode is refused, before anything is sent, when the caller set something it would overwrite:
a ``provider_options`` key its wire writes, a ``search_depth`` other than the one it stands
for, or an option (``search_depth``, ``effort``) that sets a field the mode writes to another value.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import cache
from typing import Any, ClassVar, Literal, Protocol, cast

from web_router.constants_cost import COST_ESTIMATED
from web_router.constants_modes import (
    DEPTH_LEVELS,
    EFFORT_LEVELS,
    ID_SEP,
    MODE_FIELD,
    MSG_PIN_DEPTH,
    MSG_PIN_EFFORT,
    MSG_PIN_OPTION,
    MSG_PIN_TOOL,
    MSG_PIN_WRITES,
    PART_SEP,
)
from web_router.exceptions_typed import InvalidParameterError
from web_router.modes import Content, Declared, Flag, Slots, Tier, parse_id, split_mode
from web_router.types import NormalizedRequest, SearchRequest, provider_name

SEARCH: Literal["search"] = "search"
PROBED = ("search_depth", "effort")
"""The options a mode's wire may collide with: each is probed alone against the payload it changes."""


class ModeOwner(Protocol):
    """A provider instance, as the merge reads it: its name, its parts, and how it builds a payload."""

    name: ClassVar[str]
    tiers: ClassVar[Mapping[str, Tier]]
    contents: ClassVar[Mapping[str, Content]]
    flags: ClassVar[Mapping[str, Flag]]

    def _build_payload(self, request: Any) -> dict[str, Any]: ...


def merged(ours: dict[str, Any], theirs: Mapping[str, Any]) -> dict[str, Any]:
    """``theirs`` laid over ``ours`` at every depth: a nested object is merged, any other value replaced."""
    out = dict(ours)
    for key, value in theirs.items():
        nested = out.get(key)
        out[key] = merged(nested, value) if isinstance(nested, dict) and isinstance(value, Mapping) else value
    return out


def slots(owner: Any, mode: str) -> Slots:
    """``mode``, a canonical mode of ``owner``, in its slots."""
    return split_mode(owner.name, mode.split(PART_SEP), owner)


def _wires(owner: Any, found: Slots) -> tuple[dict[str, Any], dict[str, Any]]:
    """The content's wire, then the tier's and flags' merged into one."""
    content = owner.contents.get(found.depth) if found.depth else None
    laid: dict[str, Any] = {}
    for part in [found.tier, *found.flags]:
        if part:
            laid = merged(laid, (owner.tiers.get(part) or owner.flags[part]).wire)
    return dict(content.wire) if content else {}, laid


def with_mode(payload: dict[str, Any], owner: ModeOwner, request: NormalizedRequest) -> dict[str, Any]:
    """``payload`` with the request's mode merged in, before ``provider_options``; refused as the module says."""
    mode = getattr(request, "mode", None)
    if not mode:
        return payload
    found = slots(owner, mode)
    replaced, laid = _wires(owner, found)
    content = owner.contents.get(found.depth) if found.depth else None
    for field in {*replaced, *laid} & set(request.provider_options):
        raise InvalidParameterError(MODE_FIELD, MSG_PIN_OPTION.format(mode=mode, field=field))
    asked = getattr(request, "search_depth", None)
    if content is not None and asked not in (None, content.as_depth):
        raise InvalidParameterError(MODE_FIELD, MSG_PIN_DEPTH.format(mode=mode, depth=content.as_depth, asked=asked))
    _refuse_collisions(owner, request, mode, {**replaced, **laid}, content is not None)
    return merged({**payload, **replaced}, laid)


def _refuse_collisions(
    owner: ModeOwner, request: NormalizedRequest, mode: str, wire: dict[str, Any], has_content: bool
) -> None:
    """Refuse an option the caller set that changes a field the wire writes, to a value the wire does not send."""
    bare = request.model_copy(update={"mode": None, "provider_options": {}, **dict.fromkeys(PROBED)})
    base = owner._build_payload(bare)
    for option in PROBED:
        value = getattr(request, option, None)
        if value is None or (has_content and option == "search_depth"):
            continue
        alone = owner._build_payload(bare.model_copy(update={option: value}))
        for field, sent in wire.items():
            if alone.get(field) != base.get(field) and alone.get(field) != sent:
                message = MSG_PIN_WRITES.format(mode=mode, field=field, option=option, value=value)
                raise InvalidParameterError(MODE_FIELD, message)


def pinned_request(owner: Any, request: SearchRequest, mode: str) -> SearchRequest:
    """``request`` in ``mode``: its level fills ``search_depth`` or ``effort``, and ``mode`` is the canonical string."""
    found = slots(owner, mode)
    update: dict[str, Any] = {}
    if found.depth in DEPTH_LEVELS:
        if request.search_depth not in (None, found.depth):
            message = MSG_PIN_DEPTH.format(mode=mode, depth=found.depth, asked=request.search_depth)
            raise InvalidParameterError(MODE_FIELD, message)
        update["search_depth"] = found.depth
    elif found.depth in EFFORT_LEVELS:
        if request.effort not in (None, found.depth):
            message = MSG_PIN_EFFORT.format(mode=mode, effort=found.depth, asked=request.effort)
            raise InvalidParameterError(MODE_FIELD, message)
        update["effort"] = found.depth
    depth = found.depth or request.search_depth
    update["mode"] = Slots(found.tier, depth, found.flags).mode
    return request.model_copy(update=update)


def pinned_for(chain: Any, request: Any) -> Any:
    """``request`` in ``chain``'s pinned mode when ``chain`` is a pinned search backend, else unchanged.

    The router applies it before a call is priced, so a budget charges the mode's price, not the default's.
    """
    pinned = getattr(chain, "pinned", None)
    return pinned_request(chain, request, pinned) if pinned and isinstance(request, SearchRequest) else request


def _costed(response: Any, owner: Any, request: SearchRequest) -> Any:
    """``response`` carrying the mode's estimated price when it states none, as a chain member's answer must."""
    from web_router.routing.metered import estimated_cost  # the routing package imports the providers

    if response.cost_usd is not None or (cost := estimated_cost(SEARCH, owner.name, request)) is None:
        return response
    return response.model_copy(update={"cost_usd": cost, "cost_source": COST_ESTIMATED})


class _PinnedSearch:
    """Stamps the class's ``pinned`` mode on every search, searches as the backend does, and prices the answer."""

    pinned: ClassVar[str]

    def search(self, request: SearchRequest) -> Any:
        request = pinned_request(self, request, self.pinned)
        return _costed(super().search(request), self, request)  # type: ignore[misc]

    async def asearch(self, request: SearchRequest) -> Any:
        request = pinned_request(self, request, self.pinned)
        return _costed(await super().asearch(request), self, request)  # type: ignore[misc]


@cache
def _pinned(base: type, mode: str) -> type:
    return type(base.__name__, (_PinnedSearch, base), {"pinned": mode, "__module__": base.__module__})


def pinned_class(name: Any, resolve: Callable[[str], type]) -> type:
    """The class for ``name``: ``resolve(name)``, or for ``provider:mode`` that class pinned to the mode."""
    text = provider_name(name)
    if ID_SEP not in text:
        return resolve(text)
    found = parse_id(text, cast("Callable[[str], Declared]", resolve))
    if found.tool not in (None, SEARCH):
        raise InvalidParameterError(MODE_FIELD, MSG_PIN_TOOL.format(text=text, tool=found.tool))
    base = resolve(found.provider)
    return _pinned(base, found.mode) if found.mode else base


def offers(owner: Any) -> tuple[str, ...]:
    """The modes a router may pick for ``owner``, its default left out.

    Unless the class sets ``offers`` itself: every tier at the default depth, then each depth
    level it serves and each content at the default tier, then each flag. A tier the class names
    as its ``default_tier`` is the default already, so it is never offered twice.
    """
    own = getattr(owner, "offers", None)
    if own is not None:
        return tuple(own)
    default = getattr(owner, "default_tier", None)
    mapped = SEARCH + "_depth" in getattr(owner, "supported_parameters", ())
    levels = [level for level in DEPTH_LEVELS if mapped and level in getattr(owner, "depth_levels", ())]
    tiers = [tier for tier in owner.tiers if tier != default]
    return (*tiers, *levels, *owner.contents, *owner.flags)
