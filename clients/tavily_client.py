import os

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()


def get_tavily_client():

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise ValueError("TAVILY_API_KEY가 설정되지 않았습니다.")

    return TavilyClient(api_key=api_key)