import gradio as gr


def recommend(ingredients: str, category: str, state: dict | None):
    state = state or {"previous_recipe_urls": []}
    normalized = ingredients.replace("\n", ",") if ingredients else ""
    ingredients_preview = [item.strip() for item in normalized.split(",") if item.strip()]

    summary = "\n".join(
        [
            "## 냉털 레시피 챗봇 MVP 초안",
            "",
            f"- 입력 재료: {', '.join(ingredients_preview) if ingredients_preview else '없음'}",
            f"- 카테고리: {category}",
            "- 현재는 초기 구조만 생성된 상태입니다.",
            "- 다음 단계: 각 Tool 구현 + mock 테스트 연결",
        ]
    )
    chat = [
        {"role": "user", "content": f"재료: {ingredients} / 카테고리: {category}"},
        {"role": "assistant", "content": "초기 구조가 준비되었습니다. 이제 Tool 구현을 이어가면 됩니다."},
    ]
    return chat, summary, state


def reset_state():
    return "", "상관없음", [], "", {"previous_recipe_urls": []}


with gr.Blocks(title="냉털 레시피 챗봇") as demo:
    gr.Markdown("# 냉털 레시피 챗봇\n자취생용 레시피 추천 MVP 초기 화면")
    ingredients = gr.Textbox(label="보유 식재료", lines=4, placeholder="예: 김치, 밥, 계란")
    category = gr.Dropdown(
        choices=["한식", "중식", "일식", "양식", "분식", "상관없음"],
        value="상관없음",
        label="음식 카테고리",
    )
    with gr.Row():
        recommend_btn = gr.Button("추천")
        retry_btn = gr.Button("재추천")
        reset_btn = gr.Button("초기화")

    chatbot = gr.Chatbot(label="대화", type="messages")
    result_md = gr.Markdown()
    state = gr.State({"previous_recipe_urls": []})

    recommend_btn.click(recommend, inputs=[ingredients, category, state], outputs=[chatbot, result_md, state])
    retry_btn.click(recommend, inputs=[ingredients, category, state], outputs=[chatbot, result_md, state])
    reset_btn.click(reset_state, outputs=[ingredients, category, chatbot, result_md, state])


if __name__ == "__main__":
    demo.launch()
