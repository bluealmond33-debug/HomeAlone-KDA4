from app import MAX_INGREDIENT_BOXES, add_ingredient_box, collect_ingredient_values


def test_collect_ingredient_values_keeps_one_box_one_item_without_comma_split():
    result = collect_ingredient_values(["김치, 밥", "", " 계란 "])

    assert result == ["김치, 밥", "계란"]


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
