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

contentTypeId = 39
# 엑셀 파일 읽기
df = pd.read_excel(file_path)

content_ids = df["콘텐츠ID"].tolist()  # 콘텐츠ID 목록 추출

all_details = []
error_count = 0  # 에러 누적 카운터
for idx, contentId in enumerate(content_ids, start=1):
    url = (
        f"http://apis.data.go.kr/B551011/KorService1/detailCommon1"
        f"?serviceKey={service_key}&MobileOS=ETC&MobileApp=AppTest&_type=json"
        f"&contentId={contentId}&contentTypeId={contentTypeId}"
        f"&defaultYN=Y&overviewYN=Y&addrinfoYN=Y&firstImageYN=Y&areacodeYN=Y&catcodeYN=Y&mapinfoYN=Y"
    )
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f":x: 요청 실패 (contentId={contentId}) - status code:", response.status_code)
            error_count += 1
            if error_count >= 30:
                print(":경광등: 에러 30건 이상 → 수집 중단 및 저장 진행")
                break
            continue
        data = response.json()
        item = data['response']['body']['items']['item']
        # 리스트 혹은 단일 dict 대응
        if isinstance(item, list):
            all_details.extend(item)
        else:
            all_details.append(item)
        print(f":흰색_확인_표시: {idx}/{len(content_ids)} - contentId {contentId} 수집 완료")
        error_count = 0  # 성공 시 초기화
        time.sleep(0.2)
    except Exception as e:
        print(f":경고: 파싱 오류 (contentId={contentId}):", e)
        print("응답 내용:", response.text[:300])
        error_count += 1
        if error_count >= 30:
            print(":경광등: 에러 30건 이상 → 수집 중단 및 저장 진행")
            break
        continue
# DataFrame 변환 및 중복 제거
seoul_detail1 = pd.DataFrame(all_details)
seoul_detail1 = seoul_detail1.drop_duplicates()

# 저장
seoul_detail1.to_csv("ZB)ZB)TourAPI_gyeonggi_음식점_detail.csv", index=False, encoding="utf-8-sig")
print(":흰색_확인_표시: 저장 완료! 총 행 수:", len(seoul_detail1))