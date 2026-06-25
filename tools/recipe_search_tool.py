import re

from clients.openai_client import get_openai_client, get_openai_model


def normalize_cooking_time(cooking_time) -> int:

    if isinstance(cooking_time, int):
        return cooking_time

    if not cooking_time:
        return 30

    numbers = re.findall(r"\d+", str(cooking_time))

    if not numbers:
        return 30

    return max(map(int, numbers))


def recipe_search_tool(
    valid_ingredients: list[str],
    category: str,
    cooking_time,
) -> str:

    if not valid_ingredients:
        return "추천 가능한 메뉴가 없습니다."

    max_time = normalize_cooking_time(cooking_time)

    ingredients = ", ".join(valid_ingredients)

    prompt = f"""
너는 1인 가구 레시피 추천 AI이다.

사용 가능한 재료
{ingredients}

카테고리
{category}

조건
- 반드시 1인분
- 조리시간은 {max_time}분 이내
- 실제 만개의레시피에서 검색 가능한 메뉴
- 메뉴명만 출력
- 설명 금지
- 번호 금지
- 따옴표 금지

예시

김치볶음밥
토마토계란볶음
계란국

메뉴명 하나만 출력해.
"""

    client = get_openai_client()

    response = client.responses.create(
        model=get_openai_model(),
        input=prompt,
    )

    return response.output_text.strip()
