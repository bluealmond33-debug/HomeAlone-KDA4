from __future__ import annotations

try:
    import gradio as gr
except ModuleNotFoundError:  # pragma: no cover - test env fallback
    gr = None

from config import settings
from services.recommendation_service import RecommendationService
from tools.ingredient_validator_tool import ingredient_validator_tool

_service = RecommendationService()

MAX_INGREDIENT_BOXES = 20
INITIAL_INGREDIENT_BOXES = 3
MAX_EXCLUDE_BOXES = 20
INITIAL_EXCLUDE_BOXES = 1
DEFAULT_INGREDIENT_PLACEHOLDERS = [
    "식재료만 입력해주세요(예시: 김치)",
    "식재료만 입력해주세요(예시: 두부)",
    "식재료만 입력해주세요(예시: 계란)",
]
DEFAULT_EXCLUDE_PLACEHOLDERS = [
    "추천에서 제외할 재료(예시: 양파)",
    "추천에서 제외할 재료(예시: 고수)",
    "추천에서 제외할 재료(예시: 버섯)",
]
CATEGORY_CHOICES = ["한식", "중식", "일식", "양식", "분식", "상관없음"]
INITIAL_STATE = {
    "previous_recipe_urls": [],
    "last_valid_ingredients": [],
    "last_excluded_ingredients": [],
}
INITIAL_READY_MESSAGE = "기본 재료 칸 3개가 준비됐어요. 재료를 넣고 카테고리를 골라주세요."


def _update(**kwargs):
    if gr is None:
        return kwargs
    return gr.update(**kwargs)


def collect_ingredient_values(ingredient_values: list[str]) -> list[str]:
    return [value.strip() for value in ingredient_values if value and value.strip()]


def get_ingredient_placeholder(index: int) -> str:
    if index < len(DEFAULT_INGREDIENT_PLACEHOLDERS):
        return DEFAULT_INGREDIENT_PLACEHOLDERS[index]
    return "식재료만 입력해주세요(예시: 감자)"


def get_exclude_placeholder(index: int) -> str:
    if index < len(DEFAULT_EXCLUDE_PLACEHOLDERS):
        return DEFAULT_EXCLUDE_PLACEHOLDERS[index]
    return "추천에서 제외할 재료(예시: 양파)"


def build_summary(ingredients: list[str], category: str, validation_result) -> str:
    excluded_lines = [f"  - {item.item}: {item.reason}" for item in validation_result.excluded_items]
    warning_lines = [f"  - {warning}" for warning in validation_result.warnings]
    return "\n".join(
        [
            "## 냉털 레시피 챗봇 MVP",
            "",
            f"- 입력 재료: {', '.join(ingredients) if ingredients else '없음'}",
            f"- 카테고리: {category}",
            f"- 유효 재료: {', '.join(validation_result.valid_ingredients) if validation_result.valid_ingredients else '없음'}",
            "- 제외 항목:",
            *(excluded_lines or ["  - 없음"]),
            "- 경고:",
            *(warning_lines or ["  - 없음"]),
            "",
            "- 다음 단계: 유효 재료가 1개 이상일 때 후속 검색 Tool로 연결",
        ]
    )


def build_next_box_status(visible_count: int) -> str:
    if visible_count >= MAX_INGREDIENT_BOXES:
        return "재료 칸 20개가 모두 열렸어요. 이제 냉장고 털이 시작 준비 완료입니다."
    return f"재료 칸 {visible_count}개 준비 완료. 다음 재료도 한 칸에 하나씩 넣어주세요."


def build_next_exclude_box_status(visible_count: int) -> str:
    if visible_count <= 0:
        return "제외할 재료가 없으면 그대로 추천해도 돼요."
    if visible_count >= MAX_EXCLUDE_BOXES:
        return "제외 재료 칸 20개가 모두 열렸어요."
    return f"제외 재료 칸 {visible_count}개 준비 완료. 없는 재료를 한 칸에 하나씩 넣어주세요."


def build_remove_box_status(visible_count: int, *, is_exclude: bool) -> str:
    if is_exclude:
        if visible_count <= 0:
            return "제외할 재료가 없으면 그대로 추천해도 돼요."
        return f"제외 재료 칸 {visible_count}개가 남았어요."
    if visible_count <= 0:
        return "식재료 칸을 모두 지웠어요. 식재료 추가로 다시 열 수 있어요."
    return f"재료 칸 {visible_count}개가 남았어요."


def build_category_status(*args) -> str:
    ingredient_values = list(args[:-1])
    category = args[-1] or "상관없음"
    ingredients = collect_ingredient_values(ingredient_values)

    if not ingredients:
        return f"{category} 모드 설정 완료. 이제 식재료를 넣으면 추천 준비를 시작할게요."

    ingredient_text = ", ".join(ingredients)
    return f"{category} 모드 설정 완료. {ingredient_text}로 추천 시작 준비 완료입니다."


def _outcome_markdown(outcome) -> str:
    if outcome.status == "SUCCESS":
        return outcome.card_markdown
    lines = [f"### {outcome.message}"]
    if outcome.excluded_items:
        lines.append("")
        lines.append("- 제외된 입력:")
        lines += [f"  - {item.item}: {item.reason}" for item in outcome.excluded_items]
    return "\n".join(lines)


def _run_recommend(ingredient_values, exclude_values, category, state, *, is_retry):
    category = category or "상관없음"
    state = state or INITIAL_STATE.copy()
    ingredients = collect_ingredient_values(ingredient_values)
    excluded_ingredients = collect_ingredient_values(exclude_values)
    previous = list(state.get("previous_recipe_urls", []))

    # 새 추천은 이력을 비우고 검색, 재추천은 이전 추천 URL을 제외한다.
    outcome = _service.recommend(
        ingredients,
        category,
        exclude_urls=previous if is_retry else [],
        exclude_ingredients=excluded_ingredients,
    )

    urls = previous if is_retry else []
    if outcome.recipe_url and outcome.recipe_url not in urls:
        urls.append(outcome.recipe_url)

    new_state = {
        **INITIAL_STATE,
        **state,
        "last_valid_ingredients": outcome.valid_ingredients,
        "last_excluded_ingredients": excluded_ingredients,
        "previous_recipe_urls": urls,
    }

    if is_retry and outcome.status != "SUCCESS":
        outcome.message = "더 보여드릴 새로운 레시피가 없어요. 재료나 카테고리를 바꿔보세요."

    label = "다시 추천" if is_retry else "추천"
    user_content = (
        f"{label} 요청 — 재료: {', '.join(ingredients) if ingredients else '없음'} "
        f"/ 제외 재료: {', '.join(excluded_ingredients) if excluded_ingredients else '없음'} "
        f"/ 카테고리: {category}"
    )
    chat = [
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": outcome.message},
    ]
    return chat, _outcome_markdown(outcome), new_state


def recommend(*args):
    ingredient_values = list(args[:MAX_INGREDIENT_BOXES])
    exclude_values = list(args[MAX_INGREDIENT_BOXES:-2])
    return _run_recommend(
        ingredient_values,
        exclude_values,
        args[-2],
        args[-1],
        is_retry=False,
    )


def retry(*args):
    ingredient_values = list(args[:MAX_INGREDIENT_BOXES])
    exclude_values = list(args[MAX_INGREDIENT_BOXES:-2])
    return _run_recommend(
        ingredient_values,
        exclude_values,
        args[-2],
        args[-1],
        is_retry=True,
    )


def add_ingredient_box(visible_count: int):
    new_count = min(MAX_INGREDIENT_BOXES, visible_count + 1)
    next_button_update = _update(interactive=new_count < MAX_INGREDIENT_BOXES)
    textbox_updates = [_update(visible=index < new_count) for index in range(MAX_INGREDIENT_BOXES)]
    delete_button_updates = [
        _update(visible=index < new_count) for index in range(MAX_INGREDIENT_BOXES)
    ]
    return [
        new_count,
        next_button_update,
        *textbox_updates,
        *delete_button_updates,
        build_next_box_status(new_count),
    ]


def add_exclude_box(visible_count: int):
    new_count = min(MAX_EXCLUDE_BOXES, visible_count + 1)
    next_button_update = _update(interactive=new_count < MAX_EXCLUDE_BOXES)
    textbox_updates = [_update(visible=index < new_count) for index in range(MAX_EXCLUDE_BOXES)]
    delete_button_updates = [
        _update(visible=index < new_count) for index in range(MAX_EXCLUDE_BOXES)
    ]
    return [
        new_count,
        next_button_update,
        *textbox_updates,
        *delete_button_updates,
        build_next_exclude_box_status(new_count),
    ]


def _remove_box(
    remove_index: int,
    visible_count: int,
    values: list[str],
    *,
    max_boxes: int,
    is_exclude: bool,
):
    visible_count = max(0, min(max_boxes, int(visible_count or 0)))
    active_values = list(values[:visible_count])
    if 0 <= remove_index < visible_count:
        del active_values[remove_index]

    new_count = len(active_values)
    padded_values = active_values + [""] * (max_boxes - new_count)
    next_button_update = _update(interactive=new_count < max_boxes)
    textbox_updates = [
        _update(value=padded_values[index], visible=index < new_count)
        for index in range(max_boxes)
    ]
    delete_button_updates = [
        _update(visible=index < new_count) for index in range(max_boxes)
    ]

    return [
        new_count,
        next_button_update,
        *textbox_updates,
        *delete_button_updates,
        build_remove_box_status(new_count, is_exclude=is_exclude),
    ]


def remove_ingredient_box(remove_index: int, visible_count: int, *values):
    return _remove_box(
        remove_index,
        visible_count,
        list(values),
        max_boxes=MAX_INGREDIENT_BOXES,
        is_exclude=False,
    )


def remove_exclude_box(remove_index: int, visible_count: int, *values):
    return _remove_box(
        remove_index,
        visible_count,
        list(values),
        max_boxes=MAX_EXCLUDE_BOXES,
        is_exclude=True,
    )


def reset_state():
    textbox_updates = [
        _update(value="", visible=index < INITIAL_INGREDIENT_BOXES)
        for index in range(MAX_INGREDIENT_BOXES)
    ]
    ingredient_delete_updates = [
        _update(visible=index < INITIAL_INGREDIENT_BOXES)
        for index in range(MAX_INGREDIENT_BOXES)
    ]
    exclude_updates = [
        _update(value="", visible=index < INITIAL_EXCLUDE_BOXES)
        for index in range(MAX_EXCLUDE_BOXES)
    ]
    exclude_delete_updates = [
        _update(visible=index < INITIAL_EXCLUDE_BOXES)
        for index in range(MAX_EXCLUDE_BOXES)
    ]
    return [
        *textbox_updates,
        *ingredient_delete_updates,
        *exclude_updates,
        *exclude_delete_updates,
        "상관없음",
        [],
        "",
        INITIAL_READY_MESSAGE,
        INITIAL_STATE.copy(),
        INITIAL_INGREDIENT_BOXES,
        _update(interactive=True),
        INITIAL_EXCLUDE_BOXES,
        _update(interactive=True),
    ]


if gr is not None:
    with gr.Blocks(title="냉털 레시피 챗봇") as demo:
        gr.Markdown("# 냉털 레시피 챗봇\n자취생용 레시피 추천 MVP")
        gr.Markdown("식재료는 한 칸에 하나씩 입력하고, 더 필요하면 **식재료 추가** 버튼으로 입력 칸을 추가하세요.")
        reset_btn = gr.Button("초기화")

        visible_count = gr.State(INITIAL_INGREDIENT_BOXES)
        exclude_visible_count = gr.State(INITIAL_EXCLUDE_BOXES)
        ingredient_boxes = []
        ingredient_delete_buttons = []
        for index in range(MAX_INGREDIENT_BOXES):
            with gr.Row():
                ingredient_boxes.append(
                    gr.Textbox(
                        label=f"식재료 {index + 1}",
                        placeholder=get_ingredient_placeholder(index),
                        visible=index < INITIAL_INGREDIENT_BOXES,
                    )
                )
                ingredient_delete_buttons.append(
                    gr.Button("🗑", visible=index < INITIAL_INGREDIENT_BOXES)
                )

        next_btn = gr.Button("식재료 추가")
        gr.Markdown("추천에서 빼고 싶은 재료가 있으면 아래에 입력하세요.")
        exclude_boxes = []
        exclude_delete_buttons = []
        for index in range(MAX_EXCLUDE_BOXES):
            with gr.Row():
                exclude_boxes.append(
                    gr.Textbox(
                        label=f"제외 재료 {index + 1}",
                        placeholder=get_exclude_placeholder(index),
                        visible=index < INITIAL_EXCLUDE_BOXES,
                    )
                )
                exclude_delete_buttons.append(
                    gr.Button("🗑", visible=index < INITIAL_EXCLUDE_BOXES)
                )

        exclude_next_btn = gr.Button("제외 재료 추가")
        category = gr.Dropdown(
            choices=CATEGORY_CHOICES,
            value="상관없음",
            label="음식 카테고리",
        )
        ready_md = gr.Markdown(INITIAL_READY_MESSAGE)

        recommend_btn = gr.Button("냉장고 털기 시작")
        retry_btn = gr.Button("다른 추천 받기")

        chatbot = gr.Chatbot(label="대화")
        result_md = gr.Markdown()
        state = gr.State(INITIAL_STATE.copy())

        next_btn.click(
            add_ingredient_box,
            inputs=[visible_count],
            outputs=[
                visible_count,
                next_btn,
                *ingredient_boxes,
                *ingredient_delete_buttons,
                ready_md,
            ],
        )
        exclude_next_btn.click(
            add_exclude_box,
            inputs=[exclude_visible_count],
            outputs=[
                exclude_visible_count,
                exclude_next_btn,
                *exclude_boxes,
                *exclude_delete_buttons,
                ready_md,
            ],
        )
        for index, delete_btn in enumerate(ingredient_delete_buttons):
            delete_btn.click(
                lambda visible, *values, index=index: remove_ingredient_box(
                    index,
                    visible,
                    *values,
                ),
                inputs=[visible_count, *ingredient_boxes],
                outputs=[
                    visible_count,
                    next_btn,
                    *ingredient_boxes,
                    *ingredient_delete_buttons,
                    ready_md,
                ],
            )
        for index, delete_btn in enumerate(exclude_delete_buttons):
            delete_btn.click(
                lambda visible, *values, index=index: remove_exclude_box(
                    index,
                    visible,
                    *values,
                ),
                inputs=[exclude_visible_count, *exclude_boxes],
                outputs=[
                    exclude_visible_count,
                    exclude_next_btn,
                    *exclude_boxes,
                    *exclude_delete_buttons,
                    ready_md,
                ],
            )
        category.change(
            build_category_status,
            inputs=[*ingredient_boxes, category],
            outputs=[ready_md],
        )
        recommend_btn.click(
            recommend,
            inputs=[*ingredient_boxes, *exclude_boxes, category, state],
            outputs=[chatbot, result_md, state],
        )
        retry_btn.click(
            retry,
            inputs=[*ingredient_boxes, *exclude_boxes, category, state],
            outputs=[chatbot, result_md, state],
        )
        reset_btn.click(
            reset_state,
            outputs=[
                *ingredient_boxes,
                *ingredient_delete_buttons,
                *exclude_boxes,
                *exclude_delete_buttons,
                category,
                chatbot,
                result_md,
                ready_md,
                state,
                visible_count,
                next_btn,
                exclude_visible_count,
                exclude_next_btn,
            ],
        )
else:  # pragma: no cover - runtime UI unavailable in test env
    demo = None


if __name__ == "__main__":
    if demo is None:
        raise ModuleNotFoundError("gradio가 설치되지 않아 UI를 실행할 수 없습니다.")
    demo.launch()
