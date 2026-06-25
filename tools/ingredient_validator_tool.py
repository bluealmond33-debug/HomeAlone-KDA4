from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from clients.openai_client import OpenAIIngredientClassifier
from models.schemas import ExcludedItem, IngredientValidationResult

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_TOTAL_CHARS = 300
MAX_ITEMS = 20
SEPARATOR_RE = re.compile(r"[,，\n]+")


class IngredientClassifier(Protocol):
    def classify_unknown_items(self, items: list[str]) -> list[dict]: ...


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_known_ingredients() -> set[str]:
    return set(_load_json(DATA_DIR / "known_ingredients.json"))


def load_aliases() -> dict[str, str]:
    return _load_json(DATA_DIR / "ingredient_aliases.json")


def normalize_item(item: str, aliases: dict[str, str]) -> str:
    collapsed = " ".join((item or "").strip().split())
    return aliases.get(collapsed, collapsed)


def parse_ingredient_input(payload: str | list[str] | dict) -> list[str]:
    if isinstance(payload, dict):
        if "ingredients" in payload:
            raw_items = payload["ingredients"]
            if not isinstance(raw_items, list):
                raise ValueError("ingredients는 문자열 목록이어야 합니다.")
            return [str(item) for item in raw_items]
        if "ingredients_text" in payload:
            payload = payload["ingredients_text"]
        else:
            raise ValueError("ingredients 또는 ingredients_text 입력이 필요합니다.")

    if isinstance(payload, list):
        return [str(item) for item in payload]

    if payload is None:
        raise ValueError("식재료를 입력해주세요.")

    if not isinstance(payload, str):
        raise ValueError("식재료 입력 형식이 올바르지 않습니다.")

    return [token for token in SEPARATOR_RE.split(payload) if token.strip()]


def ingredient_validator_tool(
    payload: str | list[str] | dict,
    *,
    classifier: IngredientClassifier | None = None,
) -> IngredientValidationResult:
    raw_items = parse_ingredient_input(payload)
    aliases = load_aliases()
    known_ingredients = load_known_ingredients()

    raw_total_chars = sum(len((item or "").strip()) for item in raw_items)
    if raw_total_chars == 0:
        raise ValueError("식재료를 입력해주세요.")
    if raw_total_chars > MAX_TOTAL_CHARS:
        raise ValueError("식재료 입력은 전체 300자 이하여야 합니다.")

    normalized_items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        normalized = normalize_item(raw_item, aliases)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_items.append(normalized)

    if not normalized_items:
        raise ValueError("식재료를 입력해주세요.")
    if len(normalized_items) > MAX_ITEMS:
        raise ValueError("식재료는 최대 20개까지 입력할 수 있습니다.")

    valid_ingredients: list[str] = []
    excluded_items: list[ExcludedItem] = []
    unknown_items: list[str] = []

    for item in normalized_items:
        if item in known_ingredients:
            valid_ingredients.append(item)
        else:
            unknown_items.append(item)

    warnings: list[str] = []
    if unknown_items:
        active_classifier = classifier or OpenAIIngredientClassifier()
        try:
            judgments = active_classifier.classify_unknown_items(unknown_items)
        except Exception:
            warnings.append("일부 재료는 현재 판별할 수 없어 보류했어요.")
            judgments = [
                {"item": item, "is_valid": False, "reason": "판별 보류"}
                for item in unknown_items
            ]

        for judgment in judgments:
            item = normalize_item(str(judgment.get("item", "")), aliases)
            if not item:
                continue
            if judgment.get("is_valid"):
                normalized_name = normalize_item(str(judgment.get("normalized_name") or item), aliases)
                if normalized_name not in seen:
                    seen.add(normalized_name)
                    valid_ingredients.append(normalized_name)
                elif normalized_name not in valid_ingredients:
                    valid_ingredients.append(normalized_name)
            else:
                excluded_items.append(
                    ExcludedItem(
                        item=item,
                        reason=str(judgment.get("reason") or "판별 보류"),
                    )
                )

    return IngredientValidationResult(
        valid_ingredients=valid_ingredients,
        excluded_items=excluded_items,
        warnings=warnings,
    )
