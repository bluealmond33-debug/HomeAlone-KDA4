"""HTTP client for fetching 만개의레시피 recipe detail pages.

All network access to recipe pages is funnelled through :func:`fetch_recipe_html`
so a single place enforces the safety rules: the URL is re-validated against the
allow-list (SSRF guard), a timeout is pinned, redirects must still land on an
allowed host, only HTML is accepted, and the response size is capped.
"""

from __future__ import annotations

import httpx

from config import settings
from tools.retry_recommendation_tool import normalize_recipe_url

_USER_AGENT = (
    "HomeAlone-RecipeBot/1.0 "
    "(+https://github.com/bluealmond33-debug/HomeAlone-KDA4)"
)
# ~2 MB is generous for a single recipe page and bounds memory/abuse.
_MAX_RESPONSE_BYTES = 2_000_000


class RecipeFetchError(RuntimeError):
    """Raised when a recipe page cannot be fetched safely."""


def fetch_recipe_html(url: str, *, client: httpx.Client | None = None) -> str:
    """Fetch and return the HTML of an allowed 만개의레시피 detail page.

    Args:
        url: A candidate recipe URL. Re-validated before any request.
        client: Optional injected ``httpx.Client`` (used by tests via
            ``httpx.MockTransport``). When omitted, a client is created and
            closed within the call.

    Raises:
        ValueError: The URL is not an allowed 만개의레시피 detail URL.
        RecipeFetchError: The request failed, redirected off-host, returned a
            non-HTML body, a non-200 status, or an oversized response.
    """
    safe_url = normalize_recipe_url(url)

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=float(settings.request_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    try:
        response = client.get(safe_url)
    except httpx.HTTPError as error:
        raise RecipeFetchError(f"레시피 페이지 요청에 실패했습니다: {error}") from error
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise RecipeFetchError(
            f"레시피 페이지 응답 코드가 비정상입니다: {response.status_code}"
        )

    # A redirect must not escape the allow-list (defense in depth for SSRF).
    try:
        normalize_recipe_url(str(response.url))
    except ValueError as error:
        raise RecipeFetchError("리다이렉트 후 허용되지 않은 URL로 이동했습니다.") from error

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        raise RecipeFetchError(f"HTML이 아닌 응답입니다: {content_type!r}")

    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise RecipeFetchError("레시피 페이지 응답이 허용 크기를 초과했습니다.")

    return response.text


__all__ = ["RecipeFetchError", "fetch_recipe_html"]
