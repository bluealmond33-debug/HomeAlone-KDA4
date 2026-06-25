from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from config import settings


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
