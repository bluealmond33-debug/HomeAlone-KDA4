from app import (
    INITIAL_EXCLUDE_BOXES,
    INITIAL_INGREDIENT_BOXES,
    MAX_EXCLUDE_BOXES,
    MAX_INGREDIENT_BOXES,
    add_exclude_box,
    add_ingredient_box,
    build_category_status,
    collect_ingredient_values,
    get_exclude_placeholder,
    get_ingredient_placeholder,
    reset_state,
)


def test_collect_ingredient_values_keeps_one_box_one_item_without_comma_split():
    result = collect_ingredient_values(["김치, 밥", "", " 계란 "])

    assert result == ["김치, 밥", "계란"]


def test_default_ingredient_boxes_start_with_three_distinct_placeholders():
    placeholders = [get_ingredient_placeholder(index) for index in range(INITIAL_INGREDIENT_BOXES)]

    assert INITIAL_INGREDIENT_BOXES == 3
    assert placeholders == [
        "식재료만 입력해주세요(예시: 김치)",
        "식재료만 입력해주세요(예시: 두부)",
        "식재료만 입력해주세요(예시: 계란)",
    ]


def test_default_exclude_box_starts_with_onion_placeholder():
    placeholders = [get_exclude_placeholder(index) for index in range(INITIAL_EXCLUDE_BOXES)]

    assert INITIAL_EXCLUDE_BOXES == 1
    assert placeholders == ["추천에서 제외할 재료(예시: 양파)"]


def test_add_ingredient_box_reveals_one_more_input():
    updates = add_ingredient_box(1)

    assert updates[0] == 2
    assert updates[2]["visible"] is True
    assert updates[3]["visible"] is True
    assert updates[4]["visible"] is False


def test_add_ingredient_box_disables_button_at_limit():
    updates = add_ingredient_box(MAX_INGREDIENT_BOXES)

    assert updates[0] == MAX_INGREDIENT_BOXES
    assert updates[1]["interactive"] is False


def test_add_ingredient_box_returns_ready_status_message():
    updates = add_ingredient_box(1)

    assert "재료 칸 2개 준비 완료" in updates[-1]


def test_add_exclude_box_reveals_one_more_input():
    updates = add_exclude_box(1)

    assert updates[0] == 2
    assert updates[2]["visible"] is True
    assert updates[3]["visible"] is True
    assert updates[4]["visible"] is False


def test_add_exclude_box_disables_button_at_limit():
    updates = add_exclude_box(MAX_EXCLUDE_BOXES)

    assert updates[0] == MAX_EXCLUDE_BOXES
    assert updates[1]["interactive"] is False


def test_add_exclude_box_returns_ready_status_message():
    updates = add_exclude_box(1)

    assert "제외 재료 칸 2개 준비 완료" in updates[-1]


def test_reset_state_restores_three_visible_ingredient_boxes():
    updates = reset_state()

    assert updates[0]["visible"] is True
    assert updates[1]["visible"] is True
    assert updates[2]["visible"] is True
    assert updates[3]["visible"] is False
    first_exclude_index = MAX_INGREDIENT_BOXES
    assert updates[first_exclude_index]["visible"] is True
    assert updates[first_exclude_index + 1]["visible"] is False
    assert updates[-4] == INITIAL_INGREDIENT_BOXES
    assert updates[-2] == INITIAL_EXCLUDE_BOXES


def test_build_category_status_mentions_category_and_ingredients():
    result = build_category_status("김치", " 두부 ", "", "한식")

    assert "한식 모드 설정 완료" in result
    assert "김치, 두부" in result
    assert "추천 시작 준비 완료" in result
