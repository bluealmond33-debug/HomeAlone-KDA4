"""calorie_estimator_tool — 메뉴/재료/인분 → 1인분 예상 칼로리 추정.

OpenAI에 메뉴명·재료(이름·수량)·인분만 전달하고 구조화된 JSON 추정을 받는다.
음수·역전 범위·필드 누락 결과는 폐기하고 1회만 재시도하며, 최종 실패 시
값을 임의로 만들지 않고 "칼로리 추정 불가" 결과(value=None, 낮은 신뢰도)를 반환한다.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from clients.openai_client import estimate_calories_raw
from models.schemas import CalorieEstimate

# 메뉴/재료를 그대로 노출하지 않는 표준 면책 문구.
_DISCLAIMER = "AI 기반 참고용 추정치입니다. 실제 칼로리는 재료의 양, 제품, 조리 방식에 따라 달라질 수 있습니다."
_FAILURE_DISCLAIMER = "칼로리 추정 불가. " + _DISCLAIMER

_VALID_CONFIDENCE = {"low", "medium", "high"}
_REQUIRED_FIELDS = (
    "estimated_kcal_per_serving",
    "range_min",
    "range_max",
    "confidence",
)


def _build_payload(
    menu_name: str,
    ingredients: list[dict],
    servings: int | None,
) -> str:
    """OpenAI에 보낼 입력을 메뉴명·재료(이름+수량)·인분으로만 한정해 직렬화한다."""
    safe_ingredients = [
        {"name": (item or {}).get("name"), "amount": (item or {}).get("amount")}
        for item in (ingredients or [])
    ]
    return json.dumps(
        {
            "menu_name": menu_name,
            "ingredients": safe_ingredients,
            "servings": servings,
        },
        ensure_ascii=False,
    )


def _parse_and_validate(raw: str) -> CalorieEstimate | None:
    """원시 응답을 파싱·검증한다. 유효하면 CalorieEstimate, 아니면 None."""
    try:
        data: Any = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # 필수 필드 누락 → 폐기.
    for field in _REQUIRED_FIELDS:
        if data.get(field) is None:
            return None

    kcal = data["estimated_kcal_per_serving"]
    range_min = data["range_min"]
    range_max = data["range_max"]
    confidence = data["confidence"]

    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (kcal, range_min, range_max)):
        return None

    # 음수·비정상 범위 → 폐기.
    if kcal < 0 or range_min < 0 or range_max < 0:
        return None
    if range_min > range_max:
        return None
    if not (range_min <= kcal <= range_max):
        return None

    if confidence not in _VALID_CONFIDENCE:
        return None

    assumptions = data.get("assumptions") or []
    if not isinstance(assumptions, list):
        assumptions = []
    assumptions = [str(item) for item in assumptions]

    disclaimer = data.get("disclaimer") or _DISCLAIMER

    return CalorieEstimate(
        estimated_kcal_per_serving=kcal,
        range_min=range_min,
        range_max=range_max,
        confidence=confidence,  # type: ignore[arg-type]
        assumptions=assumptions,
        disclaimer=str(disclaimer),
    )


def _failure_result(reason: str) -> CalorieEstimate:
    """값을 만들지 않고 추정 불가를 명시하는 결과."""
    return CalorieEstimate(
        estimated_kcal_per_serving=None,
        range_min=None,
        range_max=None,
        confidence="low",
        assumptions=[f"칼로리 추정 불가: {reason}"],
        disclaimer=_FAILURE_DISCLAIMER,
    )


def calorie_estimator_tool(
    menu_name: str,
    ingredients: list[dict] | None = None,
    servings: int | None = None,
    *,
    estimate_fn: Callable[[str], str] | None = None,
) -> CalorieEstimate:
    """메뉴/재료/인분으로 1인분 예상 칼로리를 추정한다.

    Args:
        menu_name: 메뉴명.
        ingredients: ``{"name": str, "amount": str | None}`` 형태의 재료 목록.
        servings: 인분 수. 없거나 불명확하면 낮은 신뢰도·넓은 범위가 기대된다.
        estimate_fn: OpenAI 원시 호출 함수(주입 가능). 테스트는 이를 mock한다.

    Returns:
        검증을 통과한 ``CalorieEstimate``. 음수·역전 범위·필드 누락은 폐기 후
        1회 재시도하며, 최종 실패나 OpenAI 오류 시 값=None인 추정 불가 결과를 반환한다
        (예외를 올리지 않는다).
    """
    # 기본값을 호출 시점에 해석해 monkeypatch(모듈 수준 estimate_calories_raw)가 반영되게 한다.
    call_estimate = estimate_fn if estimate_fn is not None else estimate_calories_raw

    payload = _build_payload(menu_name, ingredients or [], servings)

    last_reason = "유효한 추정 결과 없음"
    # 최초 호출 + 검증 실패 시 1회만 재시도 (총 2회 시도).
    for _ in range(2):
        try:
            raw = call_estimate(payload)
        except Exception:  # OpenAI 오류/네트워크/SDK 예외 등 → 값 위조 없이 실패 처리.
            return _failure_result("OpenAI 호출 오류")

        result = _parse_and_validate(raw)
        if result is not None:
            return result
        last_reason = "구조 검증 실패"

    return _failure_result(last_reason)
