# retry_recommendation_tool

PRD 8.5의 재추천 기능을 구현한 독립 모듈이다. Python 3.11 이상과
Pydantic 2가 필요하다.

## 파일

- `models/schemas.py`: 입력, 추천 결과, 출력 Pydantic 계약
- `tools/retry_recommendation_tool.py`: 캐시 우선 재추천과 중복 차단
- `tests/test_retry_recommendation_tool.py`: 외부 API를 사용하지 않는 단위 테스트

## 실행

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest -v tests.test_retry_recommendation_tool
```

## 서비스 계층 연결 예시

```python
from models.schemas import RecommendationResult, RetryRecommendationInput
from tools.retry_recommendation_tool import retry_recommendation_tool


def existing_recommendation_pipeline(
    *, valid_ingredients, category, exclude_urls, exclude_menu_names
):
    # 1) recipe_search_tool(..., exclude_urls=list(exclude_urls))
    # 2) recipe_detail_scraper_tool(...) 및 필수 조건 필터/랭킹
    # 3) calorie_estimator_tool(...) 후 RecommendationResult 목록 반환
    return [
        RecommendationResult(
            title="김치전",
            source_url="https://www.10000recipe.com/recipe/1234567",
            category="한식",
            servings=1,
            cooking_time_minutes=20,
            difficulty="초급",
            ingredient_names=["김치", "부침가루"],
        )
    ]


request = RetryRecommendationInput(
    valid_ingredients=["김치", "밥", "계란"],
    category="한식",
    previous_recipe_urls=["https://www.10000recipe.com/recipe/0000000"],
    previous_menu_names=["김치볶음밥"],
    cached_candidates=[],
)

result = retry_recommendation_tool(
    request,
    search_pipeline=existing_recommendation_pipeline,
)

# result.previous_recipe_urls, result.normalized_menu_names,
# result.cached_candidates를 같은 사용자의 gr.State에 다시 저장한다.
print(result.model_dump(mode="json"))
```

`RetryPipelineError`는 외부 검색 장애 또는 파이프라인 미설정을 뜻한다.
이 오류를 `NO_NEW_CANDIDATE`로 바꾸면 사용자가 조건 문제로 오해하므로 서비스
계층에서 별도의 일시적 오류 메시지로 처리해야 한다.
