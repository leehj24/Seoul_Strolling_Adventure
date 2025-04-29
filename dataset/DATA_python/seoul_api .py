import requests
import pandas as pd
import time
import math
import json
import os
from dotenv import load_dotenv

# .env 파일 불러오기
load_dotenv()

# 환경 변수 (서비스 키 등) 읽기
service_key = os.getenv("SERVICE_KEY")
base_url = "http://apis.data.go.kr/B551011/KorService1/categoryCode1"

file_path = "카테고리.xlsx"  # cat1, cat2가 저장된 엑셀 파일 경로
df_cat12 = pd.read_excel(file_path)

# cat3 결과를 모을 리스트
all_cat3_items = []

# 각 행마다 (대분류, 중분류) 정보를 이용하여 소분류(cat3) 호출
for idx, row in df_cat12.iterrows():
    cat1 = str(row["cat1"]).strip()   # 예: "A01"
    cat2 = str(row["cat2"]).strip()   # 예: "A0101", "A0102", "A0201", 등

    # cat2의 첫 3글자가 cat1과 동일한 경우에만 처리
    if not cat2.startswith(cat1):
        print(f"[건너뜀] 대분류(cat1)={cat1}와 중분류(cat2)={cat2}의 3글자가 일치하지 않음.")
        continue

    print(f"\n[조회] 대분류(cat1)={cat1}, 중분류(cat2)={cat2}")

    # API 요청 파라미터 설정 (소분류 조회)
    params = {
        "serviceKey": service_key,
        "cat1": cat1,           # 대분류 코드
        "cat2": cat2,           # 중분류 코드 (이 값은 첫 3글자가 cat1과 동일해야 함)
        "MobileApp": "AppTest",
        "MobileOS": "ETC",
        "pageNo": 1,
        "numOfRows": 9999,      # 충분히 큰 값(소분류 항목 수가 많지 않으므로)
        "_type": "json"
    }

    # API 호출
    response = requests.get(base_url, params=params)
    try:
        data = response.json()
    except Exception as e:
        print(f"[오류] cat1={cat1}, cat2={cat2} JSON 파싱 실패: {e}")
        continue

    # 응답 구조에서 소분류(항목) 데이터 확인
    try:
        items_field = data["response"]["body"]["items"]
        if not isinstance(items_field, dict) or "item" not in items_field:
            print(f"[주의] cat1={cat1}, cat2={cat2}에 대한 소분류 데이터가 없습니다. (items_field 타입: {type(items_field)})")
            continue
        items = items_field["item"]
    except Exception as e:
        print(f"[주의] cat1={cat1}, cat2={cat2} 데이터 처리 오류: {e}")
        continue

    # 단일 항목이면 리스트로 변환
    if isinstance(items, dict):
        items = [items]

    # 수집된 소분류 데이터 누적
    for item in items:
        code3 = item.get("code")    # 소분류 코드
        name3 = item.get("name")    # 소분류 이름
        all_cat3_items.append({
            "cat1": cat1,
            "cat2": cat2,
            "cat3": code3,
            "cat3_name": name3
        })

    print(f"[완료] cat1={cat1}, cat2={cat2}: {len(items)}개 항목 수집됨.")
    time.sleep(1)  # API 과부하 방지를 위한 딜레이

# 모든 소분류 데이터를 엑셀로 저장
if all_cat3_items:
    df_cat3 = pd.DataFrame(all_cat3_items)
    # 원하는 순서의 컬럼 정렬
    df_cat3 = df_cat3[["cat1", "cat2", "cat3", "cat3_name"]]
    
    # (옵션) 컬럼 매핑 정보 적용
    # df_cat3.rename(columns=column_mapping, inplace=True)

    output_file = "대분류중분류_소분류결과.xlsx"
    df_cat3.to_excel(output_file, index=False)
    print(f"\n소분류 정보가 '{output_file}' 파일로 저장되었습니다.")
else:
    print("수집된 소분류(cat3) 데이터가 없습니다.")