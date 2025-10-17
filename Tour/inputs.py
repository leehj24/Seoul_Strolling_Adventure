# inputs.py
# 사용자 입력만 관리합니다.
import os

# 현재 작업 디렉토리 가져오기
PARENT = os.getcwd()


TOUR_REGION          = "강릉"
TRANSPORT_FALLBACK   = "transit"      # "walk" | "transit"
SCORE_NAME           = ["인기도지수"]  # ["인기도지수"] or ["관광지수"]
DAY_STR              = "3일"
PATH_TMF             = fr"{PARENT}\Tour\관광지_법정동_매핑결과.csv"
FALLBACK_N           = 5

# 카테고리(큰→작은). 비율은 3·2·1로 적용되고, 가능 시 각 카테고리 최소 1곳 보장.
CATS                 = ["자연", "레포츠", "쇼팡"]

# 일정 시간
START_TIME_STR       = "08:00"
END_TIME_STR         = "22:00"
print(PARENT)