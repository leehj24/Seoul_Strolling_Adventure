import requests
from config import KAKAO_API_KEY
from typing import Optional, Tuple

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

def print_region(region: str) -> None:
    """
    콘솔에 region 입력 로그와 좌표를 출력.
    """
    print(f"선택한 지역: {region}")
    coords = geocode_region_kakao(region)
    lat_lon = []
    if coords:
        lat_lon.append(coords[0])
        lat_lon.append(coords[1])
    
        print(f" → 위도: {coords[0]:.6f}, 경도: {coords[1]:.6f}")
    else:
        print(" → 위·경도 조회에 실패했습니다.")
    print()
    lat = lat_lon[0]
    lon = lat_lon[1]

    return lat, lon

def compute_scores(selection):      ## 지수선택
    """
    선택 리스트 순서대로 3,2,1점… 할당하여 리스트로 반환.
    """
    # [max(0, 3 - i) for i in range(len(selection))]
    scores = []
    for idx, item in enumerate(selection):
        scores.append(max(0, 3 - idx))
    return scores


def print_scores(selection, label="항목"):  ### 테마선택
    """
    compute_scores 결과를 보기 좋게 콘솔에 출력.
    """
    scores = compute_scores(selection)
    print(f"{label} 점수 매핑:")
    for item, score in scores.items():
        print(f"  {item}: {score}")
    print()
