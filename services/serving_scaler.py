"""Scale recipe ingredient amounts down to a single serving.

만개의레시피 rarely publishes 1-serving recipes, so the service accepts any
serving count and presents amounts on a per-1-serving basis: a 4-serving recipe
has every parseable amount divided by 4, a 3-serving recipe by 3, and so on.

Design notes
------------
- Pure, dependency-light functions so the scraper, service layer, and UI can all
  reuse them and unit tests need no network or API key.
- **Conservative**: only a clean ``"<quantity><unit>"`` amount is scaled. Free
  descriptors (``"약간"``, ``"적당량"``) and compound amounts that contain more
  than one number (``"1큰술 + 1작은술"``) are returned unchanged so we never print
  a misleading quantity.
- Quantities render as cooking-friendly fractions (``"1/4컵"``, ``"1과 1/2큰술"``)
  rather than long decimals.
"""

from __future__ import annotations

import re
from fractions import Fraction

from models.schemas import IngredientAmount, RecipeDetail

# Native Korean counting words that commonly precede a unit (한 개, 두 컵, 반 모...).
_KOREAN_NUMBER_WORDS: dict[str, Fraction] = {
    "반": Fraction(1, 2),
    "한": Fraction(1),
    "두": Fraction(2),
    "세": Fraction(3),
    "석": Fraction(3),
    "네": Fraction(4),
    "넉": Fraction(4),
    "다섯": Fraction(5),
    "여섯": Fraction(6),
    "일곱": Fraction(7),
    "여덟": Fraction(8),
    "아홉": Fraction(9),
    "열": Fraction(10),
}

# A leading numeric quantity: mixed (1과 1/2 · 1 1/2), fraction, decimal, integer.
_NUMERIC_QUANTITY = re.compile(
    r"^\s*(?P<num>"
    r"\d+\s*과\s*\d+\s*/\s*\d+"
    r"|\d+\s+\d+\s*/\s*\d+"
    r"|\d+\s*/\s*\d+"
    r"|\d+\.\d+"
    r"|\d+"
    r")\s*(?P<unit>.*)$"
)

_KOREAN_WORD_QUANTITY = re.compile(
    r"^\s*(?P<word>반|한|두|세|석|네|넉|다섯|여섯|일곱|여덟|아홉|열)\s*(?P<unit>.*)$"
)

_DIGIT = re.compile(r"\d")


def _quantity_from_numeric(token: str) -> Fraction:
    """Convert a matched numeric token to an exact :class:`Fraction`."""
    token = token.strip()
    if "과" in token:
        whole_part, frac_part = token.split("과", 1)
        return Fraction(int(whole_part.strip())) + Fraction(frac_part.replace(" ", ""))
    if "/" in token:
        if " " in token.strip():
            whole_part, frac_part = token.strip().split(None, 1)
            return Fraction(int(whole_part)) + Fraction(frac_part.replace(" ", ""))
        return Fraction(token.replace(" ", ""))
    if "." in token:
        return Fraction(token)
    return Fraction(int(token))


def _parse_leading_quantity(text: str) -> tuple[Fraction, str] | None:
    """Return ``(quantity, trailing_unit)`` if ``text`` starts with a quantity.

    Returns ``None`` for free descriptors with no leading number/number-word.
    """
    numeric = _NUMERIC_QUANTITY.match(text)
    if numeric:
        return _quantity_from_numeric(numeric.group("num")), numeric.group("unit").strip()

    word = _KOREAN_WORD_QUANTITY.match(text)
    if word:
        return _KOREAN_NUMBER_WORDS[word.group("word")], word.group("unit").strip()

    return None


def _format_quantity(value: Fraction) -> str:
    """Render a quantity as an integer, a simple fraction, or a mixed fraction."""
    value = value.limit_denominator(8)
    if value.denominator == 1:
        return str(value.numerator)
    whole, remainder = divmod(value.numerator, value.denominator)
    if whole == 0:
        return f"{remainder}/{value.denominator}"
    return f"{whole}과 {remainder}/{value.denominator}"


def scale_amount(amount: str | None, servings: int) -> str | None:
    """Divide a single amount string by ``servings`` for a per-serving value.

    Unchanged when: ``amount`` is empty, ``servings`` <= 1, the amount has no
    leading quantity (``"약간"``), or the amount contains more than one number
    (a compound amount we cannot safely split).
    """
    if amount is None:
        return None
    text = amount.strip()
    if not text or servings <= 1:
        return amount

    parsed = _parse_leading_quantity(text)
    if parsed is None:
        return amount

    quantity, unit = parsed
    # Refuse compound amounts like "1큰술 + 1작은술": scaling only the first number
    # would print a wrong total, so leave the original untouched.
    if _DIGIT.search(unit):
        return amount

    scaled = _format_quantity(quantity / servings)
    return f"{scaled}{unit}" if unit else scaled


def scale_ingredients(
    ingredients: list[IngredientAmount], servings: int
) -> list[IngredientAmount]:
    """Return a new ingredient list with every amount scaled to one serving."""
    return [
        IngredientAmount(name=item.name, amount=scale_amount(item.amount, servings))
        for item in ingredients
    ]


def scale_recipe_detail_to_one_serving(detail: RecipeDetail) -> RecipeDetail:
    """Return a copy of ``detail`` normalized to a single serving.

    The original serving count is preserved in ``serving_text`` for transparency
    (``"1인분 (원래 4인분 기준 환산)"``). When the recipe is already 1 serving or
    the serving count is unknown, ingredients are returned unchanged.
    """
    servings = detail.servings
    if not servings or servings <= 1:
        return detail.model_copy(deep=True)

    return detail.model_copy(
        update={
            "servings": 1,
            "serving_text": f"1인분 (원래 {servings}인분 기준 환산)",
            "ingredients": scale_ingredients(detail.ingredients, servings),
        },
        deep=True,
    )


__all__ = [
    "scale_amount",
    "scale_ingredients",
    "scale_recipe_detail_to_one_serving",
]
