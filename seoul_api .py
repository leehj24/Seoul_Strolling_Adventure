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
base_url = "http://apis.data.go.kr/B551011/KorService1/searchKeyword1"

# 초기 파라미터 설정
params = {
    "serviceKey": service_key,
    "pageNo": 1,            # 시작 페이지 번호 (반복문 내에서 업데이트)
    "numOfRows": 1000,        # 한 페이지당 항목 수 (필요에 따라 조정)
    "MobileApp": "AppTest",
    "MobileOS": "ETC",
    "arrange": "A",
    # "contentTypeId": 12,
    "areaCode":31,          # areaCode 1 (모든 데이터)
    "_type": "json",         # JSON 응답 요청
    "keyword" : "박물관"
}


response = requests.get(base_url, params=params)
data = response.json()
try:
    total_count = int(data["response"]["body"]["totalCount"])
except (KeyError, TypeError, ValueError) as e:
    print("totalCount를 확인할 수 없습니다.", e)
    total_count = None

if total_count is not None:
    print(f"전체 데이터 개수: {total_count}")
    total_pages = math.ceil(total_count / params["numOfRows"])
    print(f"전체 페이지 수: {total_pages}")

    all_items = []
    for page in range(1, total_pages + 1):
        params["pageNo"] = page
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            print(f"페이지 {page} 요청 실패: 상태 코드 {response.status_code}")
            break

        data = response.json()
        try:
            items = data["response"]["body"]["items"]["item"]
        except (KeyError, TypeError) as e:
            print(f"페이지 {page}에 데이터가 없거나 구조가 다릅니다. 오류: {e}")
            continue

        # 단일 항목이 dict 형태로 전달될 경우 리스트로 변환
        if isinstance(items, dict):
            items = [items]

        all_items.extend(items)
        print(f"페이지 {page} 완료, {len(items)}개 항목 수집됨.")
        time.sleep(1)  # 요청 간 간격

    print(f"\n총 {len(all_items)}개의 항목을 수집하였습니다.")

    if all_items:
        df = pd.DataFrame(all_items)
        # 영어 컬럼명을 한글로 매핑
        column_mapping = {
            "addr1"	        :    "주소",
            "addr2"	        :   "상세주소",
            "areacode"	    :   "지역코드",
            "booktour"	    :   "교과서속여행지여부",
            "cat1"	        :   "대분류",
            "cat2"	        :   "중분류",
            "cat3"	        :   "소분류",
            "contentid"	    :   "콘텐츠ID",
            "contenttypeid"	:   "콘텐츠타입ID",
            "createdtime"	:   "등록일",
            "firstimage"	:   "대표이미지(원본)",
            "firstimage2"	:   "대표이미지(썸네일)",
            "cpyrhtDivCd"	:   "저작권 유형",
            "mapx"	        :   "GPS X좌표",
            "mapy"	        :   "GPS Y좌표",
            "mlevel"	    :   "Map Level",
            "modifiedtime"	:   "수정일",
            "sigungucode"   :   "시군구코드",
            "tel"           :   "전화번호",
            "title"         :   "제목",
            "zipcode"       :   "우편번호"

        }
        df.rename(columns=column_mapping, inplace=True)
        excel_filename = "keyword_박물관_경기_korean.xlsx"
        df.to_excel(excel_filename, index=False)
        print(f"데이터가 '{excel_filename}' 파일로 저장되었습니다.")
else:
    print("전체 데이터 개수를 확인할 수 없습니다.")