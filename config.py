import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "8"))
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "5"))
    enable_ingredient_cache_write: bool = (
        os.getenv("ENABLE_INGREDIENT_CACHE_WRITE", "false").lower() == "true"
    )
    enable_recipe_content_display: bool = (
        os.getenv("ENABLE_RECIPE_CONTENT_DISPLAY", "false").lower() == "true"
    )


settings = Settings()
