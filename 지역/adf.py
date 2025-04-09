import pandas as pd

# 엑셀 파일 읽기
file_path = r'E:\machin-prj\지역\tourism_data_쇼핑_korean.xlsx'  # 엑셀 파일 경로
df = pd.read_excel(file_path)

# 특정 단어 삭제
target_word = "시장"  # 삭제하려는 단어
df_filtered = df[~df.apply(lambda row: row.astype(str).str.contains(target_word).any(), axis=1)]  # 단어가 포함된 행을 제외
# 수정된 데이터 저장
df_filtered.to_excel(file_path, index=False)  # 수정된 파일 저장
