import json

import pytest

from tools.ingredient_validator_tool import ingredient_validator_tool, parse_ingredient_input


class FakeClassifier:
    def __init__(self, response: list[dict] | None = None, should_fail: bool = False):
        self.response = response or []
        self.should_fail = should_fail
        self.calls = []

    def classify_unknown_items(self, items: list[str]) -> list[dict]:
        self.calls.append(items)
        if self.should_fail:
            raise RuntimeError("boom")
        return self.response


def test_parse_ingredient_input_supports_text_and_list():
    assert parse_ingredient_input("김치, 밥\n계란") == ["김치", " 밥", "계란"]
    assert parse_ingredient_input(["김치", "밥"]) == ["김치", "밥"]


def test_ingredient_validator_applies_alias_and_deduplicates_known_ingredients():
    result = ingredient_validator_tool("계란, 달걀, 김치")

    assert result.valid_ingredients == ["계란", "김치"]
    assert result.excluded_items == []
    assert result.warnings == []


def test_ingredient_validator_uses_classifier_for_unknown_items():
    classifier = FakeClassifier(
        response=[
            {"item": "테스트재료", "is_valid": True, "normalized_name": "테스트재료"},
            {"item": "핸드폰", "is_valid": False, "reason": "식재료가 아님"},
        ]
    )

    result = ingredient_validator_tool(
        {"ingredients": ["김치", "테스트재료", "핸드폰"]},
        classifier=classifier,
    )

    assert classifier.calls == [["테스트재료", "핸드폰"]]
    assert result.valid_ingredients == ["김치", "테스트재료"]
    assert [(item.item, item.reason) for item in result.excluded_items] == [("핸드폰", "식재료가 아님")]
    assert result.warnings == []


def test_ingredient_validator_uses_known_cache_and_aliases_before_classifier():
    classifier = FakeClassifier()

    result = ingredient_validator_tool(
        {"ingredients": ["두부", "밥", "케찹"]},
        classifier=classifier,
    )

    assert classifier.calls == []
    assert result.valid_ingredients == ["두부", "쌀", "케첩"]
    assert result.excluded_items == []
    assert result.warnings == []


def test_ingredient_validator_persists_new_valid_classifier_results(tmp_path):
    (tmp_path / "known_ingredients.json").write_text(
        json.dumps(["김치"], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "ingredient_aliases.json").write_text(
        json.dumps({}, ensure_ascii=False),
        encoding="utf-8",
    )
    classifier = FakeClassifier(
        response=[
            {"item": "초당옥수수", "is_valid": True, "normalized_name": "옥수수"},
            {"item": "노트북", "is_valid": False, "reason": "식재료가 아님"},
        ]
    )

    result = ingredient_validator_tool(
        {"ingredients": ["김치", "초당옥수수", "노트북"]},
        classifier=classifier,
        persist_new_ingredients=True,
        data_dir=tmp_path,
    )

    known = json.loads((tmp_path / "known_ingredients.json").read_text(encoding="utf-8"))
    aliases = json.loads((tmp_path / "ingredient_aliases.json").read_text(encoding="utf-8"))
    assert result.valid_ingredients == ["김치", "옥수수"]
    assert [(item.item, item.reason) for item in result.excluded_items] == [("노트북", "식재료가 아님")]
    assert "옥수수" in known
    assert aliases["초당옥수수"] == "옥수수"


def test_ingredient_validator_does_not_persist_new_results_without_flag(tmp_path):
    (tmp_path / "known_ingredients.json").write_text(
        json.dumps(["김치"], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "ingredient_aliases.json").write_text(
        json.dumps({}, ensure_ascii=False),
        encoding="utf-8",
    )
    classifier = FakeClassifier(
        response=[
            {"item": "초당옥수수", "is_valid": True, "normalized_name": "옥수수"},
        ]
    )

    result = ingredient_validator_tool(
        {"ingredients": ["초당옥수수"]},
        classifier=classifier,
        data_dir=tmp_path,
    )

    known = json.loads((tmp_path / "known_ingredients.json").read_text(encoding="utf-8"))
    aliases = json.loads((tmp_path / "ingredient_aliases.json").read_text(encoding="utf-8"))
    assert result.valid_ingredients == ["옥수수"]
    assert known == ["김치"]
    assert aliases == {}


def test_ingredient_validator_falls_back_to_hold_when_classifier_fails():
    classifier = FakeClassifier(should_fail=True)

    result = ingredient_validator_tool(
        {"ingredients": ["김치", "핸드폰"]},
        classifier=classifier,
    )

    assert result.valid_ingredients == ["김치"]
    assert [(item.item, item.reason) for item in result.excluded_items] == [("핸드폰", "판별 보류")]
    assert result.warnings == ["일부 재료는 현재 판별할 수 없어 보류했어요."]


def test_ingredient_validator_rejects_more_than_twenty_items():
    too_many_items = {"ingredients": [f"재료{i}" for i in range(1, 22)]}

    with pytest.raises(ValueError, match="최대 20개"):
        ingredient_validator_tool(too_many_items)


def test_ingredient_validator_rejects_more_than_three_hundred_chars():
    with pytest.raises(ValueError, match="300자"):
        ingredient_validator_tool({"ingredients": ["가" * 301]})
