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
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    return 2 * EARTH_RADIUS * asin(sqrt(a))

def recommend(region: str, selection: list[str]) -> pd.DataFrame:
    # 1) region → 위경도 변환
    coords = geocode_region_kakao(region)
    if not coords:
        raise ValueError(f"[geocode] '{region}' 위·경도 조회 실패")
    station_lat, station_lon = coords

    # 2) DB 연결 설정
    host = 'localhost'
    user = 'root'
    password = '0000'
    database = 'df_region'
    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}/{database}")

    # 3) 데이터 로드
    df_region = pd.read_sql("excel_table", con=engine)
    df_review = pd.read_sql("csv_table",  con=engine)

    # 4) 리뷰 점수 계산 및 키워드 병합
    df_score = df_review.groupby("addr1", as_index=False)["긍정점수"].mean()
    df_kw    = df_review.groupby("addr1", as_index=False)["리뷰내용"].agg(
        lambda kws: " ".join(sorted(set(k for k in kws if pd.notnull(k))))
    )
    df_region = (
        df_region
        .merge(df_score, on="addr1", how="left")
        .merge(df_kw,    on="addr1", how="left")
        .drop_duplicates(subset=["title"], keep="first")
        .reset_index(drop=True)
    )

    # 리뷰내용이 없으면 cat3 사용
    df_review['리뷰내용'] = df_review.apply(
        lambda row: row['cat3'] if pd.isna(row['리뷰내용']) else row['리뷰내용'],
        axis=1
    )

    # 5) 테마 필터링
    main_theme = selection[0].strip()
    df_food = df_region[df_region["cat1"].str.strip() == main_theme].copy()
    if df_food.empty:
        raise ValueError(
            f"[filter] '{main_theme}' 카테고리 데이터가 없습니다.\n"
            f"가능한 cat1 값 예시: {df_region['cat1'].unique()[:10]}"
        )

    # 6) 방문지와의 거리 계산
    df_food["distance"] = df_food.apply(
        lambda r: haversine(station_lat, station_lon, r["mapy"], r["mapx"]),
        axis=1
    )

    # 7) 상위 10개 후보 원본 인덱스 추출 및 정렬
    candidate_idx = df_food.nsmallest(10, "distance").index
    top10 = (
        df_food
        .loc[candidate_idx]
        .sort_values(by="긍정점수", ascending=False)
        .reset_index(drop=True)
    )

    # 8) 후보군에서 top10 제외
    df_candidates = df_food.drop(candidate_idx).reset_index(drop=True)

    # 빈 결과 처리
    if top10.empty:
        return pd.DataFrame()

    # 9) NearestNeighbors 모델 생성
    nn = NearestNeighbors(radius=10 / EARTH_RADIUS, metric="haversine")
    nn.fit(np.radians(df_candidates[["mapy", "mapx"]].values))

    used = set()
    routes = []

    for idx, row in top10.iterrows():
        stage = row["title"]

        # 1차 추천 (5~10km)
        pt1 = np.radians([[row["mapy"], row["mapx"]]])
        d1, ind1 = nn.radius_neighbors(pt1, return_distance=True)
        d1_km = d1[0] * EARTH_RADIUS
        mask1 = (d1_km >= 5)
        pairs1 = [(i, dist) for i, dist in zip(ind1[0][mask1], d1_km[mask1]) if i not in used]
        tmp1 = pd.DataFrame(pairs1, columns=["idx", "dist"])
        tmp1["score"] = df_candidates.iloc[tmp1["idx"]]["긍정점수"].values
        tmp1 = tmp1.sort_values(["score", "dist"], ascending=[False, True]).head(5)
        rec1_df = df_candidates.iloc[tmp1["idx"]]
        used |= set(tmp1["idx"])

        # 2차 추천
        rec2_df = pd.DataFrame()
        if not rec1_df.empty:
            first1 = rec1_df.iloc[0]
            pt2 = np.radians([[first1["mapy"], first1["mapx"]]])
            d2, ind2 = nn.radius_neighbors(pt2, return_distance=True)
            d2_km = d2[0] * EARTH_RADIUS
            mask2 = (d2_km >= 5)
            pairs2 = [(i, dist) for i, dist in zip(ind2[0][mask2], d2_km[mask2]) if i not in used]
            tmp2 = pd.DataFrame(pairs2, columns=["idx", "dist"])
            tmp2["score"] = df_candidates.iloc[tmp2["idx"]]["긍정점수"].values
            tmp2 = tmp2.sort_values(["score", "dist"], ascending=[False, True]).head(5)
            rec2_df = df_candidates.iloc[tmp2["idx"]]
            used |= set(tmp2["idx"])

        # 이동수단 예시 로직
        mode1 = "지하철" if idx % 2 == 0 else "버스"
        mode2 = "버스" if mode1 == "지하철" else "지하철"
        end1   = (rec1_df.iloc[0]["closest_subway_station"] if not rec1_df.empty else "")
        start2 = end1
        end2   = (rec2_df.iloc[0]["closest_subway_station"] if not rec2_df.empty else "")

        routes.append({
            "단계": stage,
            "이동수단1": mode1,
            "타는곳1": "출발지",
            "내리는곳1": end1 or "없음",
            "추천장소1": ", ".join(rec1_df["title"]) if not rec1_df.empty else "없음",
            "이동수단2": mode2,
            "타는곳2": start2 or "없음",
            "내리는곳2": end2 or "없음",
            "추천장소2": ", ".join(rec2_df["title"]) if not rec2_df.empty else "없음",
        })

    return pd.DataFrame(routes)
