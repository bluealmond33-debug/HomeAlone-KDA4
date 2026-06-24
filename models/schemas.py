"""Pydantic contracts used by ``retry_recommendation_tool``.

The models deliberately contain only fields required to decide whether a cached
or newly searched recipe can be returned. Other tools may extend
``RecommendationResult`` with calorie or presentation fields later.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Category = Literal["한식", "중식", "일식", "양식", "분식", "상관없음"]
RetryStatus = Literal["SUCCESS", "NO_NEW_CANDIDATE"]
RecommendationSource = Literal["CACHE", "SEARCH"]


class RecommendationResult(BaseModel):
    """A ranked recipe that has passed the detail-scraping stage."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=100)
    source_url: str
    category: Category
    servings: int = Field(ge=1)
    cooking_time_minutes: int = Field(ge=1)
    difficulty: str = Field(min_length=1, max_length=20)
    ingredient_names: list[str] = Field(min_length=1)
    recommendation_reason: str | None = Field(default=None, max_length=500)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        # Local import avoids a model -> tool module dependency at import time.
        from tools.retry_recommendation_tool import normalize_recipe_url

        return normalize_recipe_url(value)

    @field_validator("ingredient_names")
    @classmethod
    def clean_ingredient_names(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if not item:
                continue
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(item)
        if not cleaned:
            raise ValueError("ingredient_names에는 빈 값이 아닌 재료가 필요합니다.")
        return cleaned


class RetryRecommendationInput(BaseModel):
    """Latest UI conditions plus the current session's retry state.

    ``previous_menu_names`` and ``cached_candidates`` have defaults so the PRD's
    minimal JSON input remains valid. In Gradio, both should be populated from
    the current session's ``gr.State``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    valid_ingredients: list[str] = Field(min_length=1, max_length=5)
    category: Category
    previous_recipe_urls: list[str] = Field(default_factory=list)
    previous_menu_names: list[str] = Field(default_factory=list)
    cached_candidates: list[RecommendationResult] = Field(default_factory=list)

    @field_validator("valid_ingredients")
    @classmethod
    def clean_valid_ingredients(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if not item:
                continue
            if len(item) > 30:
                raise ValueError("식재료는 항목당 최대 30자입니다.")
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                cleaned.append(item)
        if not cleaned:
            raise ValueError("유효한 식재료가 1개 이상 필요합니다.")
        return cleaned

    @field_validator("previous_recipe_urls")
    @classmethod
    def normalize_previous_urls(cls, values: list[str]) -> list[str]:
        from tools.retry_recommendation_tool import normalize_recipe_url

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            url = normalize_recipe_url(value)
            if url not in seen:
                seen.add(url)
                normalized.append(url)
        return normalized

    @field_validator("previous_menu_names")
    @classmethod
    def normalize_previous_names(cls, values: list[str]) -> list[str]:
        from tools.retry_recommendation_tool import normalize_menu_name

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            name = normalize_menu_name(value)
            if name and name not in seen:
                seen.add(name)
                normalized.append(name)
        return normalized

    @model_validator(mode="after")
    def enforce_unique_ingredient_limit(self) -> "RetryRecommendationInput":
        if len(self.valid_ingredients) > 5:
            raise ValueError("식재료는 최대 5개까지 입력할 수 있습니다.")
        return self


class RetryRecommendationOutput(BaseModel):
    """Result and the complete state that must be written back to ``gr.State``."""

    model_config = ConfigDict(extra="forbid")

    status: RetryStatus
    recommendation: RecommendationResult | None = None
    source: RecommendationSource | None = None
    message: str
    previous_recipe_urls: list[str]
    normalized_menu_names: list[str]
    cached_candidates: list[RecommendationResult]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_payload(self) -> "RetryRecommendationOutput":
        if self.status == "SUCCESS":
            if self.recommendation is None or self.source is None:
                raise ValueError("SUCCESS에는 recommendation과 source가 필요합니다.")
        elif self.recommendation is not None or self.source is not None:
            raise ValueError("NO_NEW_CANDIDATE에는 추천 결과를 포함할 수 없습니다.")
        return self
