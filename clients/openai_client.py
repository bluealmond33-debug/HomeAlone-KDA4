import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    return OpenAI(api_key=api_key)


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
