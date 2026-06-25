"""RecommendationService — 재료/카테고리 입력을 추천 카드까지 잇는 결정적 파이프라인.

고정 순서(PRD 9.1):
1. ingredient_validator_tool — 유효 재료 판별
2. recipe_search_tool — 만개의레시피 후보 URL 검색
3. recipe_detail_scraper_tool — 후보별 상세 정보 스크래핑
4. 조건 필터(30분 이내·초급/아무나) + 보유 재료 일치 정렬 — 인분은 거르지 않음
5. serving_scaler — 선택된 레시피를 1인분 기준으로 환산
6. calorie_estimator_tool — 1인분 예상 칼로리(키 없거나 실패 시 '추정 불가')

각 단계는 주입 가능해 단위 테스트에서 네트워크/OpenAI 없이 검증할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from models.schemas import CalorieEstimate, RecipeDetail
from services.serving_scaler import scale_recipe_detail_to_one_serving
from tools.calorie_estimator_tool import calorie_estimator_tool
from tools.ingredient_validator_tool import ingredient_validator_tool
from tools.recipe_detail_scraper_tool import recipe_detail_scraper_tool
from tools.recipe_search_tool import recipe_search_tool
from tools.retry_recommendation_tool import normalize_recipe_url

ALLOWED_DIFFICULTIES = frozenset({"초급", "아무나"})
MAX_COOKING_MINUTES = 30


@dataclass
class RecommendationOutcome:
    """추천 결과와 화면 표시에 필요한 모든 값."""

    status: str  # SUCCESS | NO_VALID_INGREDIENT | NO_CANDIDATE | NO_MATCH | ERROR
    message: str
    card_markdown: str = ""
    recipe_url: str | None = None
    detail: RecipeDetail | None = None  # 1인분 환산본
    calorie: CalorieEstimate | None = None
    valid_ingredients: list[str] = field(default_factory=list)
    excluded_ingredients: list[str] = field(default_factory=list)
    excluded_items: list[Any] = field(default_factory=list)
    matched_ingredients: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return "".join((text or "").casefold().split())


class RecommendationService:
    def __init__(
        self,
        *,
        validator_fn: Callable = ingredient_validator_tool,
        search_fn: Callable = recipe_search_tool,
        scrape_fn: Callable = recipe_detail_scraper_tool,
        calorie_fn: Callable = calorie_estimator_tool,
        max_scrape: int = 5,
    ) -> None:
        self.validator_fn = validator_fn
        self.search_fn = search_fn
        self.scrape_fn = scrape_fn
        self.calorie_fn = calorie_fn
        self.max_scrape = max_scrape

    # -- pipeline ---------------------------------------------------------

    def recommend(
        self,
        ingredients: list[str],
        category: str = "상관없음",
        *,
        exclude_urls: list[str] | tuple[str, ...] = (),
        exclude_ingredients: list[str] | tuple[str, ...] = (),
    ) -> RecommendationOutcome:
        ingredients = [i.strip() for i in ingredients if i and i.strip()]
        excluded_ingredients = [
            i.strip() for i in exclude_ingredients if i and i.strip()
        ]

        valid, excluded = self._validate(ingredients)
        if not valid:
            return RecommendationOutcome(
                status="NO_VALID_INGREDIENT",
                message="유효한 식재료가 없어요. 재료를 다시 입력해 주세요.",
                excluded_ingredients=excluded_ingredients,
                excluded_items=excluded,
            )

        try:
            candidates = self.search_fn(
                valid,
                category,
                exclude_urls=tuple(exclude_urls),
                max_results=self.max_scrape * 2,
            )
        except Exception as error:  # 네트워크/검색 실패는 값 위조 없이 안내.
            return RecommendationOutcome(
                status="ERROR",
                message=f"레시피 검색에 실패했어요. 잠시 후 다시 시도해 주세요. ({error})",
                valid_ingredients=valid,
                excluded_ingredients=excluded_ingredients,
                excluded_items=excluded,
            )

        if not candidates:
            return RecommendationOutcome(
                status="NO_CANDIDATE",
                message="검색 결과가 없어요. 카테고리를 '상관없음'으로 바꾸거나 재료를 더 넣어보세요.",
                valid_ingredients=valid,
                excluded_ingredients=excluded_ingredients,
                excluded_items=excluded,
            )

        excluded_keys: set[str] = set()
        for raw in exclude_urls:
            try:
                excluded_keys.add(normalize_recipe_url(raw))
            except ValueError:
                continue

        passing = self._scrape_and_filter(
            candidates,
            valid,
            excluded_keys,
            excluded_ingredients,
        )
        if not passing:
            exclude_hint = (
                f" 제외 재료({', '.join(excluded_ingredients)})가 들어간 레시피도 제외했어요."
                if excluded_ingredients
                else ""
            )
            return RecommendationOutcome(
                status="NO_MATCH",
                message=(
                    "조건(30분 이내·초급/아무나)에 맞는 레시피를 찾지 못했어요. "
                    "재료를 바꾸거나 카테고리를 완화해 보세요."
                    f"{exclude_hint}"
                ),
                valid_ingredients=valid,
                excluded_ingredients=excluded_ingredients,
                excluded_items=excluded,
            )

        # 보유 재료 일치 수 우선, 동점이면 조리시간이 짧은 순.
        match_count, detail = max(
            passing, key=lambda item: (item[0], -(item[1].cooking_time_minutes or 999))
        )
        scaled = scale_recipe_detail_to_one_serving(detail)
        calorie = self._estimate_calories(scaled)
        matched = self._matched_ingredients(detail, valid)

        return RecommendationOutcome(
            status="SUCCESS",
            message="추천을 찾았어요!",
            card_markdown=self._render_card(
                scaled,
                calorie,
                valid,
                matched,
                excluded_ingredients,
            ),
            recipe_url=str(detail.source_url),
            detail=scaled,
            calorie=calorie,
            valid_ingredients=valid,
            excluded_ingredients=excluded_ingredients,
            excluded_items=excluded,
            matched_ingredients=matched,
        )

    # -- steps ------------------------------------------------------------

    def _validate(self, ingredients: list[str]) -> tuple[list[str], list[Any]]:
        try:
            result = self.validator_fn(
                {"ingredients": ingredients}, persist_new_ingredients=False
            )
            return list(result.valid_ingredients), list(result.excluded_items)
        except Exception:
            # 검증기 자체 실패 시 입력 재료를 그대로 사용해 데모가 멈추지 않게 한다.
            return ingredients, []

    def _scrape_and_filter(
        self,
        candidates,
        valid: list[str],
        excluded_keys: set[str] = frozenset(),
        excluded_ingredients: list[str] | tuple[str, ...] = (),
    ) -> list[tuple[int, RecipeDetail]]:
        passing: list[tuple[int, RecipeDetail]] = []
        for candidate in candidates[: self.max_scrape]:
            # 재추천: 이미 추천한 URL은 건너뛴다(검색이 못 거른 경우 대비).
            try:
                if normalize_recipe_url(str(candidate.url)) in excluded_keys:
                    continue
            except ValueError:
                continue
            try:
                detail = self.scrape_fn(str(candidate.url), require_complete=True)
            except Exception:
                continue
            if detail is None:
                continue
            if (detail.cooking_time_minutes or 999) > MAX_COOKING_MINUTES:
                continue
            if detail.difficulty not in ALLOWED_DIFFICULTIES:
                continue
            if self._has_excluded_ingredient(detail, excluded_ingredients):
                continue
            passing.append((len(self._matched_ingredients(detail, valid)), detail))
        return passing

    def _estimate_calories(self, detail: RecipeDetail) -> CalorieEstimate | None:
        try:
            return self.calorie_fn(
                detail.title,
                [{"name": i.name, "amount": i.amount} for i in detail.ingredients],
                detail.servings,
            )
        except Exception:
            return None

    @staticmethod
    def _matched_ingredients(detail: RecipeDetail, valid: list[str]) -> list[str]:
        recipe_names = [_norm(i.name) for i in detail.ingredients]
        matched = []
        for item in valid:
            key = _norm(item)
            if any(key and (key in name or name in key) for name in recipe_names):
                matched.append(item)
        return matched

    @staticmethod
    def _has_excluded_ingredient(
        detail: RecipeDetail,
        excluded_ingredients: list[str] | tuple[str, ...],
    ) -> bool:
        recipe_names = [_norm(i.name) for i in detail.ingredients]
        for item in excluded_ingredients:
            key = _norm(item)
            if not key:
                continue
            if len(key) == 1:
                if key in recipe_names:
                    return True
                continue
            if any(key in name for name in recipe_names):
                return True
        return False

    # -- rendering --------------------------------------------------------

    @staticmethod
    def _render_card(
        detail: RecipeDetail,
        calorie: CalorieEstimate | None,
        valid: list[str],
        matched: list[str],
        excluded_ingredients: list[str] | tuple[str, ...] = (),
    ) -> str:
        lines = [
            f"## 🍳 {detail.title}",
            f"- 출처: 만개의레시피 ([원본 링크]({detail.source_url}))",
            f"- 인분: {detail.serving_text or '1인분'}",
            f"- 조리시간: {detail.cooking_time_minutes}분 이내",
            f"- 난이도: {detail.difficulty}",
            f"- 활용 가능한 보유 재료: {', '.join(matched) if matched else '없음'}",
            f"- 제외한 재료: {', '.join(excluded_ingredients) if excluded_ingredients else '없음'}",
            "",
            "### 재료 (1인분 기준 환산)",
        ]
        lines += [
            f"- {item.name}: {item.amount or '적당량'}" for item in detail.ingredients
        ] or ["- (재료 정보 없음)"]

        lines.append("")
        lines.append("### 1인분 예상 칼로리")
        if calorie and calorie.estimated_kcal_per_serving is not None:
            lines.append(
                f"- 약 {calorie.estimated_kcal_per_serving} kcal "
                f"(범위 {calorie.range_min}~{calorie.range_max}, 신뢰도 {calorie.confidence})"
            )
        else:
            lines.append("- 칼로리 추정 불가 (OpenAI 키 미설정 또는 추정 실패)")
        if calorie:
            lines.append(f"- {calorie.disclaimer}")
        return "\n".join(lines)


__all__ = ["RecommendationService", "RecommendationOutcome"]
