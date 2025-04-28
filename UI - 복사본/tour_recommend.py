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
    df_trip_merged = 'trip_merged'
    

    df_region  = pd.read_sql(df_excel, con=engine)
    df_tourism =  pd.read_sql(df_trip_merged, con=engine)

    main_theme = selection[0].strip()
    # df_food = df_region[df_region["cat1"].str.strip() == main_theme].copy()

    # 거리 계산 및 새로운 열 추가
    df_tourism["거리"] = df_tourism.apply(lambda row: haversine(station_lat, station_lon, row["위도"], row["경도"]), axis=1)

    # 5km 미만인 데이터 필터링
    df_filtered = df_tourism[df_tourism["거리"] < 5]

    # 거리순으로 정렬 후, 같은 거리 내에서 음식 점수 순으로 정렬
    df_sorted = df_filtered.sort_values(by=[main_theme, "거리"], ascending=[True, False])
    # 상위 10개 데이터 선택
    df_top10 = df_sorted.head(2)

    # 중복 확인용 세트
    recommended_foods = set()

    # 각 행정동별로 가까운 음식점 5개 찾기 (중복 제거)
    def find_top5_food(row):
        lat, lon = row["위도"], row["경도"]
        df_region["거리"] = df_region.apply(lambda r: haversine(lat, lon, r["mapy"], r["mapx"]), axis=1)
        
        # 중복되지 않은 음식점 찾기
        top_foods = []
        for _, food in df_region.sort_values("거리").iterrows():
            if food["title"] not in recommended_foods:
                top_foods.append(food["title"])
                recommended_foods.add(food["title"])
            if len(top_foods) == 5:  # 5개만 선택
                break
        return top_foods

    # 리스트로 저장
    closest_foods_list = [find_top5_food(row) for _, row in df_top10.iterrows()]

    # 평탄화(Flatten)하여 한 행씩 추가
    flat_foods_list = [food for sublist in closest_foods_list for food in sublist]

    # 데이터프레임 생성
    df_recommend = pd.DataFrame({'추천장소': flat_foods_list})


    # ───────────클러스터링 ─────────────────────────────────
    # NearestNeighbors 설정
    neighbors_model = NearestNeighbors(n_neighbors=15, radius=5, algorithm='ball_tree')
    neighbors_model.fit(df_region[["mapy", "mapx"]])  # 음식점 위치 학습

    # 중복 방지를 위한 집합
    recommended_foods = set()

    # 음식점 추천 함수 (중복 없이 5개 추출)
    def find_nearby_foods(place_name):
        place_row = df_region[df_region["title"] == place_name]

        if place_row.empty:
            return [], 0  # 해당 추천장소가 없으면 빈 리스트 반환

        lat, lon = place_row.iloc[0]["mapy"], place_row.iloc[0]["mapx"]
        distances, indices = neighbors_model.radius_neighbors([[lat, lon]], radius=5)

        nearby_foods = []
        walk_distances = []

        for idx, dist in zip(indices[0], distances[0]):
            food_name = df_region.iloc[idx]["title"]
            if food_name not in recommended_foods:
                nearby_foods.append(food_name)
                walk_distances.append(dist)
                recommended_foods.add(food_name)
            if len(nearby_foods) == 5:  # 최대 5개 선택
                break

        avg_walk_distance = round(sum(walk_distances) / len(walk_distances), 2) if walk_distances else 0
        return nearby_foods, avg_walk_distance

    # 첫 번째 추천장소에서 가까운 음식점 5개 및 도보 이동 거리 추가
    df_recommend["추천장소2"], df_recommend["도보이동km_1"] = zip(*df_recommend["추천장소"].apply(find_nearby_foods))
    df_recommend["추천장소3"], df_recommend["도보이동km_2"] = zip(*df_recommend["추천장소2"].apply(lambda places: find_nearby_foods(places[0]) if places else ([], 0)))

    # 추천장소2에서 추가 음식점 5개 및 도보 이동 거리 추가
    df_recommend["추천장소3"] = df_recommend["추천장소2"].apply(lambda places: [find_nearby_foods(place) for place in places])
    # 🔹 지정된 열 순서대로 정렬
    df_recommend = df_recommend[["추천장소", "도보이동km_1", "추천장소2", "도보이동km_2", "추천장소3"]]

    df_recommend["추천장소2"] = df_recommend["추천장소2"].apply(lambda x: ", ".join(x))  # 리스트를 문자열로 변환
    df_recommend["추천장소3"] = df_recommend["추천장소3"].apply(lambda x: ", ".join(map(str, x)).replace("[", "").replace("]", "") if isinstance(x, list) else str(x))
    df_recommend["추천장소3"] = df_recommend["추천장소3"].apply(lambda x: ", ".join(map(str, x)).replace("(", "").replace(")", "").replace("[", "").replace("]", "").strip() if isinstance(x, (list, tuple)) else str(x).replace("(", "").replace(")", "").replace("[", "").replace("]", "").strip())
    df_recommend["추천장소3"] = df_recommend["추천장소3"].apply(lambda x: str(x).replace("'", ""))

    df_recommend.to_csv("tour_recommend.csv", index=False, encoding="utf-8-sig")
    return pd.DataFrame(df_recommend)

# print(tour("서울", ["자연","음식"]))
