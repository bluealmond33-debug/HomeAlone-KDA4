from __future__ import annotations

try:
    import gradio as gr
except ModuleNotFoundError:  # pragma: no cover - test env fallback
    gr = None

from tools.ingredient_validator_tool import ingredient_validator_tool

MAX_INGREDIENT_BOXES = 20
CATEGORY_CHOICES = ["한식", "중식", "일식", "양식", "분식", "상관없음"]
INITIAL_STATE = {"previous_recipe_urls": [], "last_valid_ingredients": []}


def _update(**kwargs):
    if gr is None:
        return kwargs
    return gr.update(**kwargs)


def collect_ingredient_values(ingredient_values: list[str]) -> list[str]:
    return [value.strip() for value in ingredient_values if value and value.strip()]


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


def recommend(*args):
    ingredient_values = list(args[:-2])
    category = args[-2]
    state = args[-1] or INITIAL_STATE.copy()

    ingredients = collect_ingredient_values(ingredient_values)
    validation = ingredient_validator_tool({"ingredients": ingredients})
    state = {
        **INITIAL_STATE,
        **state,
        "last_valid_ingredients": validation.valid_ingredients,
    }

    user_content = f"재료: {', '.join(ingredients) if ingredients else '없음'} / 카테고리: {category}"
    if validation.valid_ingredients:
        assistant_content = "ingredient_validator_tool 검증을 마쳤어요. 다음 검색 단계로 넘길 수 있습니다."
    else:
        assistant_content = "유효 재료가 없어 다음 Tool은 호출하지 않았어요."

    chat = [
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]
    summary = build_summary(ingredients, category, validation)
    return chat, summary, state


def add_ingredient_box(visible_count: int):
    new_count = min(MAX_INGREDIENT_BOXES, visible_count + 1)
    next_button_update = _update(interactive=new_count < MAX_INGREDIENT_BOXES)
    textbox_updates = [_update(visible=index < new_count) for index in range(MAX_INGREDIENT_BOXES)]
    return [new_count, next_button_update, *textbox_updates]


def reset_state():
    textbox_updates = [_update(value="", visible=index == 0) for index in range(MAX_INGREDIENT_BOXES)]
    return [
        *textbox_updates,
        "상관없음",
        [],
        "",
        INITIAL_STATE.copy(),
        1,
        gr.update(interactive=True),
    ]


if gr is not None:
    with gr.Blocks(title="냉털 레시피 챗봇") as demo:
        gr.Markdown("# 냉털 레시피 챗봇\n자취생용 레시피 추천 MVP")
        gr.Markdown("식재료는 한 칸에 하나씩 입력하고, 더 필요하면 **다음** 버튼으로 입력 칸을 추가하세요.")

        visible_count = gr.State(1)
        ingredient_boxes = []
        for index in range(MAX_INGREDIENT_BOXES):
            ingredient_boxes.append(
                gr.Textbox(
                    label=f"식재료 {index + 1}",
                    placeholder="식재료만 입력해주세요(예시: 김치)",
                    visible=index == 0,
                )
            )

        next_btn = gr.Button("다음")
        category = gr.Dropdown(
            choices=CATEGORY_CHOICES,
            value="상관없음",
            label="음식 카테고리",
        )

        with gr.Row():
            recommend_btn = gr.Button("추천")
            retry_btn = gr.Button("재추천")
            reset_btn = gr.Button("초기화")

        chatbot = gr.Chatbot(label="대화")
        result_md = gr.Markdown()
        state = gr.State(INITIAL_STATE.copy())

        next_btn.click(
            add_ingredient_box,
            inputs=[visible_count],
            outputs=[visible_count, next_btn, *ingredient_boxes],
        )
        recommend_btn.click(
            recommend,
            inputs=[*ingredient_boxes, category, state],
            outputs=[chatbot, result_md, state],
        )
        retry_btn.click(
            recommend,
            inputs=[*ingredient_boxes, category, state],
            outputs=[chatbot, result_md, state],
        )
        reset_btn.click(
            reset_state,
            outputs=[*ingredient_boxes, category, chatbot, result_md, state, visible_count, next_btn],
        )
else:  # pragma: no cover - runtime UI unavailable in test env
    demo = None


if __name__ == "__main__":
    if demo is None:
        raise ModuleNotFoundError("gradio가 설치되지 않아 UI를 실행할 수 없습니다.")
    demo.launch()
