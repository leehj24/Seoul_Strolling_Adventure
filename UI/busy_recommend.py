import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import make_interp_spline
from math import radians, sin, cos, sqrt, asin
from sqlalchemy import create_engine
from utils import geocode_region_kakao, compute_scores
import pymysql
import matplotlib 
import matplotlib.pyplot as plt
matplotlib.use('Agg')

EARTH_RADIUS = 6371.0  # 지구 반지름 km

def haversine(lat1, lon1, lat2, lon2):
    """두 좌표 간 대원거리(km) 계산"""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * asin(sqrt(a))

def busy(region: str) -> plt.Figure:
    """region을 받아서 가장 가까운 읍면동 혼잡도 plot 반환"""
    # 한글 폰트 설정
    plt.rc('font', family='Malgun Gothic')
    plt.rcParams['axes.unicode_minus'] = False

    # 1) region → 위경도 변환
    coords = geocode_region_kakao(region)  # 너가 따로 구현해놓은 함수
    if not coords:
        raise ValueError(f"[geocode] '{region}' 위·경도 조회 실패")
    station_lat, station_lon = coords

    # 2) MySQL 데이터베이스 연결
    host = 'localhost'
    user = 'root'
    password = '0000'
    database = 'df_region'
    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}/{database}")

    # 3) 테이블 불러오기
    table_busy = 'busy_table'
    df_busy = pd.read_sql(table_busy, con=engine)

    # 4) 가장 가까운 읍면동 찾기
    df_busy["distance"] = df_busy.apply(lambda row: haversine(station_lat, station_lon, row["latitude"], row["longitude"]), axis=1)
    closest_area = df_busy.loc[df_busy["distance"].idxmin(), "읍면동"]

    # 5) 가장 가까운 읍면동의 시간대별 데이터 정리
    closest_df = df_busy[df_busy["읍면동"] == closest_area].sort_values(by="시간대")
    time_labels = closest_df["시간대"].str.replace('시', '').astype(int)

    level_map = {'여유': 1, '보통': 2, '붐빔': 3, '매우 붐빔': 4}
    levels_numeric = closest_df["final_level"].map(level_map)

    # 6) 스플라인 보간으로 부드럽게
    x_smooth = np.linspace(time_labels.min(), time_labels.max(), 300)
    spl = make_interp_spline(time_labels, levels_numeric, k=3)
    y_smooth = spl(x_smooth)

    # 7) plot 그리기
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x_smooth, y_smooth, linestyle='-', linewidth=2, color='dimgray')
    ax.set_xticks(np.arange(0, 24))
    ax.set_xticklabels([f'{i:02d}시' for i in range(24)], rotation=45)
    ax.set_yticks([1, 2, 3, 4])
    ax.set_yticklabels(['여유', '보통', '붐빔', '매우 붐빔'])
    ax.set_title(f'시간대별 혼잡도 (스플라인 보간 적용)')
    ax.set_xlabel('시간대')
    ax.set_ylabel('혼잡도')
    ax.grid(color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
    fig.tight_layout()

    return fig  # ★★★★★
