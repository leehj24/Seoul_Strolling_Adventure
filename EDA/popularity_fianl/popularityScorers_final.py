import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler

class PopularityScorer:
    def __init__(self, review_data):
        """리뷰 데이터 로딩"""
        self.review_data = review_data.copy()
        self.dong_cate_stats = None
        self.scaled_df = None
        self.weights = None

    def calculate_positive_probability(self, row):
        """감정레이블에 따라 긍정확률 계산"""
        if row["감정레이블"] == 2:
            return row["감정확률"]
        elif row["감정레이블"] == 0:
            return 1 - row["감정확률"]
        else:
            return 0.5

    def aggregate_features(self):
        """리뷰수, 평균별점, 평균긍정비율 집계 및 로그리뷰수 추가"""
        self.review_data["긍정확률"] = self.review_data.apply(self.calculate_positive_probability, axis=1)

        stats = self.review_data.groupby(["행정구", "행정동", "카테고리"]).agg(
            리뷰수=("별점", "count"),
            평균별점=("별점", "mean"),
            평균긍정비율=("긍정확률", "mean")
        ).reset_index()

        stats["로그리뷰수"] = np.log1p(stats["리뷰수"])
        self.dong_cate_stats = stats

    def bayesian_adjust(self, value, count, global_mean, m):
        """베이지안 보정"""
        return (count * value + m * global_mean) / (count + m)

    def apply_bayesian_correction(self):
        """평균별점과 평균긍정비율 베이지안 보정"""
        global_avg_rating = self.dong_cate_stats["평균별점"].mean()
        global_avg_posrate = self.dong_cate_stats["평균긍정비율"].mean()
        m_rating = self.dong_cate_stats["리뷰수"].median()
        m_posrate = self.dong_cate_stats["리뷰수"].median()

        self.dong_cate_stats["보정평균별점"] = self.dong_cate_stats.apply(
            lambda row: self.bayesian_adjust(row["평균별점"], row["리뷰수"], global_avg_rating, m_rating), axis=1
        )
        self.dong_cate_stats["보정평균긍정비율"] = self.dong_cate_stats.apply(
            lambda row: self.bayesian_adjust(row["평균긍정비율"], row["리뷰수"], global_avg_posrate, m_posrate), axis=1
        )

    def scale_features(self):
        """MinMaxScaler로 표준화"""
        features = ["로그리뷰수", "보정평균별점", "보정평균긍정비율"]
        scaler = MinMaxScaler()
        self.scaled_df = pd.DataFrame(
            scaler.fit_transform(self.dong_cate_stats[features]),
            columns=features
        )

    def assign_equal_weights(self):
        """단순평균 가중치 부여 (각 1/3)"""
        n_features = self.scaled_df.shape[1]
        self.weights = {col: 1/n_features for col in self.scaled_df.columns}

    def calculate_popularity_score(self):
        """최종 인기도지수 계산"""
        score = sum(
            self.weights[col] * self.scaled_df[col]
            for col in self.scaled_df.columns
        )
        self.dong_cate_stats["인기도지수"] = score

    def run(self):
        """전체 프로세스 실행"""
        self.aggregate_features()
        self.apply_bayesian_correction()
        self.scale_features()
        self.assign_equal_weights()
        self.calculate_popularity_score()
        return self.dong_cate_stats.sort_values(by="인기도지수", ascending=False).reset_index(drop=True)