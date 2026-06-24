import re
from urllib.parse import urlparse, urlunparse

from clients.tavily_client import get_tavily_client


ALLOWED_HOSTS = {"10000recipe.com", "www.10000recipe.com"}
RECIPE_PATH_PATTERN = re.compile(r"^/recipe/\d+$")


def build_recipe_query(valid_ingredients: list[str], category: str) -> str:
    ingredient_text = " ".join(valid_ingredients)

    if category and category != "상관없음":
        return f"{ingredient_text} {category} 1인분 2인분 30분 이내 초급 아무나 레시피"

    return f"{ingredient_text} 1인분 2인분 30분 이내 초급 아무나 레시피"


def normalize_recipe_url(url: str) -> str | None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return None

    if parsed.netloc not in ALLOWED_HOSTS:
        return None

    if not RECIPE_PATH_PATTERN.match(parsed.path):
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def recipe_search_tool(
    valid_ingredients: list[str],
    category: str = "상관없음",
    exclude_urls: list[str] | None = None,
    max_results: int = 5,) -> dict:
    if exclude_urls is None:
        exclude_urls = []

    if not valid_ingredients:
        return {
            "query": "",
            "candidates": [],
            "error": "유효 재료가 없습니다.",
        }

    query = build_recipe_query(valid_ingredients, category)

    normalized_exclude_urls = set()
    for url in exclude_urls:
        clean_url = normalize_recipe_url(url)
        if clean_url:
            normalized_exclude_urls.add(clean_url)

    try:
        tavily_client = get_tavily_client()

        response = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
            include_domains=["10000recipe.com"],
        )

    except Exception as e:
        return {
            "query": query,
            "candidates": [],
            "error": f"Tavily 검색 실패: {e}",
        }

    candidates = []
    seen_urls = set()

    for item in response.get("results", []):
        clean_url = normalize_recipe_url(item.get("url", ""))

        if clean_url is None:
            continue

        if clean_url in seen_urls:
            continue

        if clean_url in normalized_exclude_urls:
            continue

        seen_urls.add(clean_url)

        candidates.append(
            {
                "title": item.get("title", ""),
                "url": clean_url,
                "search_score": item.get("score"),
            }
        )

    return {
        "query": query,
        "candidates": candidates,
        "error": None,
    }