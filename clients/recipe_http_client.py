"""HTTP client for fetching 만개의레시피 pages (recipe detail + search listing).

All network access is funnelled through this module so a single place enforces
the safety rules: the URL is validated against the allow-list (SSRF guard), a
timeout is pinned, redirects must still land on an allowed host, only HTML is
accepted, and the response size is capped.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from config import settings
from tools.retry_recommendation_tool import normalize_recipe_url

_USER_AGENT = (
    "Mozilla/5.0 (compatible; HomeAlone-RecipeBot/1.0; "
    "+https://github.com/bluealmond33-debug/HomeAlone-KDA4)"
)
# ~2 MB is generous for a single page and bounds memory/abuse.
_MAX_RESPONSE_BYTES = 2_000_000


class RecipeFetchError(RuntimeError):
    """Raised when a page cannot be fetched safely."""


def _assert_allowed_host(url: str) -> None:
    """Validate scheme/host without requiring a ``/recipe/{id}`` path."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = host == "10000recipe.com" or host.endswith(".10000recipe.com")
    if parsed.scheme.lower() != "https" or not allowed:
        raise ValueError("허용된 만개의레시피 HTTPS URL만 사용할 수 있습니다.")


def _request_html(url, *, client, redirect_validator):
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=float(settings.request_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    try:
        response = client.get(url)
    except httpx.HTTPError as error:
        raise RecipeFetchError(f"페이지 요청에 실패했습니다: {error}") from error
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise RecipeFetchError(f"페이지 응답 코드가 비정상입니다: {response.status_code}")

    # A redirect must not escape the allow-list (defense in depth for SSRF).
    try:
        redirect_validator(str(response.url))
    except ValueError as error:
        raise RecipeFetchError("리다이렉트 후 허용되지 않은 URL로 이동했습니다.") from error

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        raise RecipeFetchError(f"HTML이 아닌 응답입니다: {content_type!r}")

    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise RecipeFetchError("페이지 응답이 허용 크기를 초과했습니다.")

    return response.text


def fetch_recipe_html(url: str, *, client: httpx.Client | None = None) -> str:
    """Fetch the HTML of an allowed 만개의레시피 **detail** page (``/recipe/{id}``).

    Raises:
        ValueError: The URL is not an allowed 만개의레시피 detail URL.
        RecipeFetchError: The request failed, redirected off-host, returned a
            non-HTML body, a non-200 status, or an oversized response.
    """
    safe_url = normalize_recipe_url(url)
    return _request_html(
        safe_url, client=client, redirect_validator=normalize_recipe_url
    )


def fetch_listing_html(url: str, *, client: httpx.Client | None = None) -> str:
    """Fetch the HTML of a 만개의레시피 **search listing** page.

    The path is not constrained to ``/recipe/{id}`` (search uses
    ``/recipe/list.html``), but the host must still be on the allow-list.
    """
    _assert_allowed_host(url)
    return _request_html(
        url, client=client, redirect_validator=_assert_allowed_host
    )


__all__ = ["RecipeFetchError", "fetch_recipe_html", "fetch_listing_html"]
