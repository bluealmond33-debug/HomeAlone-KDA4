"""calorie_estimator_tool 단위 테스트 (PRD 19.1).

OpenAI 호출은 전부 mock한다(네트워크·API 키 불필요).
- 기본은 주입 가능한 ``estimate_fn``으로 mock한다.
- 모듈 monkeypatch 경로(``clients.openai_client.estimate_calories_raw``)도 함께 검증한다.
"""

import json

import pytest

from models.schemas import CalorieEstimate
from tools.calorie_estimator_tool import calorie_estimator_tool

MENU = "김치볶음밥"
INGREDIENTS = [
    {"name": "밥", "amount": "200g"},
    {"name": "김치", "amount": "100g"},
    {"name": "계란", "amount": "1개"},
]


def _ok_json(kcal=550, range_min=480, range_max=650, confidence="medium"):
    return json.dumps(
        {
            "estimated_kcal_per_serving": kcal,
            "range_min": range_min,
            "range_max": range_max,
            "confidence": confidence,
            "assumptions": ["식용유 1큰술 사용 가정"],
            "disclaimer": "실제 칼로리는 재료의 양, 제품, 조리 방식에 따라 달라질 수 있습니다.",
        },
        ensure_ascii=False,
    )


class _Recorder:
    """호출 횟수와 페이로드를 기록하는 mock estimate_fn 팩토리."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        if not self._responses:
            raise AssertionError("estimate_fn 호출 횟수 초과")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------------------------
# 칼로리 정상: 검증된 mock JSON → 1인분 값·범위 반환
# ---------------------------------------------------------------------------
def test_calorie_normal_returns_value_and_range():
    fn = _Recorder([_ok_json()])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert isinstance(result, CalorieEstimate)
    assert result.estimated_kcal_per_serving == 550
    assert result.range_min == 480
    assert result.range_max == 650
    assert result.confidence == "medium"
    assert result.assumptions == ["식용유 1큰술 사용 가정"]
    assert len(fn.calls) == 1  # 정상이면 재시도 없음


def test_calorie_normal_sends_only_menu_ingredients_servings():
    fn = _Recorder([_ok_json()])

    calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    payload = json.loads(fn.calls[0])
    assert set(payload.keys()) == {"menu_name", "ingredients", "servings"}
    assert payload["menu_name"] == MENU
    assert payload["servings"] == 2
    for sent, original in zip(payload["ingredients"], INGREDIENTS):
        assert set(sent.keys()) == {"name", "amount"}
        assert sent["name"] == original["name"]
        assert sent["amount"] == original["amount"]


# ---------------------------------------------------------------------------
# 칼로리 역전: min > max → 검증 실패 → 1회 재시도
# ---------------------------------------------------------------------------
def test_calorie_inverted_range_retries_once_then_succeeds():
    inverted = _ok_json(range_min=700, range_max=400)
    fn = _Recorder([inverted, _ok_json()])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert len(fn.calls) == 2  # 재시도가 정확히 1회 발생
    assert result.estimated_kcal_per_serving == 550


def test_calorie_inverted_range_twice_returns_failure():
    inverted = _ok_json(range_min=700, range_max=400)
    fn = _Recorder([inverted, inverted])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert len(fn.calls) == 2  # 1회만 재시도, 그 이상은 없음
    assert result.estimated_kcal_per_serving is None
    assert result.confidence == "low"


# ---------------------------------------------------------------------------
# 필드 누락: 필수 필드 누락 → 폐기 → 재시도 → 여전히 나쁘면 실패 결과
# ---------------------------------------------------------------------------
def test_calorie_missing_field_discards_and_retries():
    missing = json.dumps(
        {
            # estimated_kcal_per_serving 누락
            "range_min": 480,
            "range_max": 650,
            "confidence": "medium",
            "assumptions": [],
        },
        ensure_ascii=False,
    )
    fn = _Recorder([missing, _ok_json()])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert len(fn.calls) == 2
    assert result.estimated_kcal_per_serving == 550


def test_calorie_missing_field_twice_returns_failure():
    missing = json.dumps({"range_min": 480, "range_max": 650}, ensure_ascii=False)
    fn = _Recorder([missing, missing])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert len(fn.calls) == 2
    assert result.estimated_kcal_per_serving is None
    assert result.confidence == "low"
    assert any("칼로리 추정 불가" in note for note in result.assumptions)


def test_calorie_negative_value_returns_failure():
    negative = _ok_json(kcal=-10, range_min=-50, range_max=100)
    fn = _Recorder([negative, negative])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert result.estimated_kcal_per_serving is None
    assert result.confidence == "low"


# ---------------------------------------------------------------------------
# 수량 누락/인분 불명확: 낮은 신뢰도 + 넓은 범위 (모델 응답을 그대로 매핑)
# ---------------------------------------------------------------------------
def test_calorie_missing_amounts_low_confidence_wider_range():
    low_conf = _ok_json(kcal=600, range_min=350, range_max=900, confidence="low")
    fn = _Recorder([low_conf])
    ingredients_no_amount = [
        {"name": "밥", "amount": None},
        {"name": "김치", "amount": None},
    ]

    result = calorie_estimator_tool(MENU, ingredients_no_amount, servings=None, estimate_fn=fn)

    assert result.confidence == "low"
    assert (result.range_max - result.range_min) >= 400  # 넓은 범위
    # 수량/인분 정보가 비어 전달됨을 확인
    payload = json.loads(fn.calls[0])
    assert payload["servings"] is None
    assert all(item["amount"] is None for item in payload["ingredients"])


# ---------------------------------------------------------------------------
# OpenAI 오류/예외: 추정 불가 결과(value=None) 반환, 예외를 올리지 않음
# ---------------------------------------------------------------------------
def test_openai_error_returns_failure_does_not_raise():
    fn = _Recorder([RuntimeError("openai unavailable")])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert isinstance(result, CalorieEstimate)
    assert result.estimated_kcal_per_serving is None
    assert result.confidence == "low"
    assert any("칼로리 추정 불가" in note for note in result.assumptions)
    assert "칼로리 추정 불가" in result.disclaimer
    assert len(fn.calls) == 1  # 예외는 즉시 실패 처리(재시도하지 않음)


def test_invalid_json_returns_failure():
    fn = _Recorder(["this is not json", "still not json"])

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2, estimate_fn=fn)

    assert result.estimated_kcal_per_serving is None
    assert len(fn.calls) == 2


# ---------------------------------------------------------------------------
# 모듈 monkeypatch 경로 검증: 기본 estimate_fn(=estimate_calories_raw)을 patch
# ---------------------------------------------------------------------------
def test_monkeypatched_module_default_path(monkeypatch):
    calls = {"n": 0}

    def fake_raw(payload):
        calls["n"] += 1
        return _ok_json()

    monkeypatch.setattr(
        "tools.calorie_estimator_tool.estimate_calories_raw", fake_raw
    )

    result = calorie_estimator_tool(MENU, INGREDIENTS, servings=2)

    assert result.estimated_kcal_per_serving == 550
    assert calls["n"] == 1
