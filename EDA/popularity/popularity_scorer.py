import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler

class PopularityScorer:
    def __init__(self, filepath):
        # 리뷰 데이터 불러오기
        self.reviews = pd.read_csv(filepath, encoding="utf-8-sig")
        self.stats = None
        self.weights = None

    def aggregate_basic_stats(self):
        # 행정동/카테고리별 리뷰 수, 평균 평점, 평균 긍정점수 집계
        self.stats = self.reviews.groupby(["행정구", "행정동", "카테고리"]).agg(
            리뷰수=("날짜", "size"),
            평균평점=("별점", "mean"),
            평균긍정점수=("긍정점수", "mean")
        ).reset_index()

    def transform_review_count(self):
        # 리뷰 수를 로그 변환하여 스케일 차이 보정
        self.stats["로그리뷰수"] = np.log1p(self.stats["리뷰수"])

    def apply_bayesian_adjustment(self):
        # 베이지안 방식으로 평점 및 긍정점수 보정
        def bayesian_adjust(value, count, global_mean, m):
            return (count * value + m * global_mean) / (count + m)

        m = self.stats["리뷰수"].median()
        global_rating_mean = self.stats["평균평점"].mean()
        global_pos_mean = self.stats["평균긍정점수"].mean()

        self.stats["보정평점"] = self.stats.apply(
            lambda row: bayesian_adjust(row["평균평점"], row["리뷰수"], global_rating_mean, m),
            axis=1
        )
        self.stats["보정긍정점수"] = self.stats.apply(
            lambda row: bayesian_adjust(row["평균긍정점수"], row["리뷰수"], global_pos_mean, m),
            axis=1
        )

    def calculate_entropy_weights(self, log_weight_max=0.5):
        # 엔트로피 기반 가중치 계산 후 로그리뷰수 상한 설정
        features = ["보정평점", "보정긍정점수", "로그리뷰수"]
        scaled = StandardScaler().fit_transform(self.stats[features])
        df_scaled = pd.DataFrame(scaled, columns=features)

        # 엔트로피 계산
        P = df_scaled / (df_scaled.sum(axis=0) + 1e-9)
        E = -np.nansum(P * np.log(P + 1e-9), axis=0) / np.log(len(df_scaled))
        d = 1 - E
        raw_weights = d / d.sum()

        # 가중치 상한 조정
        adjusted_log_weight = min(raw_weights[2], log_weight_max)
        remaining_weight = 1 - adjusted_log_weight
        total_remaining = raw_weights[0] + raw_weights[1]

        adjusted_weights = {
            "보정평점": raw_weights[0] / total_remaining * remaining_weight,
            "보정긍정점수": raw_weights[1] / total_remaining * remaining_weight,
            "로그리뷰수": adjusted_log_weight
        }

        self.weights = adjusted_weights

    def compute_popularity_index(self):
        # 인기도지수 계산
        self.stats["인기도"] = (
            self.weights["보정평점"] * self.stats["보정평점"] +
            self.weights["보정긍정점수"] * self.stats["보정긍정점수"] +
            self.weights["로그리뷰수"] * self.stats["로그리뷰수"]
        )
        self.stats = self.stats.sort_values("인기도", ascending=False).reset_index(drop=True)

    def run_all(self):
        # 전체 흐름 실행
        self.aggregate_basic_stats()
        self.transform_review_count()
        self.apply_bayesian_adjustment()
        self.calculate_entropy_weights()
        self.compute_popularity_index()
        return self.stats, self.weights
