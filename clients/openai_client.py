"""OpenAI ingredient classification wrapper.

기본 동작은 환경 설정이 없으면 예외를 발생시켜 caller가 PRD fallback을 타게 한다.
실제 API 연결은 이후 팀 통합 시 이 클래스에 추가하면 된다.
"""

from config import settings


class OpenAIIngredientClassifier:
    def classify_unknown_items(self, items: list[str]) -> list[dict]:
        if not items:
            return []
        if not settings.openai_api_key or not settings.openai_model:
            raise RuntimeError("OpenAI classifier unavailable")
        raise NotImplementedError("OpenAI ingredient classification integration pending")
