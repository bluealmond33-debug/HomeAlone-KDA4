"""Return a new recipe while excluding every recipe recommended in this session.

The tool owns retry-state handling and duplicate prevention. Search, scraping,
filtering, ranking, and calorie estimation remain in the service pipeline and are
injected through ``search_pipeline``. This keeps the tool deterministic and easy
to unit test without external API calls.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from models.retry_schemas import (
    Category,
    RecommendationResult,
    RetryRecommendationInput,
    RetryRecommendationOutput,
)


ALLOWED_DIFFICULTIES = frozenset({"초급", "아무나"})
RECIPE_PATH_PATTERN = re.compile(r"^/recipe/(\d+)/?$", re.IGNORECASE)


class RetryPipelineError(RuntimeError):
    """Raised when retry search fails, rather than misreporting an empty result."""


class SearchPipeline(Protocol):
    """Contract for the existing search -> scrape -> filter -> rank pipeline."""

    def __call__(
        self,
        *,
        valid_ingredients: tuple[str, ...],
        category: Category,
        exclude_urls: frozenset[str],
        exclude_menu_names: frozenset[str],
    ) -> Sequence[RecommendationResult | Mapping[str, Any]]: ...


def normalize_recipe_url(url: str) -> str:
    """Validate and canonicalize an allowed 만개의레시피 detail URL.

    Query strings, fragments, alternate approved subdomains, and a trailing slash
    collapse to one URL key. Credentials, ports, HTTP, and non-recipe paths are
    rejected before any downstream network access.
    """

    if not isinstance(url, str) or not url.strip():
        raise ValueError("레시피 URL은 빈 문자열일 수 없습니다.")

    parsed = urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed_host = hostname == "10000recipe.com" or hostname.endswith(
        ".10000recipe.com"
    )
    if parsed.scheme.lower() != "https" or not allowed_host:
        raise ValueError("허용된 만개의레시피 HTTPS URL만 사용할 수 있습니다.")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("사용자 정보나 포트가 포함된 URL은 허용되지 않습니다.")

    match = RECIPE_PATH_PATTERN.fullmatch(parsed.path)
    if match is None:
        raise ValueError("만개의레시피 상세 경로(/recipe/{숫자})가 아닙니다.")

    recipe_id = match.group(1)
    return f"https://www.10000recipe.com/recipe/{recipe_id}"


def normalize_menu_name(name: str) -> str:
    """Build a stable secondary duplicate key from a displayed menu name."""

    if not isinstance(name, str):
        return ""
    normalized = unicodedata.normalize("NFKC", name).casefold().strip()
    return "".join(character for character in normalized if character.isalnum())


def _normalize_ingredient(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold().strip()
    return " ".join(normalized.split())


def _meets_latest_conditions(
    candidate: RecommendationResult,
    *,
    valid_ingredients: set[str],
    category: Category,
) -> bool:
    """Recheck every cache/search result against PRD 6.2 mandatory rules.

    Serving count is intentionally *not* a reject criterion: 만개의레시피 rarely
    has 1-serving recipes, so any serving count is accepted and amounts are later
    normalized to one serving by ``services.serving_scaler``.
    """

    if category != "상관없음" and candidate.category != category:
        return False
    if candidate.cooking_time_minutes > 30:
        return False
    if candidate.difficulty not in ALLOWED_DIFFICULTIES:
        return False

    candidate_ingredients = {
        _normalize_ingredient(item) for item in candidate.ingredient_names
    }
    return bool(valid_ingredients & candidate_ingredients)


def _coerce_search_results(
    raw_candidates: Iterable[RecommendationResult | Mapping[str, Any]],
) -> tuple[list[RecommendationResult], list[str]]:
    candidates: list[RecommendationResult] = []
    warnings: list[str] = []
    for index, raw_candidate in enumerate(raw_candidates):
        try:
            if isinstance(raw_candidate, RecommendationResult):
                candidate = raw_candidate
            else:
                candidate = RecommendationResult.model_validate(raw_candidate)
            candidates.append(candidate)
        except (ValidationError, TypeError, ValueError) as error:
            warnings.append(
                f"검색 후보 {index + 1}의 구조가 올바르지 않아 제외했습니다: {error}"
            )
    return candidates, warnings


def _remove_historical_and_duplicate_candidates(
    candidates: Iterable[RecommendationResult],
    *,
    excluded_urls: set[str],
    excluded_names: set[str],
) -> list[RecommendationResult]:
    result: list[RecommendationResult] = []
    seen_urls = set(excluded_urls)
    seen_names = set(excluded_names)

    for candidate in candidates:
        name_key = normalize_menu_name(candidate.title)
        if candidate.source_url in seen_urls or name_key in seen_names:
            continue
        seen_urls.add(candidate.source_url)
        seen_names.add(name_key)
        result.append(candidate)
    return result


def _build_success_output(
    *,
    selected: RecommendationResult,
    source: str,
    remaining_candidates: list[RecommendationResult],
    previous_urls: list[str],
    previous_names: list[str],
    warnings: list[str],
) -> RetryRecommendationOutput:
    selected_name = normalize_menu_name(selected.title)
    updated_urls = [*previous_urls, selected.source_url]
    updated_names = [*previous_names, selected_name]

    # Do not retain a different URL with the selected menu name in cache.
    remaining = [
        candidate
        for candidate in remaining_candidates
        if candidate.source_url != selected.source_url
        and normalize_menu_name(candidate.title) != selected_name
    ]

    return RetryRecommendationOutput(
        status="SUCCESS",
        recommendation=selected,
        source=source,
        message="이전 추천을 제외한 새로운 레시피를 찾았습니다.",
        previous_recipe_urls=updated_urls,
        normalized_menu_names=updated_names,
        cached_candidates=remaining,
        warnings=warnings,
    )


def retry_recommendation_tool(
    request: RetryRecommendationInput | Mapping[str, Any],
    *,
    search_pipeline: SearchPipeline | None = None,
) -> RetryRecommendationOutput:
    """Return the first valid, non-duplicate cached or newly searched recipe.

    Processing order:

    1. Validate latest UI conditions and normalize session history.
    2. Recheck cached candidates and return the first eligible one.
    3. If none is eligible, invoke the injected recommendation pipeline once.
    4. Return ``NO_NEW_CANDIDATE`` without mutating history when exhausted.

    Pipeline exceptions are raised as ``RetryPipelineError``. Treating an outage
    as ``NO_NEW_CANDIDATE`` would incorrectly tell the user to change conditions.
    """

    if not isinstance(request, RetryRecommendationInput):
        request = RetryRecommendationInput.model_validate(request)

    excluded_urls = set(request.previous_recipe_urls)
    excluded_names = set(request.previous_menu_names)
    valid_ingredients = {
        _normalize_ingredient(item) for item in request.valid_ingredients
    }

    cache = _remove_historical_and_duplicate_candidates(
        request.cached_candidates,
        excluded_urls=excluded_urls,
        excluded_names=excluded_names,
    )
    for candidate in cache:
        if _meets_latest_conditions(
            candidate,
            valid_ingredients=valid_ingredients,
            category=request.category,
        ):
            return _build_success_output(
                selected=candidate,
                source="CACHE",
                remaining_candidates=cache,
                previous_urls=request.previous_recipe_urls,
                previous_names=request.previous_menu_names,
                warnings=[],
            )

    if search_pipeline is None:
        raise RetryPipelineError(
            "사용 가능한 캐시 후보가 없으며 search_pipeline이 설정되지 않았습니다."
        )

    try:
        raw_search_results = search_pipeline(
            valid_ingredients=tuple(request.valid_ingredients),
            category=request.category,
            exclude_urls=frozenset(excluded_urls),
            exclude_menu_names=frozenset(excluded_names),
        )
    except Exception as error:
        raise RetryPipelineError("재추천 검색 파이프라인 실행에 실패했습니다.") from error

    search_results, warnings = _coerce_search_results(raw_search_results)
    new_candidates = _remove_historical_and_duplicate_candidates(
        search_results,
        excluded_urls=excluded_urls,
        excluded_names=excluded_names,
    )

    # Keep old cache entries because they may become valid after a later UI
    # condition change. New results are appended in pipeline ranking order.
    combined_cache = _remove_historical_and_duplicate_candidates(
        [*cache, *new_candidates],
        excluded_urls=excluded_urls,
        excluded_names=excluded_names,
    )

    for candidate in new_candidates:
        if _meets_latest_conditions(
            candidate,
            valid_ingredients=valid_ingredients,
            category=request.category,
        ):
            return _build_success_output(
                selected=candidate,
                source="SEARCH",
                remaining_candidates=combined_cache,
                previous_urls=request.previous_recipe_urls,
                previous_names=request.previous_menu_names,
                warnings=warnings,
            )

    return RetryRecommendationOutput(
        status="NO_NEW_CANDIDATE",
        recommendation=None,
        source=None,
        message=(
            "새로운 추천 후보가 없습니다. 카테고리를 '상관없음'으로 바꾸거나 "
            "식재료를 추가해 주세요."
        ),
        previous_recipe_urls=request.previous_recipe_urls,
        normalized_menu_names=request.previous_menu_names,
        cached_candidates=combined_cache,
        warnings=warnings,
    )


__all__ = [
    "RetryPipelineError",
    "SearchPipeline",
    "normalize_menu_name",
    "normalize_recipe_url",
    "retry_recommendation_tool",
]
