import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors
from math import radians, sin, cos, sqrt, asin
from utils import geocode_region_kakao, compute_scores

EARTH_RADIUS = 6371.0  # km


def haversine(lat1, lon1, lat2, lon2):
    """두 좌표 간 대원거리(km)"""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))


def recommend(region: str, selection: list[str]) -> pd.DataFrame:
    """
    region : '인천역' 같은 키워드
    selection : ['음식', '관광', '레포츠'] 등 테마 리스트
    반환      : 단계·이동수단·추천 음식점 정보 DataFrame
    """
    # ── 1) region → 위경도 ─────────────────────────────────────
    coords = geocode_region_kakao(region)
    if not coords:
        raise ValueError(f"[geocode] '{region}' 위·경도 조회 실패")
    station_lat, station_lon = coords

    # ── 2) 데이터 로드 ────────────────────────────────────────
    file_main   = r"E:\machin-prj\my_dataframe5.xlsx"
    file_review = r"E:\machin-prj\review_data_인천_행정동추가.csv"

    df         = pd.read_excel(file_main)
    df_review  = pd.read_csv(file_review, encoding="utf-8")

    # ── 3) 리뷰 점수 및 텍스트 감정 점수 계산 ───────────────
    df_avg_score = df_review.groupby("장소명", as_index=False)["별점"].mean()
    df_avg_score.rename(columns={"별점": "avg_rating_score"}, inplace=True)

    pos_words = ["좋다", "최고", "만족", "추천", "행복", "감사", "친절", "편리", "맛있"]
    neg_words = ["나쁘다", "불만", "최악", "짜증", "불편", "실망", "불친절", "별로"]

    def get_text_sentiment(text: str) -> int:
        text = str(text)
        pos = sum(text.count(w) for w in pos_words)
        neg = sum(text.count(w) for w in neg_words)
        if pos > neg:
            return 10
        elif neg > pos:
            return 5
        return 0

    df_review["sent_text_score"] = df_review["리뷰내용"].apply(get_text_sentiment)
    df_avg_text = (
        df_review.groupby("장소명", as_index=False)["sent_text_score"]
        .mean()
        .rename(columns={"sent_text_score": "avg_text_sent_score"})
    )

    # 원본 + 점수 머지
    df_final = df_review.drop_duplicates(subset=["장소명"])
    df_final = df_final.merge(df_avg_score, on="장소명", how="left")
    df_final = df_final.merge(df_avg_text, on="장소명", how="left")
    df_final["final_score"] = (
        df_final["avg_rating_score"] + df_final["avg_text_sent_score"]
    ) / 2

    df = df.merge(df_final[["addr1", "final_score"]], on="addr1", how="left")
    df = df.drop_duplicates(subset=["title"]).reset_index(drop=True)

    # ── 4) 첫 번째 테마 문자열로 필터 ────────────────────────
    main_theme = selection[0].strip()
    df_food = df[df["cat1"].str.strip() == main_theme].copy()

    if df_food.empty:
        raise ValueError(
            f"[filter] '{main_theme}' 카테고리 데이터가 없습니다.\n"
            f"가능한 cat1 값 예시: {df['cat1'].unique()[:10]}"
        )

    # ── 5) 인천역(=region)과의 거리 계산 ───────────────────
    df_food["distance"] = df_food.apply(
        lambda r: haversine(station_lat, station_lon, r["mapy"], r["mapx"]), axis=1
    )

    # ── 6) 거리 가까운 10개 중 점수순으로 정렬 ─────────────
    top10 = (
        df_food.nsmallest(10, "distance")
        .sort_values(by="final_score", ascending=False)
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
        tmp1["score"] = df_candidates.iloc[tmp1["idx"]]["final_score"].values
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
            tmp2["score"] = df_candidates.iloc[tmp2["idx"]]["final_score"].values
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
