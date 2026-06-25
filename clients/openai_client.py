"""OpenAI client wrappers for the recipe chatbot.

This module hosts multiple thin OpenAI wrappers that share a single client:

- Calorie estimation (``estimate_calories_raw`` / ``CalorieEstimator``).
- Ingredient classification (``OpenAIIngredientClassifier``).

Each wrapper is intentionally minimal so callers (tools) can depend on a small,
mockable surface and unit tests can monkeypatch the raw call without a real API
key or network access. API keys are read from ``settings`` (server env only) and
are never logged; raw user input is never logged either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import settings


# ---------------------------------------------------------------------------
# Calorie estimation
# ---------------------------------------------------------------------------

# Where the calorie estimation prompt (system instructions) lives.
_CALORIE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "calorie_estimation.md"

# Cap output so a malformed/runaway response cannot consume an unbounded budget.
_CALORIE_MAX_OUTPUT_TOKENS = 500

_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """Return a lazily-created, process-wide OpenAI client.

    Shared by all OpenAI wrappers in this module. The API key is read from
    ``settings.openai_api_key`` (server environment only) and never hardcoded.
    A request timeout is applied so a hung call cannot block the chatbot.
    """
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=float(settings.request_timeout_seconds),
        )
    return _client


def load_calorie_prompt() -> str:
    """Load the calorie estimation system prompt from ``prompts/``."""
    return _CALORIE_PROMPT_PATH.read_text(encoding="utf-8")


def estimate_calories_raw(user_payload: str) -> str:
    """Call the OpenAI Responses API for a calorie estimate and return raw text.

    This is the single thin, injectable seam that ``calorie_estimator_tool``
    depends on. Tests monkeypatch this function (or pass their own callable) so
    no real API key or network is required.

    Args:
        user_payload: A JSON string containing only ``menu_name``, ``ingredients``
            (name + amount) and ``servings``.

    Returns:
        The model's raw response text, expected to be a JSON object string.
    """
    client = get_openai_client()
    # The Responses API requires the word "json" in the input message when
    # ``text.format`` is ``json_object`` (the instructions alone do not satisfy it).
    response = client.responses.create(
        model=settings.openai_model,
        instructions=load_calorie_prompt(),
        input=f"아래 데이터로 1인분 예상 칼로리를 추정해 JSON 객체 하나로만 응답해 주세요.\n{user_payload}",
        text={"format": {"type": "json_object"}},
        max_output_tokens=_CALORIE_MAX_OUTPUT_TOKENS,
    )
    return response.output_text


class CalorieEstimator:
    """Object wrapper around :func:`estimate_calories_raw`.

    Provided for callers/tests that prefer dependency injection over module-level
    monkeypatching. ``calorie_estimator_tool`` uses the function form by default.
    """

    def estimate(self, user_payload: str) -> str:
        return estimate_calories_raw(user_payload)


# ---------------------------------------------------------------------------
# Ingredient classification
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """너는 한국어 식재료 판별기다.
입력된 항목마다 음식 조리에 쓰는 식재료인지 판단한다.
반드시 JSON object만 반환한다.
형식:
{
  "items": [
    {
      "item": "입력 원문",
      "is_valid": true,
      "normalized_name": "표준 재료명",
      "reason": "짧은 이유"
    }
  ]
}
식재료가 아니면 is_valid는 false, normalized_name은 null로 둔다.
브랜드명이나 조리 상태 표현은 가능한 일반 재료명으로 정규화한다.
"""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "valid"}
    return bool(value)


def parse_classification_content(content: str) -> list[dict]:
    payload = json.loads(content)
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("judgments") or payload.get("ingredients")
    else:
        raw_items = None

    if not isinstance(raw_items, list):
        raise ValueError("OpenAI classifier response must include an items list.")

    judgments: list[dict] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        item = str(raw_item.get("item", "")).strip()
        if not item:
            continue

        is_valid = _as_bool(raw_item.get("is_valid", False))
        normalized_name = raw_item.get("normalized_name")
        if normalized_name is not None:
            normalized_name = str(normalized_name).strip() or None

        judgments.append(
            {
                "item": item,
                "is_valid": is_valid,
                "normalized_name": normalized_name if is_valid else None,
                "reason": str(raw_item.get("reason") or ("식재료로 판단됨" if is_valid else "식재료가 아님")),
            }
        )

    return judgments


class OpenAIIngredientClassifier:
    def __init__(self, *, client=None, model: str | None = None):
        self.model = model or settings.openai_model
        self.client = client

    def _client(self):
        if self.client is not None:
            return self.client
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI ingredient classification.")
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.request_timeout_seconds,
        )
        return self.client

    def classify_unknown_items(self, items: list[str]) -> list[dict]:
        if not items:
            return []
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is required for OpenAI ingredient classification.")

        response = self._client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({"items": items}, ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_completion_tokens=700,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenAI classifier returned an empty response.")
        return parse_classification_content(content)
