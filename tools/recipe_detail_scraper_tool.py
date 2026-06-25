"""Scrape a 만개의레시피 detail page into a validated :class:`RecipeDetail`.

Strategy (PRD 8.3): JSON-LD (schema.org/Recipe) is read first because it is the
most stable source; the documented CSS selectors (``.view2_summary_info1~3``,
``.ready_ingre3``) are the fallback. Servings and cooking time are normalized to
integers.

The returned detail is the **raw page truth** (original serving count and
amounts). Call :func:`services.serving_scaler.scale_recipe_detail_to_one_serving`
to present per-1-serving amounts, so the calorie estimator still sees the real
serving size.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from clients.recipe_http_client import fetch_recipe_html
from models.schemas import IngredientAmount, RecipeDetail
from tools.retry_recommendation_tool import normalize_recipe_url


def _text_or_none(node) -> str | None:
    if node is None:
        return None
    text = node.get_text(strip=True)
    return text or None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _parse_minutes(value: Any) -> int | None:
    """Normalize a cooking-time string to minutes.

    Handles ISO 8601 durations (``PT1H30M``) and Korean text (``30분 이내``,
    ``1시간``, ``1시간 30분``).
    """
    if value is None:
        return None
    text = str(value).strip()

    iso = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text, re.IGNORECASE)
    if iso and (iso.group(1) or iso.group(2)):
        return int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0)

    hours = re.search(r"(\d+)\s*시간", text)
    minutes = re.search(r"(\d+)\s*분", text)
    total = (int(hours.group(1)) * 60 if hours else 0) + (
        int(minutes.group(1)) if minutes else 0
    )
    if total:
        return total

    bare = re.search(r"\d+", text)
    return int(bare.group()) if bare else None


def _iter_ld_objects(data: Any):
    if isinstance(data, list):
        for item in data:
            yield from _iter_ld_objects(item)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_ld_objects(item)
        yield data


def _is_recipe(obj: dict[str, Any]) -> bool:
    types = obj.get("@type")
    if isinstance(types, list):
        return any(str(t).lower() == "recipe" for t in types)
    return str(types).lower() == "recipe"


def _load_recipe_ld(soup: BeautifulSoup) -> dict[str, Any] | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _iter_ld_objects(data):
            if _is_recipe(obj):
                return obj
    return None


def _first_url(value: Any) -> str | None:
    """Pull a single URL string out of a JSON-LD ``image`` value."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            url = _first_url(item)
            if url:
                return url
    if isinstance(value, dict):
        return _first_url(value.get("url"))
    return None


def _extract_image(soup: BeautifulSoup, ld: dict[str, Any] | None) -> str | None:
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return og["content"].strip()
    if ld:
        return _first_url(ld.get("image"))
    return None


def _extract_title(soup: BeautifulSoup, ld: dict[str, Any] | None) -> str | None:
    if ld and ld.get("name"):
        return str(ld["name"]).strip() or None
    css = _text_or_none(soup.select_one(".view2_summary h3"))
    if css:
        return css
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip() or None
    return None


def _extract_ingredients(
    soup: BeautifulSoup, ld: dict[str, Any] | None
) -> list[IngredientAmount]:
    items: list[IngredientAmount] = []
    for li in soup.select(".ready_ingre3 li"):
        name = _text_or_none(li.select_one(".ingre_list_name"))
        if not name:
            continue
        # Live 만개의레시피 puts the amount in ``.ingre_list_ea``; older/sample
        # markup uses ``.ingre_list_value``.
        amount = _text_or_none(li.select_one(".ingre_list_ea")) or _text_or_none(
            li.select_one(".ingre_list_value")
        )
        items.append(IngredientAmount(name=name, amount=amount))
    if items:
        return items

    # Fallback: JSON-LD lists ingredients as single strings ("밥 400g"); we keep
    # the whole string as the name because name/amount are not separated there.
    if ld:
        for entry in ld.get("recipeIngredient") or ld.get("ingredients") or []:
            text = str(entry).strip()
            if text:
                items.append(IngredientAmount(name=text, amount=None))
    return items


def _extract_steps(soup: BeautifulSoup, ld: dict[str, Any] | None) -> list[str]:
    steps = [
        text
        for node in soup.select("#stepDiv .media-body, .view_step_cont .media-body")
        if (text := node.get_text(strip=True))
    ]
    if steps:
        return steps

    if ld:
        raw = ld.get("recipeInstructions")
        if isinstance(raw, str):
            return [raw.strip()] if raw.strip() else []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    text = str(entry.get("text", "")).strip()
                else:
                    text = str(entry).strip()
                if text:
                    steps.append(text)
    return steps


def parse_recipe_detail(
    html: str, source_url: str, *, require_complete: bool = True
) -> RecipeDetail | None:
    """Parse recipe HTML into a :class:`RecipeDetail` (raw, unscaled).

    Returns ``None`` when the page is not a usable recipe. With
    ``require_complete`` (default), the filtering fields — title, servings,
    cooking time, and difficulty — must all be present, matching the PRD rule of
    excluding candidates whose conditions cannot be parsed.
    """
    canonical_url = normalize_recipe_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    ld = _load_recipe_ld(soup)

    title = _extract_title(soup, ld)
    servings = _parse_int(_text_or_none(soup.select_one(".view2_summary_info1")))
    if servings is None and ld:
        servings = _parse_int(ld.get("recipeYield"))

    minutes = _parse_minutes(_text_or_none(soup.select_one(".view2_summary_info2")))
    if minutes is None and ld:
        minutes = _parse_minutes(ld.get("totalTime") or ld.get("cookTime"))

    difficulty = _text_or_none(soup.select_one(".view2_summary_info3"))

    if title is None:
        return None
    if require_complete and (
        servings is None or minutes is None or difficulty is None
    ):
        return None

    return RecipeDetail(
        title=title,
        source_url=canonical_url,
        image_url=_extract_image(soup, ld),
        servings=servings,
        serving_text=_text_or_none(soup.select_one(".view2_summary_info1")),
        cooking_time_minutes=minutes,
        cooking_time_text=_text_or_none(soup.select_one(".view2_summary_info2")),
        difficulty=difficulty,
        ingredients=_extract_ingredients(soup, ld),
        cooking_steps=_extract_steps(soup, ld),
        scraped_at=datetime.now(timezone.utc),
    )


def recipe_detail_scraper_tool(
    url: str,
    *,
    client: Any | None = None,
    require_complete: bool = True,
) -> RecipeDetail | None:
    """Fetch a recipe page and return its raw :class:`RecipeDetail`.

    URL validation and the safe fetch happen in
    :func:`clients.recipe_http_client.fetch_recipe_html`. Returns ``None`` when
    the page cannot be parsed into a usable recipe.
    """
    html = fetch_recipe_html(url, client=client)
    return parse_recipe_detail(html, url, require_complete=require_complete)


__all__ = ["parse_recipe_detail", "recipe_detail_scraper_tool"]
