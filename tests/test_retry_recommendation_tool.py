from __future__ import annotations

import unittest

from pydantic import ValidationError

from models.retry_schemas import RecommendationResult, RetryRecommendationInput
from tools.retry_recommendation_tool import (
    RetryPipelineError,
    normalize_recipe_url,
    retry_recommendation_tool,
)


def make_candidate(
    recipe_id: int,
    title: str,
    *,
    category: str = "한식",
    servings: int = 1,
    minutes: int = 20,
    difficulty: str = "초급",
    ingredients: list[str] | None = None,
) -> RecommendationResult:
    return RecommendationResult(
        title=title,
        source_url=f"https://www.10000recipe.com/recipe/{recipe_id}",
        category=category,
        servings=servings,
        cooking_time_minutes=minutes,
        difficulty=difficulty,
        ingredient_names=ingredients or ["김치", "밥"],
    )


class RetryRecommendationToolTest(unittest.TestCase):
    def test_uses_valid_cached_candidate_without_search(self) -> None:
        called = False

        def search_pipeline(**_: object) -> list[RecommendationResult]:
            nonlocal called
            called = True
            return []

        request = RetryRecommendationInput(
            valid_ingredients=["김치", "밥"],
            category="한식",
            previous_recipe_urls=[
                "https://www.10000recipe.com/recipe/100?from=old"
            ],
            previous_menu_names=["김치 볶음밥"],
            cached_candidates=[
                make_candidate(100, "김치볶음밥"),
                make_candidate(101, "김치전"),
            ],
        )

        result = retry_recommendation_tool(
            request, search_pipeline=search_pipeline
        )

        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.source, "CACHE")
        self.assertEqual(result.recommendation.source_url.rsplit("/", 1)[-1], "101")
        self.assertFalse(called)
        self.assertIn(result.recommendation.source_url, result.previous_recipe_urls)

    def test_changed_conditions_skip_old_cache_and_use_search(self) -> None:
        received: dict[str, object] = {}

        def search_pipeline(**kwargs: object) -> list[RecommendationResult]:
            received.update(kwargs)
            return [
                make_candidate(
                    201,
                    "오야코동",
                    category="일식",
                    ingredients=["계란", "닭고기"],
                )
            ]

        result = retry_recommendation_tool(
            {
                "valid_ingredients": ["계란"],
                "category": "일식",
                "previous_recipe_urls": [
                    "https://www.10000recipe.com/recipe/200"
                ],
                "cached_candidates": [
                    make_candidate(202, "김치전", category="한식")
                ],
            },
            search_pipeline=search_pipeline,
        )

        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.source, "SEARCH")
        self.assertEqual(result.recommendation.title, "오야코동")
        self.assertEqual(received["category"], "일식")
        self.assertIn(
            "https://www.10000recipe.com/recipe/200",
            received["exclude_urls"],
        )

    def test_url_and_normalized_menu_name_both_prevent_duplicates(self) -> None:
        def search_pipeline(**_: object) -> list[RecommendationResult]:
            return [
                make_candidate(300, "다른 제목"),
                make_candidate(301, "김치  볶음밥"),
                make_candidate(302, "계란찜", ingredients=["계란"]),
            ]

        result = retry_recommendation_tool(
            {
                "valid_ingredients": ["계란"],
                "category": "한식",
                "previous_recipe_urls": [
                    "https://m.10000recipe.com/recipe/300/?q=tracking"
                ],
                "previous_menu_names": ["김치볶음밥"],
            },
            search_pipeline=search_pipeline,
        )

        self.assertEqual(result.recommendation.title, "계란찜")

    def test_excluded_ingredient_skips_cached_candidate(self) -> None:
        called = False

        def search_pipeline(**_: object) -> list[RecommendationResult]:
            nonlocal called
            called = True
            return []

        result = retry_recommendation_tool(
            {
                "valid_ingredients": ["계란", "파"],
                "excluded_ingredients": ["양파"],
                "category": "한식",
                "cached_candidates": [
                    make_candidate(
                        350,
                        "양파 계란 볶음",
                        ingredients=["계란", "양파"],
                    ),
                    make_candidate(
                        351,
                        "계란 파 볶음",
                        ingredients=["계란", "파"],
                    ),
                ],
            },
            search_pipeline=search_pipeline,
        )

        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.recommendation.title, "계란 파 볶음")
        self.assertFalse(called)

    def test_exhausted_candidates_do_not_mutate_history(self) -> None:
        previous_url = "https://www.10000recipe.com/recipe/400"

        def search_pipeline(**_: object) -> list[RecommendationResult]:
            return [
                make_candidate(400, "이미 추천됨"),
                make_candidate(401, "너무 오래 걸림", minutes=60),
                make_candidate(402, "재료 불일치", ingredients=["두부"]),
            ]

        result = retry_recommendation_tool(
            {
                "valid_ingredients": ["김치"],
                "category": "한식",
                "previous_recipe_urls": [previous_url],
            },
            search_pipeline=search_pipeline,
        )

        self.assertEqual(result.status, "NO_NEW_CANDIDATE")
        self.assertIsNone(result.recommendation)
        self.assertEqual(result.previous_recipe_urls, [previous_url])

    def test_malformed_search_item_is_skipped_with_warning(self) -> None:
        def search_pipeline(**_: object) -> list[dict[str, object]]:
            return [
                {"title": "필수 필드가 없는 결과"},
                {
                    "title": "두부조림",
                    "source_url": "https://www.10000recipe.com/recipe/501",
                    "category": "한식",
                    "servings": 1,
                    "cooking_time_minutes": 30,
                    "difficulty": "아무나",
                    "ingredient_names": ["두부"],
                },
            ]

        result = retry_recommendation_tool(
            {"valid_ingredients": ["두부"], "category": "한식"},
            search_pipeline=search_pipeline,
        )

        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.recommendation.title, "두부조림")
        self.assertEqual(len(result.warnings), 1)

    def test_multi_serving_candidate_is_accepted_on_retry(self) -> None:
        # New policy: serving count is no longer a reject criterion. Any serving
        # count is accepted (amounts are normalized to 1 serving by the scaler),
        # so the first ranked candidate wins regardless of its serving size.
        def search_pipeline(**_: object) -> list[RecommendationResult]:
            return [
                make_candidate(601, "4인분 두부조림", servings=4, ingredients=["두부"]),
                make_candidate(602, "1인분 두부조림", servings=1, ingredients=["두부"]),
            ]

        result = retry_recommendation_tool(
            {"valid_ingredients": ["두부"], "category": "한식"},
            search_pipeline=search_pipeline,
        )

        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.recommendation.title, "4인분 두부조림")
        self.assertEqual(result.recommendation.servings, 4)

    def test_pipeline_failure_is_not_reported_as_candidate_exhaustion(self) -> None:
        def broken_pipeline(**_: object) -> list[RecommendationResult]:
            raise TimeoutError("Tavily timeout")

        with self.assertRaises(RetryPipelineError) as context:
            retry_recommendation_tool(
                {"valid_ingredients": ["김치"], "category": "한식"},
                search_pipeline=broken_pipeline,
            )

        self.assertIsInstance(context.exception.__cause__, TimeoutError)

    def test_missing_pipeline_raises_configuration_error(self) -> None:
        with self.assertRaises(RetryPipelineError):
            retry_recommendation_tool(
                {"valid_ingredients": ["김치"], "category": "한식"}
            )

    def test_invalid_input_and_unsafe_url_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RetryRecommendationInput(valid_ingredients=[], category="한식")

        with self.assertRaises(ValueError):
            normalize_recipe_url("https://evil.example/recipe/1")

        with self.assertRaises(ValueError):
            normalize_recipe_url("http://www.10000recipe.com/recipe/1")


if __name__ == "__main__":
    unittest.main()
