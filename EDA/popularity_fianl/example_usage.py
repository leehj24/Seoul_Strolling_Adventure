from popularity.popularityScorers_final import PopularityScorer
import pandas as pd

# 1. 데이터 불러오기
reviews = pd.read_csv("./data/zb_review_data_final.csv", encoding="utf-8-sig")

# 2. 클래스 인스턴스화
scorer = PopularityScorer(reviews)

# 3. 파이프라인 실행
dong_cate_stats = scorer.run()

# 4. 결과 확인
print(dong_cate_stats.head(10))

# 5. 결과 저장
dong_cate_stats.to_csv("./data/popularity_final.csv", index=False, encoding="utf-8-sig")