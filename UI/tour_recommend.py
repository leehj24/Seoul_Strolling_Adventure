import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors
from math import radians, sin, cos, sqrt, asin
from utils import geocode_region_kakao, compute_scores
from sqlalchemy import create_engine
import pymysql

EARTH_RADIUS = 6371.0  # km


def haversine(lat1, lon1, lat2, lon2):
    """두 좌표 간 대원거리(km)"""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))


def tour(region: str, selection: list[str]) -> pd.DataFrame:

    # ── 1) region → 위경도 ─────────────────────────────────────
    coords = geocode_region_kakao(region)
    if not coords:
        raise ValueError(f"[geocode] '{region}' 위·경도 조회 실패")
    station_lat, station_lon = coords

    host = 'localhost'         # 호스트 (예: '127.0.0.1')
    user = 'root'              # 사용자 이름
    password = '0000'      # 사용자 비밀번호
    database = 'df_region'       # 데이터베이스 이름

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}/{database}")

    df_excel="excel_table"  # 불러올 테이블 이름
    df_csv = 'csv_table'
    df_csv2 = 'tourism_table'

    # ── 2) DB에서 음식점 데이터 가져오기 ──────────────────────
    df_region  = pd.read_sql(df_excel, con=engine)
    df_review  = pd.read_sql(df_csv, con=engine)

    main_theme = selection[0].strip()
    # df_food = df_region[df_region["cat1"].str.strip() == main_theme].copy()

    df_region  = pd.read_sql(df_excel, con=engine)
    df_review  = pd.read_sql(df_csv, con=engine)

    # ── 3) 리뷰 점수 계산 ───────────────────────────────────

    # 3) addr1별 긍정점수 평균 계산
    df_score = (
        df_review
        .groupby("addr1", as_index=False)["긍정점수"]
        .mean()
        # 컬럼명이 이미 "긍정점수"라면 rename은 생략해도 됩니다.
    )

    # 4) addr1별 리뷰내용 묶기
    df_kw = (
        df_review
        .groupby("addr1", as_index=False)["리뷰내용"]
        .agg(lambda kws: 
            " ".join(
                sorted(
                    set(
                        # None/NaN 제거
                        [k for k in kws if pd.notnull(k)]
                    )
                )
            )
        )
    )

    # 5) df_region에 병합
    df_region = (
        df_region
        .merge(df_score, on="addr1", how="left")
        .merge(df_kw,    on="addr1", how="left")
        .drop_duplicates(subset=["title"], keep="first")
        .reset_index(drop=True)
    )

    # 6) 리뷰내용 없을시 카테고리 cat3로 넣음
    df_review['리뷰내용'] = df_review.apply(
    lambda row: row['cat3'] if pd.isna(row['리뷰내용']) else row['리뷰내용'],
    axis=1
    )

    # 7) 테마선택
    main_theme = selection[0].strip()
    df_food = df_region[df_region["cat1"].str.strip() == main_theme].copy()
    

    # 긍정점수 컬럼을 숫자형으로 변환
    df_food['긍정점수'] = pd.to_numeric(df_food['긍정점수'], errors='coerce')

    # 긍정점수가 없는 데이터는 제외
    df_food = df_food.dropna(subset=['긍정점수'])

    # 긍정점수 기준으로 정렬
    df_food_sorted_by_score = df_food.sort_values(by='긍정점수', ascending=False)

    # NearestNeighbors 모델 설정 (위도, 경도를 기준으로 추천)
    neighbors_model = NearestNeighbors(n_neighbors=5, radius=5, algorithm='ball_tree')
    neighbors_model.fit(df_food_sorted_by_score[['mapy', 'mapx']])

    # 중복된 추천을 방지하기 위한 집합
    recommended_foods = set()

    # 음식점 추천 함수 (중복 없이 5개 추천)
    def find_nearby_foods(place_name):
        place_row = df_food_sorted_by_score[df_food_sorted_by_score['title'] == place_name]

        if place_row.empty:
            return [], 0  # 해당 음식점이 없으면 빈 리스트 반환

        lat, lon = place_row.iloc[0]['mapy'], place_row.iloc[0]['mapx']
        distances, indices = neighbors_model.radius_neighbors([[lat, lon]], radius=5)

        nearby_foods = []
        walk_distances = []

        for idx, dist in zip(indices[0], distances[0]):
            food_name = df_food_sorted_by_score.iloc[idx]['title']
            if food_name not in recommended_foods:
                nearby_foods.append(food_name)
                walk_distances.append(dist)
                recommended_foods.add(food_name)
            if len(nearby_foods) == 5:  # 최대 5개만 추천
                break

        avg_walk_distance = round(sum(walk_distances) / len(walk_distances), 2) if walk_distances else 0
        return nearby_foods, avg_walk_distance

    # 추천 데이터프레임 준비 (상위 10개의 음식점 추천)
    df_recommend = pd.DataFrame({
        "추천장소": df_food_sorted_by_score["title"].head(10)  # 긍정점수 기준 상위 10개 음식점
    })

    # 첫 번째 추천장소에서 가까운 음식점 5개 및 도보 이동 거리 추가
    df_recommend["추천장소2"], df_recommend["도보이동km_1"] = zip(*df_recommend["추천장소"].apply(find_nearby_foods))

    # 추천장소2에서 가까운 음식점 5개 및 도보 이동 거리 추가 (추천장소2를 기준으로)
    df_recommend["추천장소3"], df_recommend["도보이동km_2"] = zip(*df_recommend["추천장소2"].apply(lambda places: find_nearby_foods(places[0]) if places else ([], 0)))

    # 🔹 지정된 열 순서대로 정렬
    df_recommend = df_recommend[["추천장소", "도보이동km_1", "추천장소2", "도보이동km_2", "추천장소3"]]

    # 리스트를 문자열로 변환
    df_recommend["추천장소2"] = df_recommend["추천장소2"].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))
    df_recommend["추천장소3"] = df_recommend["추천장소3"].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else str(x))



    return pd.DataFrame(df_recommend)

# print(tour("서울", ["자연","음식"]))
