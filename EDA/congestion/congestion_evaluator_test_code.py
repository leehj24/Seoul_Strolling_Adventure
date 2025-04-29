import pandas as pd
from congestion_evaluator import CongestionEvaluator

congestion_file_path = "./congestion/data/혼잡도 최종등급_통합.csv"
evaluator = CongestionEvaluator(congestion_file_path)

# 1. 특정 장소 + 특정 시간대 혼잡도 조회
# 예: 서울특별시 종로구 사직동, '10시' 시간대
place_level = evaluator.time_based_congestion_of_place(
    sido="서울특별시",
    sigungu="종로구",
    legaldong="사직동",
    time="10시"
)
print(f"사직동 10시 혼잡도 등급: {place_level}")

# 2. 특정 장소 + 시간구간 혼잡도 조회
# 예: 10시, 11시, 12시 평균
place_level_avg = evaluator.time_based_congestion_of_place(
    sido="서울특별시",
    sigungu="종로구",
    legaldong="사직동",
    time=["10시", "11시", "12시"]
)
print(f"\n사직동 10~12시 평균 혼잡도 등급: {place_level_avg}")

# 3. 장소 리스트에서 특정 시간대에 여유/보통인 장소 추천
# 예시 장소 DataFrame 생성
places_df = pd.DataFrame({
    "시도": ["서울특별시", "서울특별시", "경기도"],
    "시군구": ["종로구", "강남구", "성남시"],
    "legaldong": ["사직동", "삼성동", "분당동"]
})

recommended_df = evaluator.recommended_place_in_certain_time(
    df_places=places_df,
    time="10시"
)
print(f"\n[ 추천 장소 ]")
print(recommended_df)

# 4. 특정 장소의 모든 시간대별 혼잡도 조회
place_all_time_df = evaluator.get_all_time_congestion_of_place(
    sido="서울특별시",
    sigungu="종로구",
    legaldong="사직동"
)
print("\n[ 사직동 모든 시간대 혼잡도 정보 ]")
print(place_all_time_df)

# 5. 특정 시간대(예: '10시') 전체 장소의 혼잡도 조회
places_at_time_df = evaluator.get_all_places_congestion_at_time(
    time="10시"
)
print("\n[ 10시 전체 장소 혼잡도 정보 ]")
print(places_at_time_df)