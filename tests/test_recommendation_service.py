from __future__ import annotations

from models.schemas import (
    CalorieEstimate,
    IngredientAmount,
    IngredientValidationResult,
    RecipeCandidate,
    RecipeDetail,
)
from services.recommendation_service import RecommendationService


def _candidate(recipe_id: int, title: str) -> RecipeCandidate:
    return RecipeCandidate(
        title=title, url=f"https://www.10000recipe.com/recipe/{recipe_id}"
    )


def _detail(recipe_id, title, *, servings=4, minutes=20, difficulty="초급", ingredients=None):
    return RecipeDetail(
        title=title,
        source_url=f"https://www.10000recipe.com/recipe/{recipe_id}",
        servings=servings,
        serving_text=f"{servings}인분",
        cooking_time_minutes=minutes,
        difficulty=difficulty,
        ingredients=[
            IngredientAmount(**i)
            for i in (ingredients or [{"name": "김치", "amount": "400g"}])
        ],
    )


def _validator(valid, excluded=None):
    def fn(payload, persist_new_ingredients=False):
        return IngredientValidationResult(
            valid_ingredients=valid, excluded_items=excluded or []
        )

    return fn


def _search(candidates):
    def fn(valid, category, *, exclude_urls=(), max_results=None):
        return list(candidates)

    return fn


def _scraper(detail_by_id):
    def fn(url, *, require_complete=True):
        recipe_id = url.rstrip("/").rsplit("/", 1)[-1]
        return detail_by_id.get(recipe_id)

    return fn


def _calorie_ok(menu_name, ingredients, servings):
    return CalorieEstimate(
        estimated_kcal_per_serving=520, range_min=470, range_max=600, confidence="medium"
    )


def _calorie_fail(menu_name, ingredients, servings):
    return CalorieEstimate(estimated_kcal_per_serving=None, confidence="low")


def _service(**overrides):
    defaults = dict(
        validator_fn=_validator(["김치", "밥"]),
        search_fn=_search([_candidate(101, "김치볶음밥"), _candidate(102, "김치찌개")]),
        scrape_fn=_scraper(
            {
                "101": _detail(
                    101,
                    "김치볶음밥",
                    servings=4,
                    ingredients=[
                        {"name": "밥", "amount": "400g"},
                        {"name": "김치", "amount": "1컵"},
                    ],
                ),
                "102": _detail(102, "김치찌개", servings=2, ingredients=[{"name": "김치", "amount": "200g"}]),
            }
        ),
        calorie_fn=_calorie_ok,
    )
    defaults.update(overrides)
    return RecommendationService(**defaults)


def test_full_pipeline_success_scales_to_one_serving():
    outcome = _service().recommend(["김치", "밥"], "한식")

    assert outcome.status == "SUCCESS"
    assert outcome.detail.servings == 1
    assert "원래 4인분" in outcome.detail.serving_text
    # 4인분 400g -> 1인분 100g, 1컵 -> 1/4컵
    amounts = {i.name: i.amount for i in outcome.detail.ingredients}
    assert amounts["밥"] == "100g"
    assert amounts["김치"] == "1/4컵"
    assert "100g" in outcome.card_markdown
    assert "520 kcal" in outcome.card_markdown
    assert outcome.recipe_url.endswith("/recipe/101")


def test_multi_serving_recipe_is_not_filtered_out():
    service = _service(
        search_fn=_search([_candidate(201, "대용량 김치볶음밥")]),
        scrape_fn=_scraper({"201": _detail(201, "대용량 김치볶음밥", servings=6)}),
    )
    outcome = service.recommend(["김치"], "한식")

    assert outcome.status == "SUCCESS"
    assert "원래 6인분" in outcome.detail.serving_text


def test_retry_excludes_previously_recommended_url():
    # 재추천: 101을 제외하면 102가 추천돼야 한다.
    outcome = _service().recommend(
        ["김치", "밥"],
        "한식",
        exclude_urls=["https://www.10000recipe.com/recipe/101"],
    )
    assert outcome.status == "SUCCESS"
    assert outcome.recipe_url.endswith("/recipe/102")


def test_no_valid_ingredient_short_circuits():
    outcome = _service(validator_fn=_validator([])).recommend(["핸드폰"], "한식")
    assert outcome.status == "NO_VALID_INGREDIENT"


def test_no_search_candidate():
    outcome = _service(search_fn=_search([])).recommend(["김치"], "한식")
    assert outcome.status == "NO_CANDIDATE"


def test_candidates_all_fail_condition_filter():
    service = _service(
        search_fn=_search([_candidate(301, "오래 걸리는 찜"), _candidate(302, "고급 요리")]),
        scrape_fn=_scraper(
            {
                "301": _detail(301, "오래 걸리는 찜", minutes=40),  # 시간 초과
                "302": _detail(302, "고급 요리", difficulty="중급"),  # 난이도 탈락
            }
        ),
    )
    outcome = service.recommend(["김치"], "한식")
    assert outcome.status == "NO_MATCH"


def test_calorie_failure_still_recommends():
    outcome = _service(calorie_fn=_calorie_fail).recommend(["김치", "밥"], "한식")
    assert outcome.status == "SUCCESS"
    assert "칼로리 추정 불가" in outcome.card_markdown


def test_search_error_is_reported_not_crashed():
    def boom(*a, **k):
        raise RuntimeError("network down")

    outcome = _service(search_fn=boom).recommend(["김치"], "한식")
    assert outcome.status == "ERROR"
