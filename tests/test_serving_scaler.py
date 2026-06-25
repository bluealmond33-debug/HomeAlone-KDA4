from __future__ import annotations

import pytest

from models.schemas import IngredientAmount, RecipeDetail
from services.serving_scaler import (
    scale_amount,
    scale_ingredients,
    scale_recipe_detail_to_one_serving,
)


@pytest.mark.parametrize(
    ("amount", "servings", "expected"),
    [
        # Metric weights/volumes divide cleanly.
        ("200g", 4, "50g"),
        ("100g", 2, "50g"),
        ("500ml", 4, "125ml"),
        # Large non-whole quantities round to an integer instead of "33과 1/3g".
        ("100g", 3, "33g"),
        # Counts and cups render as cooking-friendly fractions.
        ("1컵", 4, "1/4컵"),
        ("2개", 2, "1개"),
        ("1개", 2, "1/2개"),
        ("1.5큰술", 3, "1/2큰술"),
        # Fraction and mixed-number inputs.
        ("1/2개", 2, "1/4개"),
        ("1 1/2컵", 3, "1/2컵"),
        ("1과 1/2컵", 3, "1/2컵"),
        # Native Korean number words.
        ("두개", 2, "1개"),
        ("한컵", 4, "1/4컵"),
        ("반모", 2, "1/4모"),
    ],
)
def test_scale_amount_scales_numeric_quantities(amount, servings, expected):
    assert scale_amount(amount, servings) == expected


@pytest.mark.parametrize(
    ("amount", "servings"),
    [
        # Free descriptors cannot be divided.
        ("약간", 4),
        ("적당량", 3),
        ("조금", 2),
        ("소금 약간", 4),
        # Compound amounts hold more than one number -> too risky to split.
        ("1큰술 + 1작은술", 2),
        ("2~3개", 2),
    ],
)
def test_scale_amount_leaves_unparseable_amounts_unchanged(amount, servings):
    assert scale_amount(amount, servings) == amount


def test_scale_amount_passthrough_for_single_serving_and_none():
    assert scale_amount("200g", 1) == "200g"
    assert scale_amount(None, 4) is None
    assert scale_amount("", 4) == ""


def test_scale_ingredients_returns_new_scaled_list():
    ingredients = [
        IngredientAmount(name="밥", amount="200g"),
        IngredientAmount(name="소금", amount="약간"),
    ]

    scaled = scale_ingredients(ingredients, 4)

    assert [(i.name, i.amount) for i in scaled] == [("밥", "50g"), ("소금", "약간")]
    # Original list is untouched.
    assert ingredients[0].amount == "200g"


def _detail(servings, ingredients):
    return RecipeDetail(
        title="김치볶음밥",
        source_url="https://www.10000recipe.com/recipe/123",
        servings=servings,
        serving_text=f"{servings}인분" if servings else None,
        cooking_time_minutes=20,
        difficulty="초급",
        ingredients=[IngredientAmount(**i) for i in ingredients],
    )


def test_scale_recipe_detail_normalizes_to_one_serving():
    detail = _detail(4, [{"name": "밥", "amount": "400g"}, {"name": "김치", "amount": "1컵"}])

    scaled = scale_recipe_detail_to_one_serving(detail)

    assert scaled.servings == 1
    assert "원래 4인분" in scaled.serving_text
    assert [(i.name, i.amount) for i in scaled.ingredients] == [
        ("밥", "100g"),
        ("김치", "1/4컵"),
    ]
    # Source detail is unmodified.
    assert detail.servings == 4


def test_scale_recipe_detail_passthrough_for_one_or_unknown_servings():
    one = _detail(1, [{"name": "밥", "amount": "200g"}])
    assert scale_recipe_detail_to_one_serving(one).ingredients[0].amount == "200g"

    unknown = _detail(None, [{"name": "밥", "amount": "200g"}])
    assert scale_recipe_detail_to_one_serving(unknown).ingredients[0].amount == "200g"
