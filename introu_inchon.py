import requests
import pandas as pd
import time
import math
import json
import os
from dotenv import load_dotenv

# .env 파일 불러오기
load_dotenv()

# 환경 변수 읽기
service_key = os.getenv("SERVICE_KEY")
file_path = os.getenv("File_path")
json_file = os.getenv("key_json")

# 엑셀 파일 읽기 (콘텐츠ID가 담긴 파일)
df = pd.read_excel(file_path)
content_ids = df["콘텐츠ID"].tolist()  # 콘텐츠ID 목록 추출

# Encoded 서비스 키 (이미 URL 인코딩된 상태)
base_url = "http://apis.data.go.kr/B551011/KorService1/detailIntro1"

# JSON 파일에서 컬럼 매핑 정보 불러오기
with open(json_file, "r", encoding="utf-8") as f:
    column_mapping = json.load(f)

# API 호출 횟수를 세기 위한 변수 (1000번 초과 시 중단)
request_counter = 0
max_requests = 1000
stop_flag = False

# 모든 콘텐츠ID의 데이터를 저장할 리스트
all_collected_items = []

for content_id in content_ids:
    if stop_flag:
        break

    print(f"\n콘텐츠ID {content_id} 처리 시작")
    # 콘텐츠ID별 첫 요청 전, 호출 횟수 확인
    if request_counter >= max_requests:
        stop_flag = True
        break

    # 초기 파라미터 설정
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 1000,
        "MobileApp": "AppTest",
        "MobileOS": "ETC",
        "contentId": content_id,
        "contentTypeId": 28,
        "_type": "json"
    }

    response = requests.get(base_url, params=params)
    request_counter += 1  # 첫 요청 카운트
    try:
        data = response.json()
    except Exception as e:
        print(f"콘텐츠ID {content_id}: JSON 디코딩 에러 -> {e}")
        continue

    # totalCount 확인
    try:
        total_count = int(data["response"]["body"]["totalCount"])
    except (KeyError, TypeError, ValueError) as e:
        print(f"콘텐츠ID {content_id}: totalCount를 확인할 수 없습니다. {e}")
        continue

    print(f"콘텐츠ID {content_id}: 전체 데이터 개수: {total_count}")
    total_pages = math.ceil(total_count / params["numOfRows"])
    print(f"콘텐츠ID {content_id}: 전체 페이지 수: {total_pages}")

    collected_items = []
    for page in range(1, total_pages + 1):
        if request_counter >= max_requests:
            stop_flag = True
            print("API 호출 횟수가 1000번에 도달했습니다. 더 이상 호출하지 않고 중단합니다.")
            break

        params["pageNo"] = page
        response = requests.get(base_url, params=params)
        request_counter += 1
        if response.status_code != 200:
            print(f"콘텐츠ID {content_id} 페이지 {page} 요청 실패: 상태 코드 {response.status_code}")
            break

        try:
            data = response.json()
        except Exception as e:
            print(f"콘텐츠ID {content_id} 페이지 {page} JSON 디코딩 실패: {e}")
            continue

        try:
            items = data["response"]["body"]["items"]["item"]
        except (KeyError, TypeError) as e:
            print(f"콘텐츠ID {content_id} 페이지 {page}에 데이터가 없거나 구조가 다릅니다. 오류: {e}")
            continue

        # 단일 항목이면 리스트로 변환
        if isinstance(items, dict):
            items = [items]

        collected_items.extend(items)
        print(f"콘텐츠ID {content_id} 페이지 {page} 완료, {len(items)}개 항목 수집됨.")
        time.sleep(1)  # 요청 간 간격

    print(f"콘텐츠ID {content_id}: 총 {len(collected_items)}개 항목 수집됨.")
    # 각 콘텐츠ID에서 수집한 데이터 누적
    all_collected_items.extend(collected_items)

    # 1000번 호출 도달 시 전체 중단
    if stop_flag:
        break

# 모든 콘텐츠ID의 데이터를 하나의 엑셀 파일로 저장 (호출 제한으로 중단된 경우에도 지금까지 수집한 데이터 저장)
if all_collected_items:
    df_all = pd.DataFrame(all_collected_items)
    # 불러온 컬럼 매핑 정보를 사용하여 DataFrame 컬럼명 변경
    df_all.rename(columns=column_mapping, inplace=True)
    
    excel_filename = "소개_경기_레포츠_전체데이터.xlsx"
    df_all.to_excel(excel_filename, index=False)
    print(f"\n전체 데이터가 '{excel_filename}' 파일로 저장되었습니다.")
    print(f"총 API 호출 횟수: {request_counter}")
else:
    print("수집된 데이터가 없습니다.")
