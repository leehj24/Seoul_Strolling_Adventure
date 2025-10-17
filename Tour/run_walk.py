# run_walk.py
# -*- coding: utf-8 -*-
import os, re, math, json, requests
from datetime import datetime, timedelta
from typing import Optional, Tuple
import pandas as pd
import numpy as np
import unicodedata as ud
import math
from config import KAKAO_API_KEY
from inputs import *

def run():

    def geocode_region_kakao(region_name: str) -> Optional[Tuple[float, float]]:
        """
        카카오맵 키워드 검색으로 region_name의 위·경도를 조회.
        결과 없으면 None 반환.
        """
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
        params  = {"query": region_name}
        resp    = requests.get(url, headers=headers, params=params)
        docs    = resp.json().get("documents", [])
        if not docs:
            return None
        first = docs[0]
        return float(first["y"]), float(first["x"])  # (lat, lon)


    def read_csv_robust(path: str) -> pd.DataFrame:
        for enc in ("utf-8", "utf-8-sig", "cp949"):
            try:
                return pd.read_csv(path, encoding=enc)
            except Exception:
                pass
        return pd.read_csv(path)

    def haversine(lat1, lon1, lat2, lon2) -> float:
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
        return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))


    # =========================
    # 지오코딩
    # =========================
    coords = geocode_region_kakao(TOUR_REGION)
    if not coords:
        raise ValueError(f"[geocode] '{TOUR_REGION}' 위·경도 조회 실패")
    lat, lon = coords

    # =========================
    # CSV 로드 (원본 보존 + 표준명 리네임)
    # =========================
    tmf = read_csv_robust(PATH_TMF)
    cols_lower = {c.lower(): c for c in tmf.columns}

    need = {
        "title": cols_lower.get("title"),
        "addr1": cols_lower.get("addr1"),
        "cat1":  cols_lower.get("cat1") or next((c for c in tmf.columns if "cat1" in c.lower()), None),
        "mapx":  cols_lower.get("mapx") or cols_lower.get("lon") or cols_lower.get("longitude") or cols_lower.get("x"),
        "mapy":  cols_lower.get("mapy") or cols_lower.get("lat") or cols_lower.get("latitude") or cols_lower.get("y"),
        "tour_score": cols_lower.get("tour_score"),
        "review_score": cols_lower.get("review_score"),
    }
    missing = [k for k, v in need.items() if v is None]
    if missing:
        raise KeyError(f"필수 컬럼 누락: {missing} / 실제: {list(tmf.columns)}")

    df = tmf.rename(columns={
        need["title"]: "title",
        need["addr1"]: "addr1",
        need["cat1"]:  "cat1",
        need["mapx"]:  "lon",           # mapx=경도
        need["mapy"]:  "lat",           # mapy=위도
        need["tour_score"]: "tour_score",
        need["review_score"]: "review_score",
    }).copy()

    # 숫자화 + 좌표 결측 제거
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["tour_score"]   = pd.to_numeric(df["tour_score"], errors="coerce")
    df["review_score"] = pd.to_numeric(df["review_score"], errors="coerce")
    df = df.dropna(subset=["lat","lon"]).copy()

    # =========================
    # 반경/거리 필터
    # =========================
    radius_km = 5 if TRANSPORT_FALLBACK == "walk" else 20
    df["distance_km"] = df.apply(lambda r: haversine(lat, lon, r["lat"], r["lon"]), axis=1)
    df = df[df["distance_km"] <= radius_km].copy()
    if df.empty:
        raise RuntimeError("반경 내 후보가 없습니다. 반경/지역/카테고리를 확인하세요.")

    # =========================
    # 정렬 기준: SCORE_NAME 첫 항목만 사용 (가중치 제거)
    # =========================
    score_map = {"관광지수": "tour_score", "인기도지수": "review_score"}
    if not SCORE_NAME:
        selected_score_label = "관광지수"
    else:
        selected_score_label = SCORE_NAME[0]

    if selected_score_label not in score_map:
        raise ValueError(f"지원하지 않는 SCORE_NAME: {selected_score_label}. 허용: {list(score_map.keys())}")

    selected_col = score_map[selected_score_label]

    # (title, addr1) 중복 제거 전 정렬: 점수 desc, 거리 asc
    pool = df.sort_values([selected_col, "distance_km"], ascending=[False, True]).copy()
    pool = pool.drop_duplicates(subset=["title", "addr1"], keep="first").reset_index(drop=True)

    # =========================
    # 선택 카테고리만 우선 채우기
    # =========================
    if CATS:
        df_sorted = pool[pool["cat1"].isin(CATS)].copy()
    else:
        df_sorted = pool.copy()

    df_sorted = df_sorted.sort_values([selected_col, "distance_km"], ascending=[False, True]).reset_index(drop=True)
    df_sorted["is_fallback"] = False
    df_sorted["fallback_for"] = pd.NA

    # =========================
    # 특정 카테고리가 '아예 없으면' → 가까운 5개로 보충
    # =========================
    for cat in CATS:
        exist_cnt = (df_sorted["cat1"] == cat).sum()
        if exist_cnt == 0:
            remain = pool.loc[~pool.index.isin(df_sorted.index)]
            fb = remain.sort_values(["distance_km", selected_col], ascending=[True, False]).head(FALLBACK_N).copy()
            if not fb.empty:
                fb["is_fallback"] = True
                fb["fallback_for"] = cat
                df_sorted = pd.concat([df_sorted, fb], ignore_index=True)

    # 정렬 재적용: 보충 아님 우선, 높은 점수, 가까운 순
    df_sorted = df_sorted.sort_values(["is_fallback", selected_col, "distance_km"],
                                    ascending=[True, False, True]).reset_index(drop=True)

    # =========================
    # 메타데이터/컬럼 순서
    # =========================
    df_sorted.insert(0, "day", DAY_STR)
    df_sorted.insert(1, "tour_region", TOUR_REGION)
    df_sorted.insert(2, "transport_mode", TRANSPORT_FALLBACK)
    df_sorted.insert(3, "radius_km", radius_km)
    df_sorted.insert(4, "region_center_lat", lat)
    df_sorted.insert(5, "region_center_lon", lon)

    # ⚠️ selected_col은 빼세요 (중복 방지)
    cols_order = [
        "day","tour_region","transport_mode","radius_km","region_center_lat","region_center_lon",
        "title","addr1","cat1","cat2","cat3",
        "tour_score","review_score",
        "distance_km","lat","lon"
    ]

    # 존재하는 컬럼만 추리고, 남은 컬럼 뒤에 붙이기
    cols_order = [c for c in cols_order if c in df_sorted.columns] + \
                [c for c in df_sorted.columns if c not in cols_order]

    # 👇 중복 제거(순서 유지)
    cols_order = list(dict.fromkeys(cols_order))
    df_sorted = df_sorted.loc[:, cols_order].copy()

    candidates = df_sorted.copy()
    df = candidates.copy()

    MEAL_CAT = "음식"                    # 식사 윈도우 기준(있을 때만 적용)
    DAY_TOTAL_SLOTS = 6
    BASE_WEIGHTS = [3, 2, 1]             # CATS[0], CATS[1], CATS[2] 순서로 적용

    # 식당 윈도우 제약
    BLOCKED_CAFE_KEYS = {"카페", "전통찻집"}            # 부분일치 금지
    MEAL_CUISINE_TAGS = {"서양식", "이색음식점", "일식", "중식", "한식"}

    # ====== 유틸 ======
    def read_csv_kr(path: str) -> pd.DataFrame:
        for enc in ("utf-8", "utf-8-sig", "cp949"):
            try:
                return pd.read_csv(path, encoding=enc)
            except Exception:
                pass
        return pd.read_csv(path)

    def is_blocked_cafe_tag(tag: str) -> bool:
        s = ud.normalize("NFC", str(tag or "")).strip()
        return any(key in s for key in BLOCKED_CAFE_KEYS)

    def cuisine_bucket(tag: str):
        """cat3_norm에서 MEAL_CUISINE_TAGS 버킷 추출(정확/부분일치). 없으면 None."""
        s = ud.normalize("NFC", str(tag or "")).strip()
        for k in MEAL_CUISINE_TAGS:
            if s == k or k in s:
                return k
        return None

    def travel_minutes(d_km: float, mode: str) -> float:
        if not np.isfinite(d_km):
            return 15.0
        speed_kmh = 4.5 if mode == "walk" else 18.0  # 대중교통+도보 혼합 가정
        return max(5.0, (d_km / speed_kmh) * 60.0)

    def stay_minutes(cat_norm: str) -> float:
        if len(CATS) >= 1 and cat_norm == CATS[0]: return 75.0
        if len(CATS) >= 2 and cat_norm == CATS[1]: return 90.0
        if len(CATS) >= 3 and cat_norm == CATS[2]: return 120.0
        return 90.0

    def pick_best(sub: pd.DataFrame, cur_lat: float, cur_lon: float, mode: str):
        """이동패널티 반영 랭킹(final_score - 0.1*pen) 최대값 선택"""
        if sub.empty:
            return None, None
        dkm = np.sqrt((sub["lat"] - cur_lat)**2 + (sub["lon"] - cur_lon)**2) * 111.0
        pen = (dkm.apply(lambda x: travel_minutes(x, mode))) / 60.0  # 시간(시간단위)
        rank = sub["final_score"].fillna(0) - 0.1 * pen
        idx = rank.sort_values(ascending=False).index[0]
        return idx, float(dkm.loc[idx])

    def build_day_quota(cats):
        cats = list(dict.fromkeys(cats))
        quotas = {cat: 0 for cat in cats}
        for i, w in enumerate(BASE_WEIGHTS):
            if i < len(cats):
                quotas[cats[i]] += w
        # 총합 보정(6 유지)
        remain = DAY_TOTAL_SLOTS - sum(quotas.values())
        i = 0
        while remain > 0 and cats:
            quotas[cats[i % len(cats)]] += 1
            remain -= 1
            i += 1
        return quotas

    def _best_fit_for_cat(cat, remain, cur_lat, cur_lon, cur_time,
                        gap_start, gap_end, mode,
                        stay_override=None, forbid_meal_cuisine=False):
        """해당 cat에서 지금 배치 가능한 최상 후보(시간 내 종료). 20시 이후 식사 금지 옵션 지원."""
        sub = remain[remain["cat1_norm"] == cat]
        if forbid_meal_cuisine and cat == MEAL_CAT:
            sub = sub[~sub["cat3_norm"].apply(lambda s: cuisine_bucket(s) is not None)]
        if sub.empty:
            return None
        idx, d_km = pick_best(sub, cur_lat, cur_lon, mode)
        if idx is None:
            return None
        t_mv  = travel_minutes(d_km, mode) + 10.0
        t_sty = stay_minutes(cat) if stay_override is None else float(stay_override)
        start_time = max(cur_time + timedelta(minutes=t_mv), gap_start)
        end_time   = start_time + timedelta(minutes=t_sty)
        if end_time > gap_end:
            return None
        return (idx, d_km, start_time, end_time)

    def _round_robin_pattern(quotas, allowed):
        pattern = []
        max_q = max((quotas.get(c,0) for c in allowed), default=0)
        for i in range(max_q):
            for c in allowed:
                if quotas.get(c,0) > i:
                    pattern.append(c)
        return pattern

    def schedule_gap(gap_start: datetime, gap_end: datetime,
                    remain: pd.DataFrame, cur_lat: float, cur_lon: float, cur_time: datetime,
                    quotas: dict, mode: str, allowed_cats:list,
                    stay_override_map=None, forbid_meal_cuisine=False):
        """
        gap [gap_start, gap_end) 채우기.
        - 라운드로빈 패턴으로 카테고리 인터리브 → 쏠림 방지
        - forbid_meal_cuisine=True이면 cat1='음식'의 MEAL_CUISINE_TAGS 전부 배제
        """
        rows = []
        cur_time = max(cur_time, gap_start)

        allowed = [c for c in allowed_cats if quotas.get(c, 0) > 0]
        if not allowed:
            return rows, remain, cur_lat, cur_lon, cur_time

        pattern = _round_robin_pattern(quotas, allowed)
        if not pattern:
            return rows, remain, cur_lat, cur_lon, cur_time

        pi = 0
        while cur_time < gap_end and any(quotas.get(c,0) > 0 for c in allowed) and not remain.empty:
            placed = False
            tried = 0
            while tried < len(pattern):
                cat = pattern[pi % len(pattern)]
                pi += 1
                tried += 1
                if quotas.get(cat, 0) <= 0:
                    continue

                stay_override = None
                if stay_override_map and cat in stay_override_map:
                    stay_override = stay_override_map[cat]

                fit = _best_fit_for_cat(cat, remain, cur_lat, cur_lon, cur_time,
                                        gap_start, gap_end, mode,
                                        stay_override=stay_override,
                                        forbid_meal_cuisine=forbid_meal_cuisine)
                if fit is None:
                    continue

                idx, d_km, start_time, end_time = fit
                row = remain.loc[idx]

                rows.append({
                    "start_time": start_time.time().strftime("%H:%M"),
                    "end_time": end_time.time().strftime("%H:%M"),
                    "title": row.get("title",""),
                    "addr1": row.get("addr1",""),
                    "cat1": row.get("cat1",""),
                    "cat2": row.get("cat2",""),
                    "cat3": row.get("cat3",""),
                    "final_score": float(row.get("final_score", np.nan)),
                    "distance_from_prev_km": round(d_km, 2) if np.isfinite(d_km) else np.nan,
                    "move_min": int(travel_minutes(d_km, mode) + 10.0),
                    "stay_min": int(stay_minutes(cat) if stay_override is None else stay_override),
                })

                quotas[cat] -= 1
                cur_time = end_time
                cur_lat, cur_lon = float(row.get("lat", cur_lat)), float(row.get("lon", cur_lon))
                remain = remain.drop(index=idx)
                placed = True
                break

            if not placed:
                break
        return rows, remain, cur_lat, cur_lon, cur_time

    def schedule_meal_window(window_start: datetime, window_end: datetime,
                            remain: pd.DataFrame, cur_lat: float, cur_lon: float, cur_time: datetime,
                            mode: str, meal_quota_left: int):
        """
        음식 전용 윈도우(점심/저녁) 배치:
        - cat1='음식'만
        - cat3: 카페/전통찻집 류 금지(부분일치)
        - cat3 ∈ MEAL_CUISINE_TAGS 는 윈도우당 '최대 1개'
        """
        rows = []
        cur_time = max(cur_time, window_start)
        if meal_quota_left <= 0:
            return rows, remain, cur_lat, cur_lon, max(cur_time, window_end)

        bucket_used = False
        skip_idxs = set()
        placed_count = 0

        while cur_time < window_end and placed_count < meal_quota_left:
            mask_food    = (remain["cat1_norm"] == MEAL_CAT)
            mask_blocked = remain["cat3_norm"].apply(is_blocked_cafe_tag)
            mask_cuisine = remain["cat3_norm"].apply(lambda s: cuisine_bucket(s) is not None)

            cond = mask_food & (~mask_blocked)
            if bucket_used:
                cond = cond & (~mask_cuisine)   # 1차 차단

            sub = remain[cond & (~remain.index.isin(skip_idxs))]
            if sub.empty:
                break

            idx, d_km = pick_best(sub, cur_lat, cur_lon, mode)
            if idx is None:
                break

            row = remain.loc[idx]
            # 2차 차단(실제 선택 직전)
            c_bucket = cuisine_bucket(row.get("cat3_norm"))
            if bucket_used and (c_bucket is not None):
                skip_idxs.add(idx)
                continue

            t_mv  = travel_minutes(d_km, mode) + 10.0
            t_sty = stay_minutes(MEAL_CAT)

            start_time = max(cur_time + timedelta(minutes=t_mv), window_start)
            end_time   = start_time + timedelta(minutes=t_sty)
            if end_time > window_end:
                skip_idxs.add(idx)
                if remain[cond & (~remain.index.isin(skip_idxs))].empty:
                    break
                continue

            rows.append({
                "start_time": start_time.time().strftime("%H:%M"),
                "end_time": end_time.time().strftime("%H:%M"),
                "title": row.get("title",""),
                "addr1": row.get("addr1",""),
                "cat1": row.get("cat1",""),
                "cat2": row.get("cat2",""),
                "cat3": row.get("cat3",""),
                "final_score": float(row.get("final_score", np.nan)),
                "distance_from_prev_km": round(d_km, 2) if np.isfinite(d_km) else np.nan,
                "move_min": int(t_mv),
                "stay_min": int(t_sty),
            })

            if c_bucket is not None:
                bucket_used = True

            placed_count += 1
            cur_time = end_time
            cur_lat, cur_lon = float(row.get("lat", cur_lat)), float(row.get("lon", cur_lon))
            remain = remain.drop(index=idx)

        return rows, remain, cur_lat, cur_lon, max(cur_time, window_end)

    # ====== 파라미터 해석 ======
    m = re.search(r"(\d+)", str(DAY_STR))
    days = int(m.group(1)) if m else 2
    days = max(1, min(7, days))  # 1~7일

    tour_region    = str(df.get("tour_region", pd.Series([TOUR_REGION])).iloc[0]) \
                        if "tour_region" in df.columns else TOUR_REGION
    transport_mode = str(df.get("transport_mode", pd.Series([TRANSPORT_FALLBACK])).iloc[0]) \
                        if "transport_mode" in df.columns else TRANSPORT_FALLBACK

    # ====== 컬럼/타입 정리 ======
    req_cols = ["title","addr1","cat1","cat2","cat3","lat","lon","final_score","distance_km"]
    for c in req_cols:
        if c not in df.columns:
            df[c] = np.nan

    num_cols = ["final_score","distance_km","lat","lon","tour_score","review_score"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # final_score 보강: 없거나 전부 NaN이면 review_score > tour_score 순으로 대체
    if "final_score" not in df.columns or df["final_score"].dropna().empty:
        if "review_score" in df.columns and not df["review_score"].dropna().empty:
            df["final_score"] = pd.to_numeric(df["review_score"], errors="coerce").fillna(0.0)
        elif "tour_score" in df.columns and not df["tour_score"].dropna().empty:
            df["final_score"] = pd.to_numeric(df["tour_score"], errors="coerce").fillna(0.0)
        else:
            df["final_score"] = 0.0

    # 좌표 중심
    center_lat = float(df.get("region_center_lat", pd.Series([np.nan])).iloc[0]) if "region_center_lat" in df.columns else np.nan
    center_lon = float(df.get("region_center_lon", pd.Series([np.nan])).iloc[0]) if "region_center_lon" in df.columns else np.nan
    if not np.isfinite(center_lat) or not np.isfinite(center_lon):
        center_lat = float(df["lat"].mean())
        center_lon = float(df["lon"].mean())

    # 정규화 컬럼
    df["cat1"] = df["cat1"].astype(str)
    df["cat3"] = df["cat3"].astype(str)
    df["cat1_norm"] = df["cat1"].map(lambda s: ud.normalize("NFC", s).strip())
    df["cat3_norm"] = df["cat3"].map(lambda s: ud.normalize("NFC", s).strip())

    # 정렬 및 중복 제거
    df = df.sort_values(["final_score","distance_km"], ascending=[False, True])
    df = df.drop_duplicates(subset=["title","addr1"], keep="first").reset_index(drop=True)

    # ====== 워킹 풀 ======
    selected_pool = df[df["cat1_norm"].isin(CATS)].copy()
    if selected_pool.empty:
        selected_pool = df.copy()  # 안전장치

    # ====== N일 일정 ======
    itins = []
    cur_lat, cur_lon = center_lat, center_lon
    remain_pool = selected_pool.copy()

    today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    meal_enabled = (MEAL_CAT in CATS)

    for d in range(1, days + 1):
        base = today0 + timedelta(days=d-1)
        day_start  = base.replace(hour=8,  minute=0)
        lunch_s, lunch_e   = base.replace(hour=11, minute=0), base.replace(hour=13, minute=0)
        dinner_s, dinner_e = base.replace(hour=17, minute=0), base.replace(hour=20, minute=0)  # 17~20
        day_end    = base.replace(hour=22, minute=30)

        quotas = build_day_quota(CATS)  # {'음식':3,'자연':2,'레포츠':1}
        cur_time = day_start
        day_rows = []

        # (선점) CATS[2] 오전 우선 1개 시도
        if len(CATS) >= 3 and quotas.get(CATS[2], 0) > 0:
            pre_q = quotas[CATS[2]]
            quotas[CATS[2]] = 1
            rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
                day_start, lunch_s, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
                allowed_cats=[CATS[2]]
            )
            used_pre = 1 - quotas[CATS[2]]
            quotas[CATS[2]] = pre_q - used_pre
            for r in rows: r["day"] = d
            day_rows.extend(rows)

        # 1) 오전 [08:00, 11:00) — 음식 제외(있을 때)
        allowed_morning = [c for c in CATS if (not meal_enabled) or (c != MEAL_CAT)]
        rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
            day_start, lunch_s, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
            allowed_cats=allowed_morning if allowed_morning else CATS
        )
        for r in rows: r["day"] = d
        day_rows.extend(rows)

        # 2) 점심 [11:00, 13:00)
        if meal_enabled:
            lunch_rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_meal_window(
                lunch_s, lunch_e, remain_pool, cur_lat, cur_lon, cur_time, transport_mode,
                meal_quota_left=max(0, quotas.get(MEAL_CAT, 0))
            )
            for r in lunch_rows: r["day"] = d
            day_rows.extend(lunch_rows)
            quotas[MEAL_CAT] = max(0, quotas.get(MEAL_CAT, 0) - len(lunch_rows))
        else:
            allowed = [c for c in CATS if quotas.get(c,0)>0]
            rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
                lunch_s, lunch_e, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
                allowed_cats=allowed if allowed else CATS
            )
            for r in rows: r["day"] = d
            day_rows.extend(rows)

        # 3) 오후 (13:00, 17:00) — 음식 제외(있을 때)
        allowed_afternoon = [c for c in CATS if (not meal_enabled) or (c != MEAL_CAT)]
        rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
            lunch_e, dinner_s, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
            allowed_cats=allowed_afternoon if allowed_afternoon else CATS
        )
        for r in rows: r["day"] = d
        day_rows.extend(rows)

        # 4) 저녁 [17:00, 20:00)
        if meal_enabled:
            dinner_rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_meal_window(
                dinner_s, dinner_e, remain_pool, cur_lat, cur_lon, cur_time, transport_mode,
                meal_quota_left=max(0, quotas.get(MEAL_CAT, 0))
            )
            for r in dinner_rows: r["day"] = d
            day_rows.extend(dinner_rows)
            quotas[MEAL_CAT] = max(0, quotas.get(MEAL_CAT, 0) - len(dinner_rows))
        else:
            allowed = [c for c in CATS if quotas.get(c,0)>0]
            rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
                dinner_s, dinner_e, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
                allowed_cats=allowed if allowed else CATS
            )
            for r in rows: r["day"] = d
            day_rows.extend(rows)

        # 5) 저녁 이후 [20:00, 22:30]
        # 5-1) CATS[2] 우선 1개 시도
        if len(CATS) >= 3 and quotas.get(CATS[2], 0) > 0:
            pre_q = quotas[CATS[2]]
            quotas[CATS[2]] = 1
            rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
                dinner_e, day_end, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
                allowed_cats=[CATS[2]]
            )
            used_first = 1 - quotas[CATS[2]]
            quotas[CATS[2]] = pre_q - used_first
            for r in rows: r["day"] = d
            day_rows.extend(rows)

        # 5-1b) 그래도 CATS[2] 없으면 체류 90분 완화 재시도
        if len(CATS) >= 3 and not any(r.get("cat1") == CATS[2] for r in day_rows) and quotas.get(CATS[2],0) > 0:
            pre_q = quotas[CATS[2]]
            quotas[CATS[2]] = 1
            rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
                dinner_e, day_end, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
                allowed_cats=[CATS[2]],
                stay_override_map={CATS[2]: 90.0}
            )
            used_second = 1 - quotas[CATS[2]]
            quotas[CATS[2]] = pre_q - used_second
            for r in rows: r["day"] = d
            day_rows.extend(rows)

        # 5-2) 남은 쿼터 채우기(20시 이후 MEAL_CUISINE_TAGS 금지)
        allowed_evening = [c for c in CATS if quotas.get(c, 0) > 0]
        rows, remain_pool, cur_lat, cur_lon, cur_time = schedule_gap(
            dinner_e, day_end, remain_pool, cur_lat, cur_lon, cur_time, quotas, transport_mode,
            allowed_cats=allowed_evening if allowed_evening else CATS,
            forbid_meal_cuisine=True
        )
        for r in rows: r["day"] = d
        day_rows.extend(rows)

        # 일자 정렬
        day_df = pd.DataFrame(day_rows)
        if not day_df.empty:
            day_df = day_df.sort_values(["start_time"]).reset_index(drop=True)
        itins.append(day_df)

    # 합치기
    itinerary = pd.concat(itins, ignore_index=True) if itins else pd.DataFrame(
        columns=["day","start_time","end_time","title","addr1","cat1","cat2","cat3",
                "final_score","distance_from_prev_km","move_min","stay_min"]
    )

    # 저장
    out_path = fr"{PARENT}\Tour\itinerary_{tour_region}.csv"
    itinerary.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[DONE] {out_path} (rows={len(itinerary)}, days={days}, mode={transport_mode})")
    if not itinerary.empty:
        print("\n[Per-day counts by cat1]")
        print(itinerary.groupby(["day","cat1"]).size())
