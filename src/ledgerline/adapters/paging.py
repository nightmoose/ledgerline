"""List-call rules observed on the demo host.

beneficiaries, global_accounts, fx/conversions, and deposits return 400
invalid_argument unless page_num (0-based) and page_size are both sent, and
page_size is at least 10. The body is {has_more, items}. Deposits also
include total_count.

GET /transfers is separate: it takes page_size and returns {items: [...]}.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ledgerline.adapters.base import AirwallexError

MIN_PAGE_SIZE = 10


def require_page(page_num: int, page_size: int) -> dict[str, int]:
    if isinstance(page_num, bool) or not isinstance(page_num, int) or page_num < 0:
        raise AirwallexError(
            "invalid_argument",
            "page_num is 0-based and must be an integer >= 0",
            status=400,
            source="page_num",
        )
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < MIN_PAGE_SIZE:
        raise AirwallexError(
            "invalid_argument",
            "page_size must be an integer >= 10",
            status=400,
            source="page_size",
        )
    return {"page_num": page_num, "page_size": page_size}


def page_slice(items: list[Any], page_num: int, page_size: int, *, total_count: bool = False) -> dict[str, Any]:
    require_page(page_num, page_size)
    start = page_num * page_size
    chunk = items[start : start + page_size]
    body: dict[str, Any] = {
        "has_more": start + page_size < len(items),
        "items": chunk,
    }
    if total_count:
        body["total_count"] = len(items)
    return body


def expect_items(body: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise AirwallexError(
            "invalid_response",
            f"{path} did not return an items list",
            status=502,
            source=path,
        )
    return body


def expect_page(body: Any, *, path: str, total_count: bool = False) -> dict[str, Any]:
    page = expect_items(body, path=path)
    if "has_more" not in page:
        raise AirwallexError(
            "invalid_response",
            f"{path} did not return has_more",
            status=502,
            source=path,
        )
    if total_count and "total_count" not in page:
        raise AirwallexError(
            "invalid_response",
            f"{path} did not return total_count",
            status=502,
            source=path,
        )
    return page


def collect_pages(fetch: Callable[..., dict[str, Any]], *, page_size: int = MIN_PAGE_SIZE) -> list[Any]:
    """Follow has_more. fetch(page_num, page_size) must return a page body."""
    collected: list[Any] = []
    for page_num in range(100):
        body = fetch(page_num, page_size)
        collected.extend(body["items"])
        if not body.get("has_more"):
            return collected
    raise AirwallexError(
        "invalid_response",
        "list pagination did not finish within 100 pages",
        status=502,
        source="page_num",
    )
