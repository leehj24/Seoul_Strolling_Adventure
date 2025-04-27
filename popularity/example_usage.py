from popularity_scorer import PopularityScorer

# 리뷰데이터 파일 경로
input_path = r"C:\Users\hyunj\Seoul_Strolling_Adventure\popularity\zb_review_data_final.csv"  # 입력 데이터
output_path = r"C:\Users\hyunj\Seoul_Strolling_Adventure\popularity\popularity_result.csv"    # 결과(출력) 데이터

# 인기도지수 계산 실행
scorer = PopularityScorer(input_path)
popularity_df, weights = scorer.run_all()

# 인기지수 도출 결과
print("인기도 = ", weights["보정평점"], "x 평균평점 + ", weights["보정긍정점수"], "x 평균긍정점수 + ", weights["로그리뷰수"], "x 로그리뷰수")

# 결과 저장
popularity_df.to_csv(output_path, index=False, encoding="utf-8-sig")
print("인기도지수 계산 완료. 결과 저장:", output_path)
