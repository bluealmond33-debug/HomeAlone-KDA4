from tools.recipe_search_tool import build_recipe_query, normalize_recipe_url


def test_build_recipe_query_with_category():
    query = build_recipe_query(["김치", "밥", "계란"], "한식")

    assert "김치" in query
    assert "밥" in query
    assert "계란" in query
    assert "한식" in query
    assert "30분 이내" in query
    assert "초급" in query


def test_build_recipe_query_without_category():
    query = build_recipe_query(["김치", "밥"], "상관없음")

    assert "김치" in query
    assert "밥" in query
    assert "상관없음" not in query


def test_normalize_recipe_url_success():
    url = "https://www.10000recipe.com/recipe/6920226?seq=abc#top"

    result = normalize_recipe_url(url)

    assert result == "https://www.10000recipe.com/recipe/6920226"


def test_normalize_recipe_url_reject_external_domain():
    url = "https://blog.naver.com/recipe/6920226"

    result = normalize_recipe_url(url)

    assert result is None


def test_normalize_recipe_url_reject_http():
    url = "http://www.10000recipe.com/recipe/6920226"

    result = normalize_recipe_url(url)

    assert result is None


def test_normalize_recipe_url_reject_non_recipe_path():
    url = "https://www.10000recipe.com/shop/123"

    result = normalize_recipe_url(url)

    assert result is None