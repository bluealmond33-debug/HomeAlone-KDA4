"""recipe_search_tool — 유효 재료/카테고리 → 만개의레시피 후보 URL 목록.

MVP 데모는 Tavily 키 없이도 돌아가도록 만개의레시피 **검색 결과 페이지**를 직접
스크래핑한다(``/recipe/list.html?q=...``). 결과 링크(``/recipe/{id}``)와 제목만
추출하며, 인분·시간·난이도 같은 조건은 여기서 단정하지 않고 상세 스크래퍼가 확인한다.

Tavily 기반 검색으로 교체할 때도 출력 계약(list[RecipeCandidate])은 동일하게 유지한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from clients.recipe_http_client import fetch_listing_html
from config import settings
from models.schemas import RecipeCandidate
from tools.retry_recommendation_tool import normalize_recipe_url

_SEARCH_BASE = "https://www.10000recipe.com/recipe/list.html"


def build_search_url(valid_ingredients: Iterable[str], category: str) -> str:
    """재료(공백 구분)와 카테고리를 합쳐 만개의레시피 검색 URL을 만든다."""
    terms = [term.strip() for term in valid_ingredients if term and term.strip()]
    if category and category != "상관없음":
        terms.append(category)
    query = " ".join(terms)
    return f"{_SEARCH_BASE}?q={quote_plus(query)}&order=accuracy"


def parse_search_results(html: str) -> list[RecipeCandidate]:
    """검색 결과 HTML에서 (제목, /recipe/{id} URL) 후보를 추출한다."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[RecipeCandidate] = []
    seen: set[str] = set()

    for link in soup.select("a.common_sp_link"):
        href = link.get("href") or ""
        absolute = href if href.startswith("http") else f"https://www.10000recipe.com{href}"
        try:
            url = normalize_recipe_url(absolute)
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)

        li = link.find_parent("li")
        title_node = li.select_one(".common_sp_caption_tit") if li else None
        title = title_node.get_text(strip=True) if title_node else ""
        candidates.append(RecipeCandidate(title=title or "(제목 미상)", url=url))

    return candidates


def recipe_search_tool(
    valid_ingredients: list[str] | Mapping[str, Any],
    category: str = "상관없음",
    *,
    exclude_urls: Iterable[str] = (),
    max_results: int | None = None,
    client: Any | None = None,
) -> list[RecipeCandidate]:
    """후보 레시피 URL 목록을 반환한다.

    Args:
        valid_ingredients: 유효 재료 목록(또는 PRD 형식의
            ``{"valid_ingredients": [...], "category": ...}`` 매핑).
        category: 음식 카테고리. ``상관없음``이면 검색어에 넣지 않는다.
        exclude_urls: 이전 추천 등 제외할 URL.
        max_results: 최대 후보 수(기본 ``settings.max_search_results``).
        client: 주입형 ``httpx.Client`` (테스트용).
    """
    if isinstance(valid_ingredients, Mapping):
        payload = valid_ingredients
        category = payload.get("category", category)
        exclude_urls = payload.get("exclude_urls", exclude_urls)
        valid_ingredients = payload.get("valid_ingredients", [])

    limit = max_results or settings.max_search_results
    excluded = set()
    for raw in exclude_urls:
        try:
            excluded.add(normalize_recipe_url(raw))
        except ValueError:
            continue

    url = build_search_url(valid_ingredients, category)
    html = fetch_listing_html(url, client=client)

    results: list[RecipeCandidate] = []
    for candidate in parse_search_results(html):
        if normalize_recipe_url(str(candidate.url)) in excluded:
            continue
        results.append(candidate)
        if len(results) >= limit:
            break
    return results


__all__ = [
    "build_search_url",
    "parse_search_results",
    "recipe_search_tool",
]
