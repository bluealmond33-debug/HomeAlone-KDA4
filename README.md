# HomeAlone-KDA4

자취생 냉장고 재료를 기반으로 쉬운 레시피를 추천하는 **Gradio MVP** 프로젝트입니다.

## 프로젝트 개요

- 프로젝트명: 냉털 레시피 챗봇
- 기간: 2026-06-24 ~ 2026-06-25
- 형태: Gradio 기반 챗봇 MVP
- 핵심 외부 서비스: OpenAI API, Tavily Search API, 만개의레시피

## 팀

- 차미래
- 김민기
- 박정운
- 안치수 *(GitHub collaborator 초대 필요)*

## 현재 구조

```
HomeAlone-KDA4/
├── app.py
├── config.py
├── clients/
├── data/
├── models/
├── prompts/
├── services/
├── tools/
├── tests/
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── README.md
└── PRD.md
```

## 실행 방법

1. 가상환경 생성
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. 의존성 설치
   ```bash
   pip install -r requirements-dev.txt
   ```
3. 환경변수 설정
   ```bash
   cp .env.example .env
   ```
4. 앱 실행
   ```bash
   python app.py
   ```
5. 테스트 실행
   ```bash
   pytest
   ```

## MVP 범위

- 식재료 입력 정규화 및 검증
- Tavily 기반 만개의레시피 검색
- 상세 페이지 파싱
- 조건 필터링(1인분, 30분 이내, 초급/아무나)
- 칼로리 추정
- 재추천

## 역할 분담 초안

- 김민기: `ingredient_validator_tool` + 입력/상태 UI
- 차미래: `recipe_search_tool` + 검색 정책/통합 조율
- 안치수: `calorie_estimator_tool` + `recipe_detail_scraper_tool` 통합/배포
- 박정운: `retry_recommendation_tool` + fixture/파싱 테스트

## 참고

- 상세 요구사항은 `PRD.md` 참고
- 외부 콘텐츠 사용 범위는 반드시 확인 후 썸네일/조리문구 노출
