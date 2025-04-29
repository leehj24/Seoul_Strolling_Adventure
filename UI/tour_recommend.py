import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors
from math import radians, sin, cos, sqrt, asin
from utils import geocode_region_kakao
from sqlalchemy import create_engine
import pymysql

EARTH_RADIUS = 6371.0  # km

def haversine(lat1, lon1, lat2, lon2):
    """두 좌표 간 대원거리(km) 계산"""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))

def tour(region: str, selection: list[str]) -> pd.DataFrame:
    # 1) region → 위경도
    coords = geocode_region_kakao(region)
    if not coords:
        raise ValueError(f"[geocode] '{region}' 위·경도 조회 실패")
    station_lat, station_lon = coords

    # 2) DB 연결 및 데이터 로드
    engine = create_engine("mysql+pymysql://root:0000@localhost/df_region")
    df_region = pd.read_sql("excel_table", con=engine)
    df_review = pd.read_sql("csv_table",   con=engine)

    # 3) 리뷰 점수·키워드 집계
    df_score = (
        df_review.groupby("addr1", as_index=False)["긍정점수"].mean()
    )
    df_kw = (
        df_review.groupby("addr1", as_index=False)["리뷰내용"]
                 .agg(lambda kws: " ".join(sorted(set([k for k in kws if pd.notnull(k)]))))
    )
    df_region = (
        df_region
        .merge(df_score, on="addr1", how="left")
        .merge(df_kw,    on="addr1", how="left")
        .drop_duplicates(subset=["title"])
        .reset_index(drop=True)
    )

    # 리뷰내용이 없으면 cat3로 대체
    df_review['리뷰내용'] = df_review.apply(
        lambda r: r['cat3'] if pd.isna(r['리뷰내용']) else r['리뷰내용'],
        axis=1
    )

    # 4) 테마 필터링
    main_theme = selection[0].strip()
    df_food = df_region[df_region["cat1"].str.strip() == main_theme].copy()
    df_food['긍정점수'] = pd.to_numeric(df_food['긍정점수'], errors='coerce')
    df_food = df_food.dropna(subset=['긍정점수'])
    df_food = df_food.sort_values(by='긍정점수', ascending=False).reset_index(drop=True)

    # 5) station 좌표 기준으로 거리 계산하여 가까운 10곳
    df_food['station_dist'] = df_food.apply(
        lambda r: haversine(station_lat, station_lon, r['mapy'], r['mapx']), axis=1
    )
    nearest10 = df_food.nsmallest(10, 'station_dist')['title'].tolist()

    # 6) NearestNeighbors 모델 설정 (음식점 간 이웃 추천용)
    nbrs = NearestNeighbors(n_neighbors=5, radius=5, algorithm='ball_tree')
    nbrs.fit(df_food[['mapy', 'mapx']])

    # 중복 방지용 전역 집합
    recommended = set()

    def find_nearby(place_name):
        row = df_food[df_food['title'] == place_name]
        if row.empty:
            return [], 0
        lat, lon = row.iloc[0][['mapy', 'mapx']]
        dists, idxs = nbrs.radius_neighbors([[lat, lon]], radius=5)
        recs, walks = [], []
        for idx, d in zip(idxs[0], dists[0]):
            title = df_food.iloc[idx]['title']
            if title not in recommended:
                recs.append(title)
                walks.append(d)
                recommended.add(title)
            if len(recs) == 5:
                break
        avg_dist = round(sum(walks) / len(walks), 2) if walks else 0
        return recs, avg_dist

    # 7) 추천 DataFrame 구성
    df_recommend = pd.DataFrame({"추천장소": nearest10})
    df_recommend["추천장소2"], df_recommend["도보이동km_1"] = zip(
        *df_recommend["추천장소"].apply(find_nearby)
    )
    df_recommend["추천장소3"], df_recommend["도보이동km_2"] = zip(
        *df_recommend["추천장소2"].apply(lambda lst: find_nearby(lst[0]) if lst else ([], 0))
    )

    # 8) 최종 포맷팅
    df_recommend["추천장소2"] = df_recommend["추천장소2"].apply(lambda x: ", ".join(x))
    df_recommend["추천장소3"] = df_recommend["추천장소3"].apply(lambda x: ", ".join(x))

    return df_recommend[["추천장소", "도보이동km_1", "추천장소2", "도보이동km_2", "추천장소3"]]

# print(tour("성수", ["자연","음식"]))
