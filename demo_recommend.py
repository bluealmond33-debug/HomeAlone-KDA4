"""CLI 데모: 재료/카테고리로 추천을 받아 출력한다 (API 키 없이 실행 가능).

만개의레시피 검색 페이지를 직접 스크래핑하므로 흔한 재료는 키 없이 동작한다.
칼로리는 OpenAI 키가 없으면 '추정 불가'로 표시된다.

사용법:
    python demo_recommend.py 김치 밥 계란
    python demo_recommend.py 김치 계란 --category 한식
"""

from __future__ import annotations

import argparse
import sys

from services.recommendation_service import RecommendationService


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 한글 깨짐 방지
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="냉털 레시피 추천 데모")
    parser.add_argument("ingredients", nargs="+", help="식재료 (공백으로 구분)")
    parser.add_argument(
        "--category",
        default="상관없음",
        help="한식/중식/일식/양식/분식/상관없음 (기본: 상관없음)",
    )
    args = parser.parse_args(argv)

    print(f"\n🔎 입력: {', '.join(args.ingredients)} / 카테고리: {args.category}\n")
    outcome = RecommendationService().recommend(args.ingredients, args.category)
    print(f"[상태] {outcome.status} — {outcome.message}\n")

    if outcome.status == "SUCCESS":
        print(outcome.card_markdown)
    else:
        for item in outcome.excluded_items:
            print(f"  제외: {item.item} ({item.reason})")
    return 0 if outcome.status == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
