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


def recommend(region: str, selection: list[str]) -> pd.DataFrame:

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
    

    # ── 4) 첫 번째 테마 문자열로 필터 ────────────────────────
    main_theme = selection[0].strip()
    df_food = df_region[df_region["cat1"].str.strip() == main_theme].copy()
    
    df = df_region
    
    if df_food.empty:
        raise ValueError(
            f"[filter] '{main_theme}' 카테고리 데이터가 없습니다.\n"
            f"가능한 cat1 값 예시: {df['cat1'].unique()[:10]}"
        )

    # ── 5)(=region)과의 거리 계산 ───────────────────
    df_food["distance"] = df_food.apply(
        lambda r: haversine(station_lat, station_lon, r["mapy"], r["mapx"]), axis=1
    )

    # ── 6) 거리 가까운 10개 중 점수순으로 정렬 ─────────────
    top10 = (
        df_food.nsmallest(10, "distance")
        .sort_values(by="긍정점수", ascending=False)
        .reset_index(drop=True)
    )

    if top10.empty:
        return pd.DataFrame()  # 근처에 데이터가 없으면 빈 DF 반환

    # ── 7) 후보군 & NN ─────────────────────────────────────
    df_candidates = df_food.drop(top10.index).reset_index(drop=True)
    if df_candidates.empty:
        # 후보가 하나도 없으면 단계만 반환
        routes = [{"단계": t, "이동수단1": "", "타는곳1": "", "내리는곳1": "",
                   "추천음식점1": "", "이동수단2": "", "타는곳2": "", "내리는곳2": "",
                   "추천음식점2": ""} for t in top10["title"]]
        return pd.DataFrame(routes)

    nn = NearestNeighbors(
        radius=10 / EARTH_RADIUS,
        metric="haversine",
    ).fit(np.radians(df_candidates[["mapy", "mapx"]].values))

    used = set()
    routes = []

    for idx, row in top10.iterrows():
        stage = row["title"]

        # ─― 1차 추천 (5~10km) ―─
        pt1 = np.radians([[row["mapy"], row["mapx"]]])
        d1, ind1 = nn.radius_neighbors(pt1, return_distance=True)
        d1_km = d1[0] * EARTH_RADIUS

        mask1 = d1_km >= 5
        pairs1 = [(i, dist) for i, dist in zip(ind1[0][mask1], d1_km[mask1]) if i not in used]
        tmp1 = pd.DataFrame(pairs1, columns=["idx", "dist"])
        tmp1["score"] = df_candidates.iloc[tmp1["idx"]]["긍정점수"].values
        tmp1 = tmp1.sort_values(["score", "dist"], ascending=[False, True]).head(5)

        rec1_df = df_candidates.iloc[tmp1["idx"]]
        used |= set(tmp1["idx"])
        first1 = rec1_df.iloc[0] if not rec1_df.empty else None

        # ─― 2차 추천 ―─
        rec2_df = pd.DataFrame()
        if first1 is not None:
            pt2 = np.radians([[first1["mapy"], first1["mapx"]]])
            d2, ind2 = nn.radius_neighbors(pt2, return_distance=True)
            d2_km = d2[0] * EARTH_RADIUS
            mask2 = d2_km >= 5
            pairs2 = [(i, dist) for i, dist in zip(ind2[0][mask2], d2_km[mask2]) if i not in used]
            tmp2 = pd.DataFrame(pairs2, columns=["idx", "dist"])
            tmp2["score"] = df_candidates.iloc[tmp2["idx"]]["긍정점수"].values
            tmp2 = tmp2.sort_values(["score", "dist"], ascending=[False, True]).head(5)
            rec2_df = df_candidates.iloc[tmp2["idx"]]
            used |= set(tmp2["idx"])

        # ─― 이동수단 예시 로직 ―─
        mode1 = "지하철" if idx % 2 == 0 else "버스"
        mode2 = "버스" if mode1 == "지하철" else "지하철"
        end1  = first1["closest_subway_station"] if first1 is not None else ""
        start2 = end1
        end2 = rec2_df.iloc[0]["closest_subway_station"] if not rec2_df.empty else ""

        routes.append(
            {
                "단계": stage,
                "이동수단1": mode1,
                "타는곳1": "출발지",
                "내리는곳1": end1 or "없음",
                "추천음식점1": ", ".join(rec1_df["title"]) if not rec1_df.empty else "없음",
                "이동수단2": mode2,
                "타는곳2": start2 or "없음",
                "내리는곳2": end2 or "없음",
                "추천음식점2": ", ".join(rec2_df["title"]) if not rec2_df.empty else "없음",
            }
        )

    return pd.DataFrame(routes)

print(recommend("서울", ["음식","자연"]))
