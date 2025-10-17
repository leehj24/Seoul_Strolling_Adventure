# run_transit.py
# -*- coding: utf-8 -*-
import os, re, math, json, threading, requests
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict
import pandas as pd
import numpy as np
import unicodedata as ud
import math
from config import KAKAO_API_KEY
from config import ODSAY_API_KEY
from inputs import *

from concurrent.futures import ThreadPoolExecutor, as_completed

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

    df_sorted.to_csv(fr"{PARENT}\Tour\tour_recommend_{TRANSPORT_FALLBACK}.csv", index=False, encoding="utf-8-sig")
    # =========================
    df_sorted.head(5)

    # -*- coding: utf-8 -*-
    # 일정 생성(카테고리 비율 3·2·1 + 점심/저녁 각 1곳 버킷 + 카페 중복 허용 + 하루 최소 1회 교통편 + Kakao/ODsay)
    # + 하루에 CATS 내 각 카테고리 최소 1개 등장 보장(가능 시)
    # + 일찍 끝나면 마지막 방문 체류를 늘려 END_TIME_STR까지 채움


    CSV_CANDS       = fr"{PARENT}\Tour\tour_recommend_{TRANSPORT_FALLBACK}.csv"

    DAY_VISIT_MIN   = 5
    DAY_VISIT_MAX   = 6

    TOP_N           = 40                                  # 초기 후보 수(크면 느려짐)
    NON_MEAL_MIN_PER_DAY = 3                              # 비음식 최소 확보(가능 시)

    GRID_DEG        = 0.0025
    SUBWAY_RADIUS_M = 900
    BUS_RADIUS_M    = 900
    CONCURRENCY     = 12
    HTTP_TIMEOUT    = 5
    CACHE_PATH      = ".kakao_local_cache.json"

    # 이동시간 추정(ODsay 없을 때)
    BASE_SPEED_KMH  = 18.0
    ADD_FIXED_MIN   = 8.0
    SAME_ST_BONUS   = 10.0
    SAME_LINE_BONUS = 6.0
    SAME_BUS_BONUS  = 5.0

    WALK_SKIP_KM    = 0.30
    WALK_SPEED_KMH  = 4.5

    # ===== 식사 규칙 =====
    MEAL_CAT = "음식"
    MEAL_CUISINE_TAGS = {"서양식","이색음식점","일식","중식","한식"}   # 점심/저녁 각 1곳은 여기서만
    CAFE_DUP_KEYS     = {"카페","전통찻집"}                         # 전역 중복 허용(중복 제거 제외)

    # --------- 유틸 ----------
    def nfc(s): return ud.normalize("NFC", str(s or "")).strip()

    def norm_station(s: str) -> str:
        t = nfc(s)
        t = re.sub(r"\(.*?\)", "", t)
        t = t.replace("역","")
        t = re.sub(r"\s+","", t)
        return t

    def pick_csv():
        if os.path.exists(CSV_CANDS): return CSV_CANDS
        raise FileNotFoundError(f"입력 CSV 없음: {CSV_CANDS}")

    def read_csv_robust(p):
        for enc in ("utf-8","utf-8-sig","cp949"):
            try: return pd.read_csv(p, encoding=enc)
            except Exception: pass
        return pd.read_csv(p)

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
        phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlmb = math.radians(float(lon2) - float(lon1))
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
        return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

    def estimate_transit_minutes(d_km: float, rel: str) -> int:
        base = (d_km / BASE_SPEED_KMH) * 60.0 + ADD_FIXED_MIN
        if rel == "same_subway_station": return max(3, int(round(base - SAME_ST_BONUS)))
        if rel == "same_subway_line":    return max(4, int(round(base - SAME_LINE_BONUS)))
        if rel == "same_bus_station":    return max(5, int(round(base - SAME_BUS_BONUS)))
        return int(round(base))

    def walk_minutes(d_km: float) -> int:
        return max(3, int(round((d_km / max(0.1, WALK_SPEED_KMH)) * 60.0 + 3)))

    def stay_minutes(cat1: str) -> int:
        c = nfc(cat1)
        if c == "음식": return 75
        if c == "자연": return 90
        if c == "레포츠": return 120
        return 90

    def parse_days(s: str) -> int:
        m = re.search(r"(\d+)", str(s))
        d = int(m.group(1)) if m else 1
        return max(1, d)

    # ===== Kakao Local(세션/캐시) =====
    HEADERS = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    _session = requests.Session()
    _session.headers.update(HEADERS)
    _cache_lock = threading.Lock()
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH,"r",encoding="utf-8") as f:
                DISK_CACHE = json.load(f)
        except Exception:
            DISK_CACHE = {}
    else:
        DISK_CACHE = {}

    def save_cache():
        with _cache_lock:
            with open(CACHE_PATH,"w",encoding="utf-8") as f:
                json.dump(DISK_CACHE,f,ensure_ascii=False)

    def tile_key(lat: float, lon: float) -> str:
        return f"{round(lat/GRID_DEG)*GRID_DEG:.6f}|{round(lon/GRID_DEG)*GRID_DEG:.6f}"

    def _get(url: str, params: dict, headers=None) -> Optional[dict]:
        h = headers or _session.headers
        for _ in range(2):
            try:
                r = requests.get(url, params=params, headers=h, timeout=HTTP_TIMEOUT)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
        return None

    def nearest_subway_tile(lat: float, lon: float) -> Tuple[str,str]:
        key = f"subway|{tile_key(lat,lon)}|{SUBWAY_RADIUS_M}"
        if key in DISK_CACHE:
            v = DISK_CACHE[key]; return v.get("name",""), v.get("line","")
        js = _get("https://dapi.kakao.com/v2/local/search/category.json",
                {"category_group_code":"SW8","x":lon,"y":lat,"radius":SUBWAY_RADIUS_M,"size":1,"sort":"distance"},
                headers=HEADERS)
        name, line = "", ""
        if js and js.get("documents"):
            d = js["documents"][0]
            name = nfc(d.get("place_name"))
            raw = " ".join([name, nfc(d.get("category_name","")), nfc(d.get("address_name","")), nfc(d.get("road_address_name",""))])
            m = re.search(r"(\d+)\s*호선", raw)
            line = f"{m.group(1)}호선" if m else ""
        DISK_CACHE[key] = {"name":name,"line":line}
        return name, line

    def _nearest_bus_once(lat: float, lon: float, radius: int, keyword: str) -> str:
        js = _get("https://dapi.kakao.com/v2/local/search/keyword.json",
                {"query":keyword,"x":lon,"y":lat,"radius":radius,"size":10,"sort":"distance"},
                headers=HEADERS)
        if not (js and js.get("documents")): return ""
        docs = sorted(js["documents"], key=lambda d: int(float(d.get("distance","1e9"))))
        for d in docs:
            nm = nfc(d.get("place_name"))
            if ("정류" in nm) or ("버스" in nm) or ("정류장" in nm) or ("정류소" in nm):
                return nm
        return nfc(docs[0].get("place_name"))

    def nearest_bus_tile(lat: float, lon: float) -> str:
        key = f"bus|{tile_key(lat,lon)}|{BUS_RADIUS_M}"
        if key in DISK_CACHE:
            return DISK_CACHE[key]
        rad_seq = [BUS_RADIUS_M, max(700, BUS_RADIUS_M+200), 1200, 1500]
        kw_seq  = ["버스정류장","정류장","버스"]
        name = ""
        for r in rad_seq:
            for kw in kw_seq:
                name = _nearest_bus_once(lat, lon, r, kw)
                if name: break
            if name: break
        DISK_CACHE[key] = name
        return name

    def enrich_transit_hints_fast(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["tile_key"] = [tile_key(lat,lon) for lat,lon in zip(df["lat"],df["lon"])]
        unique_tiles = df["tile_key"].unique().tolist()

        def job_sub(t):
            lat = float(df.loc[df["tile_key"]==t,"lat"].iloc[0])
            lon = float(df.loc[df["tile_key"]==t,"lon"].iloc[0])
            return t, nearest_subway_tile(lat,lon)
        def job_bus(t):
            lat = float(df.loc[df["tile_key"]==t,"lat"].iloc[0])
            lon = float(df.loc[df["tile_key"]==t,"lon"].iloc[0])
            return t, nearest_bus_tile(lat,lon)

        subway_map, bus_map = {}, {}
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
            futs = [ex.submit(job_sub,t) for t in unique_tiles] + [ex.submit(job_bus,t) for t in unique_tiles]
            for fu in as_completed(futs):
                try:
                    t, val = fu.result()
                    if isinstance(val, tuple): subway_map[t] = val
                    else: bus_map[t] = val
                except Exception:
                    pass

        df["closest_subway_station"] = df["tile_key"].map(lambda k: subway_map.get(k,("",""))[0])
        df["closest_subway_line"]    = df["tile_key"].map(lambda k: subway_map.get(k,("",""))[1])
        df["closest_bus_station"]    = df["tile_key"].map(lambda k: bus_map.get(k,""))
        return df.drop(columns=["tile_key"])

    # ===== (선택) ODsay 대중교통 시간 =====
    def transit_minutes_via_odsay(plon, plat, nlon, nlat) -> Optional[int]:
        if not ODSAY_API_KEY: return None
        url = "https://api.odsay.com/v1/api/searchPubTransPathT"
        params = {
            "SX": f"{plon:.6f}", "SY": f"{plat:.6f}",
            "EX": f"{nlon:.6f}", "EY": f"{nlat:.6f}",
            "apiKey": ODSAY_API_KEY, "lang":0, "OPT":0
        }
        try:
            js = _get(url, params, headers=None)
            if js and "result" in js and "path" in js["result"] and js["result"]["path"]:
                info = js["result"]["path"][0].get("info", {})
                tt = info.get("totalTime")
                if isinstance(tt, (int, float)) and tt > 0:
                    return int(tt)
        except Exception:
            pass
        return None

    # ===== 데이터 로드 & 후보 =====
    src = pick_csv()
    df0 = read_csv_robust(src).copy()
    for c in ["title","addr1","cat1","cat2","cat3","lat","lon","review_score","tour_score","distance_km"]:
        if c not in df0.columns: df0[c] = np.nan
    for c in ["lat","lon","review_score","tour_score","distance_km"]:
        if c in df0.columns: df0[c] = pd.to_numeric(df0[c], errors="coerce")
    df0["title"] = df0["title"].map(nfc); df0["addr1"] = df0["addr1"].map(nfc)
    df0 = df0.dropna(subset=["lat","lon"]).reset_index(drop=True)

    score_col = "review_score" if df0["review_score"].dropna().size else ("tour_score" if "tour_score" in df0.columns else None)

    def sort_df(d):
        if score_col:
            cols = [score_col] + (["distance_km"] if "distance_km" in d.columns else [])
            asc  = [False] + ([True] if "distance_km" in d.columns else [])
            return d.sort_values(cols, ascending=asc)
        return d

    df_sorted = sort_df(df0)

    # --- 후보 풀: CATS 각 카테고리 최소 1개(가능 시) 포함 보장 ---
    buckets = []
    cats_order = list(dict.fromkeys(CATS))
    for cat in cats_order:
        sub = df_sorted.loc[df_sorted["cat1"].map(lambda s: nfc(s)==nfc(cat))]
        if not sub.empty:
            buckets.append(sub.head(max(2, TOP_N//10)))  # 각 카테고리에서 소량은 반드시 포함
    # 나머지 상위로 채움
    rest = df_sorted.copy()
    for b in buckets:
        rest = rest.drop(index=b.index, errors="ignore")
    pois = pd.concat(buckets+[rest.head(TOP_N)], ignore_index=True).drop_duplicates(subset=["title","addr1"])
    pois = pois.head(TOP_N).reset_index(drop=True)
    pois = enrich_transit_hints_fast(pois)

    # ===== 라우팅(탐욕) =====
    def step_cost_from(lat, lon, nxt_row):
        d_km = haversine(lat, lon, nxt_row["lat"], nxt_row["lon"])
        s = nxt_row.get(score_col, np.nan)
        bonus = min(0.3, float(s)/100.0) if np.isfinite(s) else 0.0
        return max(0.0, d_km - bonus)

    def greedy_order(rows: pd.DataFrame, start_lat: float, start_lon: float):
        used = set(); order = []
        cur_lat, cur_lon = start_lat, start_lon
        while len(used) < len(rows):
            cand = [i for i in range(len(rows)) if i not in used]
            j = min(cand, key=lambda k: step_cost_from(cur_lat, cur_lon, rows.loc[k]))
            order.append(j); used.add(j)
            cur_lat, cur_lon = float(rows.loc[j,"lat"]), float(rows.loc[j,"lon"])
        return rows.iloc[order].reset_index(drop=True)

    route = greedy_order(pois, float(pois.loc[0,"lat"]), float(pois.loc[0,"lon"]))

    # ===== 교통편 문자열/관계 =====
    def line_station_text(line: str, station: str) -> str:
        line, station = nfc(line), nfc(station)
        if line and (line in station): return station
        return f"{line} {station}".strip() if line else station

    def relation_and_text(prev_row, nxt_row, d_km: float):
        ps_raw, pl = nfc(prev_row.get("closest_subway_station","")), nfc(prev_row.get("closest_subway_line",""))
        ns_raw, nl = nfc(nxt_row.get("closest_subway_station","")), nfc(nxt_row.get("closest_subway_line",""))
        pb, nb = nfc(prev_row.get("closest_bus_station","")), nfc(nxt_row.get("closest_bus_station",""))

        # 한쪽 비었으면 보강
        if pb and not nb: nb = nearest_bus_tile(nxt_row["lat"], nxt_row["lon"])
        if nb and not pb: pb = nearest_bus_tile(prev_row["lat"], prev_row["lon"])

        ps, ns = norm_station(ps_raw), norm_station(ns_raw)

        if ps and ns and ps == ns:                # 같은 역(호선 달라도) → 이동행 생략
            return "same_subway_station", "", ""
        if pb and nb and pb == nb:                # 같은 정류장 → 이동행 생략
            return "same_bus_station", "", ""
        if pl and nl and ps and ns and (pl == nl):# 같은 호선 → 이동행 생략
            return "same_subway_line", "", ""
        if d_km < WALK_SKIP_KM:                   # 가까우면 이동행 생략
            return "walk_hint", "", ""

        if ps_raw and ns_raw and ps != ns:
            t1 = f"지하철 {line_station_text(pl, ps_raw)} 승차".strip()
            t2 = f"{line_station_text(nl, ns_raw)} 하차".strip()
            return "subway_hint", t1, t2
        if pb and nb and pb != nb:
            return "bus_hint", f"버스 {pb} 승차", f"{nb} 하차"

        return "walk_hint", "", ""                # 모호 → 생략

    def possible_transit_hint(prev_row, nxt_row):
        ps_raw, pl = nfc(prev_row.get("closest_subway_station","")), nfc(prev_row.get("closest_subway_line",""))
        ns_raw, nl = nfc(nxt_row.get("closest_subway_station","")), nfc(nxt_row.get("closest_subway_line",""))
        pb, nb = nfc(prev_row.get("closest_bus_station","")), nfc(nxt_row.get("closest_bus_station",""))
        ps, ns = norm_station(ps_raw), norm_station(ns_raw)

        if ps_raw and ns_raw and ps and ns and ps != ns:
            t1 = f"지하철 {line_station_text(pl, ps_raw)} 승차".strip()
            t2 = f"{line_station_text(nl, ns_raw)} 하차".strip()
            return "subway_hint", t1, t2
        if pb and nb and pb != nb:
            return "bus_hint", f"버스 {pb} 승차", f"{nb} 하차"
        return None, "", ""

    def transit_minutes_via_api_or_est(prev_row, nxt_row, rel: str, d_km: float) -> int:
        if rel in {"subway_hint","bus_hint"}:
            tt = transit_minutes_via_odsay(prev_row["lon"], prev_row["lat"], nxt_row["lon"], nxt_row["lat"])
            if isinstance(tt, int) and tt > 0:
                return tt
        return estimate_transit_minutes(d_km, rel)

    # ===== 카테고리 비율(3,2,1)로 일일 쿼터 배분 =====
    def allocate_day_quota(cats, visit_target):
        base_w = [3,2,1] + [1]*(max(0, len(cats)-3))
        w = base_w[:len(cats)]
        S = sum(w)
        ideal = [visit_target * wi / S for wi in w]
        floor_cnt = [int(math.floor(x)) for x in ideal]
        if visit_target >= len(cats):
            for i in range(len(cats)):
                if floor_cnt[i] == 0:
                    floor_cnt[i] = 1
        cur = sum(floor_cnt)
        rem = max(0, visit_target - cur)
        residuals = [(ideal[i] - floor_cnt[i], i) for i in range(len(cats))]
        residuals.sort(reverse=True)
        k = 0
        while rem > 0 and k < len(residuals):
            i = residuals[k][1]
            floor_cnt[i] += 1
            rem -= 1
            k += 1
        return {cats[i]: floor_cnt[i] for i in range(len(cats))}

    def round_robin_pattern_from_quota(quota: dict):
        order = sorted(quota.keys(), key=lambda c: (-quota[c], c))
        max_q = max(quota.values()) if quota else 0
        patt = []
        for i in range(max_q):
            for c in order:
                if quota.get(c,0) > i:
                    patt.append(c)
        return patt

    # 전역/중복 키(카페/전통찻집은 중복 허용)
    def is_cafe_like(tag: str) -> bool:
        s = nfc(tag)
        return any(k in s for k in CAFE_DUP_KEYS)

    def key_title_addr(r): return (nfc(r.get("title","")), nfc(r.get("addr1","")))

    # 하루 풀(비음식 보강)
    def ensure_variety_pool(route_df, start_idx, used_global, want):
        chunk_size = max(want * 6, want)
        chunk = route_df.iloc[start_idx : start_idx + chunk_size].copy()
        if chunk.empty: return chunk

        def used_filter(row):
            if nfc(row.get("cat1","")) == MEAL_CAT and is_cafe_like(row.get("cat3","")):
                return False
            return key_title_addr(row) in used_global

        mask_used = chunk.apply(used_filter, axis=1)
        chunk = chunk.loc[~mask_used].copy()

        is_meal = chunk["cat1"].map(lambda s: nfc(s) == MEAL_CAT)
        non_meal_cnt = int((~is_meal).sum())
        if non_meal_cnt < NON_MEAL_MIN_PER_DAY:
            rest = route_df.iloc[start_idx + chunk_size : ].copy()
            if not rest.empty:
                rest = rest.loc[~rest.apply(used_filter, axis=1)]
                rest_nm = rest.loc[rest["cat1"].map(lambda s: nfc(s) != MEAL_CAT)]
                add_n = NON_MEAL_MIN_PER_DAY - non_meal_cnt
                if add_n > 0 and not rest_nm.empty:
                    chunk = pd.concat([chunk, rest_nm.head(add_n)], ignore_index=True)
        return chunk

    # ===== 하루 스케줄러 =====
    def schedule_day(base: datetime, label: str, day_pool: pd.DataFrame, visit_target: int,
                    meal_enabled: bool, used_titles_global: set):

        def to_dt(hhmm: str) -> datetime:
            h, m = map(int, hhmm.split(":"))
            return base.replace(hour=h, minute=m, second=0, microsecond=0)

        cur_time = base.replace(hour=int(START_TIME_STR[:2]), minute=int(START_TIME_STR[3:5]), second=0, microsecond=0)
        day_end  = base.replace(hour=int(END_TIME_STR[:2]),  minute=int(END_TIME_STR[3:5]),  second=0, microsecond=0)
        lunch_s, lunch_e   = base.replace(hour=11, minute=0), base.replace(hour=13, minute=0)
        dinner_s, dinner_e = base.replace(hour=17, minute=0), base.replace(hour=20, minute=0)

        rows = []
        used_idx = set()
        prev_row = None
        transit_used_today = False

        # --- 쿼터(3,2,1 비율 고정, visit_target에 맞춤) ---
        cats_today = list(dict.fromkeys(CATS))
        quota = allocate_day_quota(cats_today, visit_target)
        quota = {k:int(v) for k,v in quota.items()}

        def already_used_globally(row) -> bool:
            if nfc(row.get("cat1","")) == MEAL_CAT and is_cafe_like(row.get("cat3","")):
                return False
            return key_title_addr(row) in used_titles_global

        def pick_best(sub: pd.DataFrame, ref_lat: float, ref_lon: float):
            if sub.empty: return None
            dkm = np.sqrt((sub["lat"] - ref_lat)**2 + (sub["lon"] - ref_lon)**2) * 111.0
            pen = dkm.apply(lambda x: (x / BASE_SPEED_KMH) * 60.0) / 60.0
            sc = sub.get(score_col, pd.Series([0]*len(sub))).fillna(0) - 0.1 * pen
            idx = sc.sort_values(ascending=False).index[0]
            return idx

        def place_visit(idx: int):
            nonlocal cur_time, prev_row, transit_used_today
            n = day_pool.loc[idx]
            if already_used_globally(n):
                return False

            # 이동 행
            if prev_row is not None:
                d_km = haversine(prev_row["lat"], prev_row["lon"], n["lat"], n["lon"])
                rel, t1, t2 = relation_and_text(prev_row, n, d_km)

                # 아직 교통편 미사용이면, transit 유발 후보를 한 번 우선 탐색
                if (rel in {"same_subway_station","same_bus_station","same_subway_line","walk_hint"}) and (not transit_used_today):
                    best_j, best_sc = None, 1e9
                    for j, r2 in day_pool.iterrows():
                        if j in used_idx: continue
                        if already_used_globally(r2): continue
                        rel2, _, _ = possible_transit_hint(prev_row, r2)
                        if rel2 in {"subway_hint","bus_hint"} and quota.get(nfc(r2.get("cat1","")),0) > 0:
                            sc = step_cost_from(prev_row["lat"], prev_row["lon"], r2)
                            if sc < best_sc:
                                best_sc, best_j = sc, j
                    if best_j is not None:
                        idx = best_j
                        n = day_pool.loc[idx]
                        d_km = haversine(prev_row["lat"], prev_row["lon"], n["lat"], n["lon"])
                        rel, t1, t2 = relation_and_text(prev_row, n, d_km)

                if rel not in {"same_subway_station","same_bus_station","same_subway_line","walk_hint"}:
                    move_min = transit_minutes_via_api_or_est(prev_row, n, rel, d_km)
                    m_end = cur_time + timedelta(minutes=move_min)
                    if m_end > day_end: return False
                    rows.append({
                        "day_label": label, "day": int(label[:-1]),
                        "start_time": cur_time.strftime("%H:%M"), "end_time": m_end.strftime("%H:%M"),
                        "title":"이동","addr1":"","cat1":"","cat2":"","cat3":"",
                        "출발지": nfc(prev_row.get("addr1") or prev_row.get("title")),
                        "교통편1": t1, "교통편2": t2,
                        "도착지": nfc(n.get("addr1") or n.get("title")),
                        "final_score": np.nan, "distance_from_prev_km": round(d_km,2),
                        "move_min": move_min, "stay_min": 0
                    })
                    cur_time = m_end
                    if rel in {"subway_hint","bus_hint"}:
                        transit_used_today = True

            # 방문 행
            smin = stay_minutes(n.get("cat1",""))
            v_end = cur_time + timedelta(minutes=smin)
            if v_end > day_end: return False
            rows.append({
                "day_label": label, "day": int(label[:-1]),
                "start_time": cur_time.strftime("%H:%M"), "end_time": v_end.strftime("%H:%M"),
                "title": nfc(n["title"]), "addr1": nfc(n["addr1"]),
                "cat1": nfc(n["cat1"]), "cat2": nfc(n["cat2"]), "cat3": nfc(n["cat3"]),
                "출발지":"", "교통편1":"", "교통편2":"", "도착지":"",
                "final_score": float(n.get(score_col, np.nan)) if score_col else np.nan,
                "distance_from_prev_km": np.nan, "move_min": 0, "stay_min": smin
            })
            cur_time = v_end
            used_idx.add(idx)
            prev_row = n
            if not (nfc(n.get("cat1","")) == MEAL_CAT and is_cafe_like(n.get("cat3",""))):
                used_titles_global.add(key_title_addr(n))
            return True

        def cuisine_bucket(tag: str):
            s = nfc(tag)
            for k in MEAL_CUISINE_TAGS:
                if s == k or k in s: return k
            syn = [("양식","서양식"),("중화","중식"),("일본","일식")]
            for a,b in syn:
                if a in s: return b
            return None

        def pick_candidate_for_cat(cat_name: str, in_meal_window: bool):
            ref_lat = float(prev_row["lat"]) if prev_row is not None else float(day_pool.iloc[0]["lat"])
            ref_lon = float(prev_row["lon"]) if prev_row is not None else float(day_pool.iloc[0]["lon"])
            sub = day_pool.copy()
            def keep(i, r):
                if i in used_idx: return False
                if already_used_globally(r): return False
                return True
            sub = sub.loc[[keep(i,r) for i,r in day_pool.iterrows()]]
            if sub.empty: return None
            sub = sub.loc[sub["cat1"].map(lambda s: nfc(s) == nfc(cat_name))]
            if sub.empty: return None
            if in_meal_window and nfc(cat_name) == MEAL_CAT:
                sub = sub.loc[sub["cat3"].map(lambda s: (s is not np.nan) and (cuisine_bucket(s) is not None))]
                if sub.empty: return None
            idx = pick_best(sub, ref_lat, ref_lon)
            return idx

        # ---------- ① 오전 씨드: 음식 제외 카테고리(예: 자연, 레포츠) 각 1개 선배치(가능 시) ----------
        non_food_cats = [c for c in cats_today if nfc(c) != MEAL_CAT]
        for c in non_food_cats:
            if quota.get(c,0) <= 0: continue
            if cur_time >= lunch_s: break
            idx = pick_candidate_for_cat(c, in_meal_window=False)
            if idx is not None and place_visit(idx):
                quota[c] -= 1

        # ---------- ② 오전 나머지(음식 제외) ----------
        while cur_time < lunch_s and sum(quota.values()) > 0:
            # 음식은 점심/저녁을 위해 남겨둠
            cat_choices = [c for c in cats_today if quota.get(c,0)>0 and nfc(c)!=MEAL_CAT]
            if not cat_choices: break
            # 남은 쿼터 큰 순으로 시도
            cat_choices.sort(key=lambda x: -quota.get(x,0))
            placed=False
            for c in cat_choices:
                idx = pick_candidate_for_cat(c, in_meal_window=False)
                if idx is not None and place_visit(idx):
                    quota[c] -= 1
                    placed=True
                    break
            if not placed:
                break

        # ---------- ③ 점심(버킷 1곳) ----------
        if meal_enabled and quota.get(MEAL_CAT,0) > 0:
            cur_time = max(cur_time, lunch_s)
            if cur_time < lunch_e:
                idx = pick_candidate_for_cat(MEAL_CAT, in_meal_window=True)
                if idx is not None and place_visit(idx):
                    quota[MEAL_CAT] -= 1

        # ---------- ④ 오후(음식 제외 우선) ----------
        while cur_time < dinner_s and sum(quota.values()) > 0:
            cat_choices = [c for c in cats_today if quota.get(c,0)>0 and nfc(c)!=MEAL_CAT]
            if not cat_choices: break
            cat_choices.sort(key=lambda x: -quota.get(x,0))
            placed=False
            for c in cat_choices:
                idx = pick_candidate_for_cat(c, in_meal_window=False)
                if idx is not None and place_visit(idx):
                    quota[c] -= 1
                    placed=True
                    break
            if not placed:
                break

        # ---------- ⑤ 저녁(버킷 1곳) ----------
        if meal_enabled and quota.get(MEAL_CAT,0) > 0:
            cur_time = max(cur_time, dinner_s)
            if cur_time < dinner_e:
                idx = pick_candidate_for_cat(MEAL_CAT, in_meal_window=True)
                if idx is not None and place_visit(idx):
                    quota[MEAL_CAT] -= 1

        # ---------- ⑥ 저녁 이후(~END) 남은 쿼터 ----------
        while cur_time < day_end and sum(quota.values()) > 0:
            # 남은 것 아무거나(우선순위 큰 순서)
            cat_choices = [c for c in cats_today if quota.get(c,0)>0]
            if not cat_choices: break
            cat_choices.sort(key=lambda x: -quota.get(x,0))
            placed=False
            for c in cat_choices:
                idx = pick_candidate_for_cat(c, in_meal_window=False)
                if idx is not None and place_visit(idx):
                    quota[c] -= 1
                    placed=True
                    break
            if not placed:
                break

        # ---------- ⑦ 일자 카테고리 커버 보정: CATS 각 카테고리 최소 1개 보장(가능 시) ----------
        present = set([nfc(r["cat1"]) for r in rows if r["title"] != "이동"])
        missing = [c for c in cats_today if nfc(c) not in present]
        # 음식 규칙: CATS에 '음식'이 없으면 무시
        if not meal_enabled:
            missing = [c for c in missing if nfc(c) != MEAL_CAT]

        for c in missing:
            if cur_time >= day_end: break
            idx = pick_candidate_for_cat(c, in_meal_window=False if nfc(c)!=MEAL_CAT else True)
            if idx is not None and place_visit(idx):
                pass  # 쿼터 초과라도 강제 1건 허용

        # ---------- ⑧ END_TIME_STR까지 채우기(마지막 방문 체류 연장) ----------
        if rows:
            last_end = to_dt(rows[-1]["end_time"])
            if last_end < day_end:
                k_visit = None
                for k in range(len(rows)-1, -1, -1):
                    if rows[k]["title"] and rows[k]["title"] != "이동":
                        k_visit = k; break
                if k_visit is not None:
                    cur_end_dt = to_dt(rows[k_visit]["end_time"])
                    add_min = int((day_end - cur_end_dt).total_seconds() // 60)
                    if add_min > 0:
                        rows[k_visit]["end_time"] = day_end.strftime("%H:%M")
                        rows[k_visit]["stay_min"] = int(rows[k_visit].get("stay_min",0)) + add_min
                        if k_visit < len(rows)-1:
                            rows[:] = rows[:k_visit+1]

        return rows, len(used_idx)

    # ===== 전체 일정 =====
    def split_visits(total: int, days: int, vmin: int, vmax: int) -> list:
        counts, rem, rem_days = [], total, days
        for _ in range(days):
            if rem_days <= 0: counts.append(0); continue
            target = math.ceil(rem / rem_days)
            target = max(vmin if rem >= vmin else rem, min(target, vmax))
            target = min(target, rem)
            counts.append(target); rem -= target; rem_days -= 1
        return counts

    days_total = parse_days(DAY_STR)
    visit_counts = split_visits(len(route), days_total, DAY_VISIT_MIN, DAY_VISIT_MAX)

    rows_all = []
    pos = 0
    midnight0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    meal_enabled_flag = (MEAL_CAT in set(CATS))
    used_titles_global = set()   # 전역 중복 금지(title+addr1) — 카페/전통찻집은 예외

    for d in range(1, days_total+1):
        base  = midnight0 + timedelta(days=d-1)
        label = f"{d}일"
        want  = visit_counts[d-1] if d-1 < len(visit_counts) else 0
        if want <= 0: break

        pool = ensure_variety_pool(route, pos, used_titles_global, want)
        if pool.empty: break

        day_rows, used = schedule_day(base, label, pool, want, meal_enabled_flag, used_titles_global)
        rows_all.extend(day_rows)
        pos += max(used, 1)

    # 결과 저장
    itinerary = pd.DataFrame(rows_all, columns=[
        "day_label","day","start_time","end_time","title","addr1","cat1","cat2","cat3",
        "출발지","교통편1","교통편2","도착지",
        "final_score","distance_from_prev_km","move_min","stay_min"
    ])

    out_path = fr"{PARENT}\Tour\itinerary_transit_enriched_kakao{TOUR_REGION}.csv"
    itinerary.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[DONE] {out_path} | rows={len(itinerary)} | days={days_total}")
    if not itinerary.empty:
        print(itinerary.groupby(['day_label','cat1']).size())
        print("\nPreview:")
        print(itinerary.head(12))
