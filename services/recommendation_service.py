class RecommendationService:
    """MVP orchestration placeholder.

    실제 구현에서는 아래 순서를 고정한다.
    1. ingredient_validator_tool
    2. recipe_search_tool
    3. recipe_detail_scraper_tool
    4. 조건 필터링/정렬
    5. calorie_estimator_tool
    6. retry_recommendation_tool
    """

    def recommend(self, raw_ingredients: str, category: str):
        return {
            "status": "not_implemented",
            "raw_ingredients": raw_ingredients,
            "category": category,
        }
