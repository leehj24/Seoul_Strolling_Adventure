"""
Travel & Food Recommender – v2.0
────────────────────────────────────────────────────────
• 지역 키워드 → 위‧경도 → 주변 맛집 / 관광 스팟 추천
• 리뷰 TF‑IDF로 키워드 & 긍정점수 추출 → 가중 정렬
• 3단계(주 스테이지 + 1·2차 추천) · 이동수단(지하철/버스) 생성
• 반환 DataFrame 컬럼 ⟶
  한줄소개, 추천음식점1, 이동수단1, 타는곳1, 내리는곳1,
  추천음식점2, 이동수단2, 타는곳2, 내리는곳2, 추천음식점3
"""

from __future__ import annotations

import re
from collections import Counter
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

# ────────────────────────────────────────────────────────────────
# 0. 상수 / 파일 경로 설정
# ----------------------------------------------------------------
EARTH_RADIUS = 6371.0  # km
DATA_DIR = Path(r"C:/Users/hyunj/Seoul_Strolling_Adventure")
MAIN_FILE = DATA_DIR / "대중교통위치/my_dataframe5.xlsx"
REVIEW_FILE = DATA_DIR / "popularity/popularity_result.csv"

# ────────────────────────────────────────────────────────────────
# 1. 공통 유틸 함수
# ----------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위‧경도 좌표 간 대원거리(km)."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))

# ────────────────────────────────────────────────────────────────
# 2. 리뷰 → TF‑IDF 키워드 & 긍정점수
# ----------------------------------------------------------------
_STOPWORDS = [
    "맛", "메뉴", "가격", "주문", "서비스", "정말",
    "진짜", "너무", "그리고", "음식", "여기", "그냥",
]
_TOKEN_PAT = r"(?u)\b[가-힣A-Za-z0-9]{2,}\b"
_VEC = TfidfVectorizer(token_pattern=_TOKEN_PAT, stop_words=_STOPWORDS, lowercase=False)
_FEATS: np.ndarray  # vectorizer feature names


def build_review_features(df: pd.DataFrame) -> pd.DataFrame:
    """TF‑IDF 기반 키워드 5개 추출 → df['keywords']에 저장."""
    df["리뷰내용"] = df.apply(lambda r: r["cat3"] if pd.isna(r["리뷰내용"]) else r["리뷰내용"], axis=1)
    tfidf = _VEC.fit_transform(df["리뷰내용"].fillna(""))
    global _FEATS
    _FEATS = np.array(_VEC.get_feature_names_out())

    def top_kw(row_vec, n=5):
        if row_vec.nnz == 0:
            return []
        idx = row_vec.indices[row_vec.data.argsort()[::-1][:n]]
        return _FEATS[idx].tolist()

    df["keywords"] = [top_kw(tfidf[i]) for i in range(tfidf.shape[0])]
    return df

# ────────────────────────────────────────────────────────────────
# 3. 키워드 집합 → 한 줄 문장
# ----------------------------------------------------------------
_STOP = {"곳", "맛", "일", "개", "어쩌구", "집", "곳이", "곳입니다"}
_MENU = r"(짜장|짬뽕|탕수육|파스타|스테이크|갈비|돈까스|냉면|볶음밥)$"
_TASTE = r"(맛있음|존맛|존맛탱|훌륭|완벽|꿀맛|강추|재밌음|만족)$"
_AMBIENCE = {"깔끔한", "분위기로", "친절하고", "편했답니다"}


def _split(tok: str) -> List[str]:
    m = re.search(_TASTE, tok)
    if m:
        stem = re.sub(_TASTE + r".*", "", tok)
        return ([stem] if stem else []) + [m.group()]
    return [tok]


def _clean(tokens: List[str]) -> List[str]:
    out = []
    for t in tokens:
        t = t.strip()
        if not t or t in _STOP:
            continue
        if t.startswith("개") and len(t) > 2:
            t = t[1:]
        if re.fullmatch(r"[^\w가-힣]+", t):
            continue
        if len(t) <= 2 and re.fullmatch(r"[A-Za-z가-힣]+", t):
            continue
        out.append(t)
    return out


def _norm_menu(word: str) -> str:
    m = re.search(_MENU, word)
    core = word[: m.end()] if m else word
    return re.sub(r"(은|는|이|가|을|를)$", "", core)


def _pick_main(tokens: List[str], reserved: set) -> str:
    food = [t for t in tokens if re.search(_MENU, t)]
    if food:
        return _norm_menu(Counter(food).most_common(1)[0][0])
    cand = [t for t in tokens if t not in reserved]
    nouns = [t for t in cand if re.fullmatch(r"[가-힣A-Za-z]{2,}", t)]
    return Counter(nouns).most_common(1)[0][0] if nouns else "이곳"


def keywords_to_sentence(blob: Any) -> str:
    raw = (
        [t.strip() for t in re.sub(r"^이\s+장소는\s*", "", blob).split(",")]
        if isinstance(blob, str) else list(blob)
    )
    tokens = _clean(sum((_split(t) for t in raw), []))

    dishes = [t for t in tokens if re.search(_MENU, t)]
    people = [t for t in tokens if t.endswith(("와", "랑"))]
    tastes = [t for t in tokens if re.fullmatch(_TASTE, t)]
    ambience = [t for t in tokens if t in _AMBIENCE]
    places = [t for t in tokens if t.endswith(("타운", "동", "차이나타운", "식당"))]

    pick = lambda lst: Counter(lst).most_common(1)[0][0] if lst else ""
    reserved = set(sum([dishes, people, tastes, ambience, places], []))

    main = _pick_main(tokens, reserved)
    who, taste, vibe, where = map(pick, (people, tastes, ambience, places))
    taste = taste or "괜찮았습니다"

    parts = [
        f"{where}에서" if where else "",
        f"{who} 함께" if who else "",
        f"{main}을(를) 경험했는데",
        taste,
        f"({vibe} 분위기)" if vibe else "",
        "인 곳이에요.",
    ]
    return " ".join(p for p in parts if p).replace("  ", " ")

# ────────────────────────────────────────────────────────────────
# 4. 메인 추천 함수
# ----------------------------------------------------------------

def recommend(region: str, selection: List[str]) -> pd.DataFrame:  # noqa: C901
    """region(예: '인천역') 기준 추천 테이블 반환."""
    from utils import geocode_region_kakao  # 외부 API 래퍼

    # 1) 기준 좌표
    coords = geocode_region_kakao(region)
    if not coords:
        raise ValueError(f"[geocode] '{region}' 좌표 조회 실패")
    lat0, lon0 = coords

    # 2) 데이터 로드 + 리뷰 처리
    df_main = pd.read_excel(MAIN_FILE)
    df_review = build_review_features(pd.read_csv(REVIEW_FILE, encoding="utf-8"))

    # 3) 리뷰 집계
    key_cols = ["검색어", "장소명", "주소"]

    def merge_kw(series):
        uniq, seen = [], set()
        for lst in series:
            for kw in lst:
                if kw not in seen:
                    seen.add(kw)
                    uniq.append(kw)
        return uniq

    agg = {c: "first" for c in df_review.columns if c not in key_cols + ["keywords"]}
    agg["keywords"] = merge_kw
    df_review = df_review.groupby(key_cols, as_index=False).agg(agg)

    # 4) 테마 필터 + 리뷰 merge
    theme = selection[0].strip()
    df_theme = (
        df_main[df_main["cat1"].str.strip() == theme]
        .merge(df_review[["addr1", "긍정점수", "keywords"]], on="addr1", how="left")
        .drop_duplicates("title")
    )

    # 5) 중심역 → 거리 계산 & Top10 선정
    df_theme["distance"] = df_theme.apply(lambda r: haversine(lat0, lon0, r["mapy"], r["mapx"]), axis=1)
    top10 = (
        df_theme.nsmallest(10, "distance")
        .sort_values("긍정점수", ascending=False)
        .reset_index(drop=True)
    )

    # 6) 후보 pool & NN 모델 (5–10 km within 10 km radius)
    pool = df_theme.drop(top10.index).reset_index(drop=True)
    coords_rad = np.radians(pool[["mapy", "mapx"]].values)
    nn = NearestNeighbors(radius=10 / EARTH_RADIUS, metric="haversine").fit(coords_rad)

    routes: List[Dict[str, Any]] = []
    used: set[int] = set()

    for idx, row in top10.iterrows():
        stage_title = row["title"]
        pt_rad = np.radians([[row["mapy"], row["mapx"]]])
        d_rad, i_idx = nn.radius_neighbors(pt_rad, return_distance=True)
        d_km = d_rad[0] * EARTH_RADIUS

        cand = [(i, dist) for i, dist in zip(i_idx[0], d_km) if 5 <= dist <= 10 and i not in used]
        cand_df = (
            pd.DataFrame(cand, columns=["idx", "dist"])
            .assign(score=lambda d: pool.loc[d["idx"], "긍정점수"].values)
            .sort_values(["score", "dist"], ascending=[False, True])
        )
        rec1_idx = cand_df["idx"].tolist()[:5]
        used.update(rec1_idx)
        rec1_titles = pool.loc[rec1_idx, "title"].tolist()

        # 2차 추천
        rec2_titles: List[str] = []
        if rec1_idx:
            first = pool.loc[rec1_idx[0]]
            pt2_rad = np.radians([[first["mapy"], first["mapx"]]])
            d2_rad, i2_idx = nn.radius_neighbors(pt2_rad, return_distance=True)
            d2_km = d2_rad[0] * EARTH_RADIUS
            cand2 = [(i, dist) for i, dist in zip(i2_idx[0], d2_km) if 5 <= dist <= 10 and i not in used]
            cand2_df = (
                pd.DataFrame(cand2, columns=["idx", "dist"])
                .assign(score=lambda d: pool.loc[d["idx"], "긍정점수"].values)
                .sort_values(["score", "dist"], ascending=[False, True])
            )
            rec2_idx = cand2_df["idx"].tolist()[:5]
            used.update(rec2_idx)
            rec2_titles = pool.loc[rec2_idx, "title"].tolist()

        # 이동수단(간소화) & 정류/역: 실제 필드가 없으면 None 처리
        mode1 = "지하철" if idx % 2 == 0 else "버스"
        mode2 = "버스" if mode1 == "지하철" else "지하철"

        routes.append(
            {
                "추천음식점1": stage_title,
                "이동수단1": mode1,
                "타는곳1": row.get("closest_subway_station") if mode1 == "지하철" else row.get("matched_station_name"),
                "내리는곳1": None,
                "추천음식점2": ", ".join(rec1_titles) or "없음",
                "이동수단2": mode2,
                "타는곳2": None,
                "내리는곳2": None,
                "추천음식점3": ", ".join(rec2_titles) or "없음",
            }
        )

    result = pd.DataFrame(routes)

    # 7) 한 줄 소개 생성
    def collect_kw(titles_str: str) -> List[str]:
        kws: set[str] = set()
        for title in titles_str.split(", "):
            k = df_theme.loc[df_theme["title"] == title, "keywords"]
            if not k.empty and isinstance(k.iloc[0], list):
                kws.update(k.iloc[0])
        return list(kws)

    result["모든키워드"] = result.apply(
        lambda r: collect_kw(", ".join([r["추천음식점1"], r["추천음식점2"], r["추천음식점3"]])), axis=1
    )
    result["한줄소개"] = result["모든키워드"].apply(keywords_to_sentence)

    # 8) 최종 열 순서 정리 & 반환
    cols = [
        "한줄소개",
        "추천음식점1", "이동수단1", "타는곳1", "내리는곳1",
        "추천음식점2", "이동수단2", "타는곳2", "내리는곳2", "추천음식점3",
    ]
    return result[cols] 
