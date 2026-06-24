from datetime import datetime
from typing import Literal

from pydantic import BaseModel, HttpUrl, Field


class ExcludedItem(BaseModel):
    item: str
    reason: str


class IngredientAmount(BaseModel):
    name: str
    amount: str | None = None


class IngredientValidationResult(BaseModel):
    valid_ingredients: list[str]
    excluded_items: list[ExcludedItem]
    warnings: list[str] = Field(default_factory=list)


class RecipeCandidate(BaseModel):
    title: str
    url: HttpUrl
    search_score: float | None = None


class RecipeDetail(BaseModel):
    title: str
    source_url: HttpUrl
    image_url: HttpUrl | None = None
    servings: int | None = None
    serving_text: str | None = None
    cooking_time_minutes: int | None = None
    cooking_time_text: str | None = None
    difficulty: str | None = None
    ingredients: list[IngredientAmount] = Field(default_factory=list)
    cooking_steps: list[str] = Field(default_factory=list)
    scraped_at: datetime | None = None


class CalorieEstimate(BaseModel):
    estimated_kcal_per_serving: int | None = None
    range_min: int | None = None
    range_max: int | None = None
    confidence: Literal["low", "medium", "high"] = "low"
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "실제 칼로리는 재료와 조리 방식에 따라 달라질 수 있습니다."


class RecommendationState(BaseModel):
    previous_recipe_urls: list[str] = Field(default_factory=list)
    normalized_menu_names: list[str] = Field(default_factory=list)
    cached_candidates: list[RecipeDetail] = Field(default_factory=list)
    last_valid_ingredients: list[str] = Field(default_factory=list)
    last_category: str | None = None
