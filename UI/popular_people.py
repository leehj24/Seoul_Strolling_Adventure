import os
import pandas as pd
import numpy as np
import matplotlib
# non-GUI 백엔드로 설정
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tour_recommend import tour
from scipy.interpolate import make_interp_spline
import difflib
from math import radians, sin, cos, sqrt, asin
from sqlalchemy import create_engine
import pymysql

# 한글 폰트 설정 (Windows 예시)
plt.rc('font', family='Malgun Gothic')
plt.rcParams['axes.unicode_minus'] = False

# ————————————————————————————————
# 1) DB 연결 및 테이블 로드
# ————————————————————————————————

def people(region,main_theme):
    host     = 'localhost'
    user     = 'root'
    password = '0000'
    database = 'df_region'
    engine   = create_engine(f"mysql+pymysql://{user}:{password}@{host}/{database}")

    df_busy   = pd.read_sql('busy_table', con=engine)
    df_region = pd.read_sql('excel_table', con=engine)

    # 추천 함수 임포트 및 실행
    result = tour(region, main_theme)

    # ————————————————————————————————
    # 2) 장소명 Fuzzy Matching
    # ————————————————————————————————
    titles         = df_region['title'].tolist()
    titles_nospace = [t.replace(" ", "") for t in titles]
    title_map      = dict(zip(titles_nospace, titles))

    def fuzzy_match(token, titles, titles_nospace, title_map, cutoff=0.6):
        nospace = token.replace(" ", "")
        if nospace in title_map:
            return title_map[nospace]
        m = difflib.get_close_matches(nospace, titles_nospace, n=1, cutoff=cutoff)
        if m:
            return title_map[m[0]]
        m = difflib.get_close_matches(token, titles, n=1, cutoff=cutoff)
        return m[0] if m else None

    records = []
    for idx, row in result.iterrows():
        for col in ['추천장소2', '추천장소3']:
            for token in str(row[col]).split(','):
                token = token.strip()
                if not token:
                    continue
                match = fuzzy_match(token, titles, titles_nospace, title_map, cutoff=0.5)
                if match:
                    r = df_region[df_region['title'] == match].iloc[0]
                    lon, lat = r['mapx'], r['mapy']
                else:
                    lon = lat = np.nan
                records.append({
                    'row_index': idx,
                    'place': token,
                    'matched_title': match,
                    'lon': lon,
                    'lat': lat
                })

    df_matched = pd.DataFrame(records)

    # ————————————————————————————————
    # 3) Haversine 함수 및 전처리
    # ————————————————————————————————
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return 2 * R * asin(sqrt(a))

    # 혼잡도 숫자 매핑
    level_map = {'여유':1, '보통':2, '붐빔':3, '매우 붐빔':4}
    df_busy['level_num'] = df_busy['final_level'].map(level_map)

    # 읍면동별 대표 좌표
    dong_coords = df_busy[['시군구','읍면동','latitude','longitude']].drop_duplicates()

    # 시간대 순서 정의
    time_order = sorted(df_busy['시간대'].unique(), key=lambda s: int(s.replace('시','')))

    # ————————————————————————————————
    # 4) 각 추천 세트별 시간대 평균 혼잡도 & 스플라인 스무딩 플롯
    # ————————————————————————————————
    output_dir = 'plots'
    os.makedirs(output_dir, exist_ok=True)

    for idx, group in df_matched.groupby('row_index'):
        # 4-1) 매칭된 읍면동 리스트 생성
        dong_list = []
        for _, item in group.iterrows():
            if pd.isna(item['lon']):
                continue
            dists = dong_coords.apply(
                lambda x: haversine(item['lat'], item['lon'], x['latitude'], x['longitude']),
                axis=1
            )
            nearest = dong_coords.loc[dists.idxmin()]
            dong_list.append((nearest['시군구'], nearest['읍면동']))
        if not dong_list:
            continue

        # 4-2) 시간대별 평균 혼잡도 계산
        df_sub   = df_busy[df_busy[['시군구','읍면동']].apply(tuple, axis=1).isin(dong_list)]
        df_pivot = df_sub.groupby('시간대')['level_num'].mean().reindex(time_order)

        # 4-3) 스플라인 스무딩
        hours      = np.array([int(t.replace('시','')) for t in time_order])
        raw_vals   = df_pivot.values
        spline     = make_interp_spline(hours, raw_vals, k=3)
        hours_new  = np.linspace(hours.min(), hours.max(), 200)
        smooth_vals= spline(hours_new)

        # 4-4) 플롯 생성 및 저장
        plt.figure(figsize=(8,4))
        plt.plot(hours_new, smooth_vals, color='gray', linewidth=2)
        plt.xticks(hours, time_order, rotation=45)
        plt.xlabel('시간대')
        plt.ylabel('평균 혼잡도 레벨')
        plt.title(f'Row {idx}: 시간대별 평균 혼잡도 (Spline)')
        plt.tight_layout()
        save_path = os.path.join(output_dir, f'row_{idx}_spline2.png')
        plt.savefig(save_path, dpi=150)
        plt.close()
        print(f">> Saved plot for row {idx}: {save_path}")

# print(people("서울", ["음식", "자연"]))