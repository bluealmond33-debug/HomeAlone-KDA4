from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from clients.recipe_http_client import RecipeFetchError
from services.serving_scaler import scale_recipe_detail_to_one_serving
from tools.recipe_detail_scraper_tool import (
    parse_recipe_detail,
    recipe_detail_scraper_tool,
)

URL = "https://www.10000recipe.com/recipe/6920226"
FIXTURE = (
    Path(__file__).parent / "fixtures" / "recipe_detail_sample.html"
).read_text(encoding="utf-8")


def _html_client(html: str = FIXTURE, *, content_type: str = "text/html; charset=utf-8"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=html.encode("utf-8"), headers={"content-type": content_type}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_fixture_extracts_raw_detail():
    detail = parse_recipe_detail(FIXTURE, URL)

    assert detail is not None
    assert detail.title == "김치볶음밥 황금레시피"
    assert detail.servings == 4
    assert detail.cooking_time_minutes == 30
    assert detail.difficulty == "초급"
    assert "/recipe/6920226" in str(detail.source_url)
    assert detail.image_url is not None
    assert [(i.name, i.amount) for i in detail.ingredients] == [
        ("밥", "400g"),
        ("김치", "1컵"),
        ("대파", "1대"),
        ("소금", "약간"),
    ]
    assert len(detail.cooking_steps) == 2


def test_scaled_detail_is_one_serving():
    detail = parse_recipe_detail(FIXTURE, URL)

    scaled = scale_recipe_detail_to_one_serving(detail)

    assert scaled.servings == 1
    assert "원래 4인분" in scaled.serving_text
    amounts = {item.name: item.amount for item in scaled.ingredients}
    assert amounts == {"밥": "100g", "김치": "1/4컵", "대파": "1/4대", "소금": "약간"}


def test_time_parsing_handles_korean_and_iso():
    from tools.recipe_detail_scraper_tool import _parse_minutes

    assert _parse_minutes("30분 이내") == 30
    assert _parse_minutes("1시간 30분") == 90
    assert _parse_minutes("PT1H30M") == 90
    assert _parse_minutes(None) is None


def test_missing_difficulty_is_excluded_when_complete_required():
    html = FIXTURE.replace('<span class="view2_summary_info3">초급</span>', "")

    assert parse_recipe_detail(html, URL) is None

    lenient = parse_recipe_detail(html, URL, require_complete=False)
    assert lenient is not None
    assert lenient.difficulty is None


def test_scraper_tool_fetches_and_parses_via_injected_client():
    detail = recipe_detail_scraper_tool(URL, client=_html_client())

    assert detail is not None
    assert detail.servings == 4
    assert detail.title == "김치볶음밥 황금레시피"


def test_scraper_tool_rejects_disallowed_url_before_network():
    # normalize_recipe_url runs first, so no request is ever made.
    with pytest.raises(ValueError):
        recipe_detail_scraper_tool("http://malicious.example.com/recipe/1")


def test_scraper_tool_rejects_non_html_response():
    client = _html_client("{}", content_type="application/json")
    with pytest.raises(RecipeFetchError):
        recipe_detail_scraper_tool(URL, client=client)
