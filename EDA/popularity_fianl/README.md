# 인기도 지수 계산기 (PopularityScorer)

- 행정구 × 행정동 × 카테고리 단위의 리뷰 데이터를 기반으로 인기도 지수를 계산하는 모듈

## 기능

- 리뷰 수, 평점, 긍정확률을 기반으로 인기도 지수 산정

- 베이지안 보정 및 로그 변환 적용

- 단순 평균 가중치 설정정

- Pandas 기반 정렬된 결과 출력


## 사용법

### 1. 의존성 설치
```
pip install -r requirements.txt
```

### 2. Python 모듈 실행
```
python example_usage.py
```

## 구성 파일

- popularity_scorer.py : 인기도 지수 계산 클래스

- example_usage.py : 실행 예제 파일

- zb_review_data_final.csv : 입력 데이터

- requirements.txt : 필수 라이브러리 목록

- README.md : 설명 문서