import requests
import pandas as pd

# API 호출 URL
url = "http://apis.data.go.kr/B551011/KorService1/areaBasedList1"
key_path ='P371OlfKqVBK3Xyh5toIl5QaAaXjNqtaL/M3MMWToiDIQ2KleaUsjemd62AZag6iBQ3UuK8gmV8i7JLT/wV/tA=='

# API 요청 파라미터 설정
params = {
    "serviceKey": key_path,
    "MobileApp": "AppTest",
    "MobileOS": "ETC",
    "pageNo": 1,
    "numOfRows": 999999,      # 충분히 큰 값(소분류 항목 수가 많지 않으므로)
    "_type": "json"
}


# API 호출
response = requests.get(url, params=params)

# 응답 결과 확인 및 데이터 처리
if response.status_code == 200:
    # JSON 형식 응답 파싱
    data = response.json()
    
    # 응답 JSON의 구조에 따라 관광정보 목록 추출
    # 일반적으로 response -> body -> items -> item 형태로 구성됨
    items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    
    # 만약 단일 항목일 경우 리스트로 변환
    if isinstance(items, dict):
        items = [items]
    
    # 추출된 데이터를 Pandas DataFrame으로 변환
    df = pd.DataFrame(items)
    
    # DataFrame 내용을 엑셀 파일로 저장 (인덱스 없이 저장)
    excel_filename = "tour_info.xlsx"
    df.to_excel(excel_filename, index=False)
    
    print(f"API 호출 성공: 응답 데이터를 '{excel_filename}' 파일로 저장하였습니다.")
else:
    print(f"API 호출 실패 (상태 코드: {response.status_code})")
