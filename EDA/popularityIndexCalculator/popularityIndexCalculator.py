import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler

class PopularityIndexCalculator:
    def __init__(self, filepath, encoding='utf-8-sig'):
        """초기화 함수: 데이터 파일 경로와 인코딩 방식 설정"""
        self.filepath = filepath
        self.encoding = encoding
        self.review_df = None
        self.filtered_grouped = None

    def load_and_filter_data(self):
        """데이터를 불러오고, 지정된 5개 카테고리로 필터링"""
        reviews = pd.read_csv(self.filepath, encoding=self.encoding)
        categories = ["힐링", "액티비티", "문화", "음식", "쇼핑"]
        self.review_df = reviews[reviews["카테고리"].isin(categories)].copy()

    def compute_features(self):
        """행정동-카테고리별 평균 별점, 리뷰 수, 긍정 비율 계산"""
        def feature_function(group):
            avg_rating = group['별점'].mean()
            review_count = len(group)
            positive_reviews = group[group['감정레이블'] == 2]
            positive_ratio = len(positive_reviews) / review_count if review_count > 0 else 0
            return pd.Series({
                'avg_rating': avg_rating,
                'review_count': review_count,
                'positive_ratio': positive_ratio
            })

        grouped = self.review_df.groupby(['행정구', '행정동', '카테고리']).apply(feature_function).reset_index()
        return grouped

    def filter_by_review_count(self, grouped_df, min_reviews=5):
        """리뷰 수가 일정 기준 이상인 데이터만 필터링"""
        filtered = grouped_df[grouped_df['review_count'] >= min_reviews].reset_index(drop=True)
        self.filtered_grouped = filtered

    def calculate_popularity_index(self, w_review=0.5, w_positive=0.3, w_rating=0.2):
        """가중합 방식으로 인기도지수 계산"""
        if self.filtered_grouped is None:
            raise ValueError("필터링된 데이터가 없습니다. 먼저 filter_by_review_count를 호출하세요.")

        self.filtered_grouped['log_review_count'] = np.log1p(self.filtered_grouped['review_count'])

        scaler = MinMaxScaler()
        self.filtered_grouped[['review_scaled', 'positive_scaled', 'rating_scaled']] = scaler.fit_transform(
            self.filtered_grouped[['log_review_count', 'positive_ratio', 'avg_rating']]
        )

        self.filtered_grouped['popularity_index'] = (
            w_review * self.filtered_grouped['review_scaled'] +
            w_positive * self.filtered_grouped['positive_scaled'] +
            w_rating * self.filtered_grouped['rating_scaled']
        )

    def get_result(self):
        """최종 결과 DataFrame 반환"""
        if self.filtered_grouped is None:
            raise ValueError("계산된 결과가 없습니다. 먼저 calculate_popularity_index를 호출하세요.")
        return self.filtered_grouped.copy()

    def get_sorted_result(self):
        """인기도지수 기준으로 내림차순 정렬된 결과 반환"""
        if self.filtered_grouped is None:
            raise ValueError("계산된 결과가 없습니다. 먼저 calculate_popularity_index를 호출하세요.")
        return self.filtered_grouped.sort_values(by='popularity_index', ascending=False).reset_index(drop=True)

    def save_result(self, filepath):
        """최종 결과를 CSV 파일로 저장"""
        if self.filtered_grouped is None:
            raise ValueError("저장할 데이터가 없습니다. 먼저 calculate_popularity_index를 호출하세요.")
        self.filtered_grouped.to_csv(filepath, index=False, encoding='utf-8-sig')

    def run_full_process(self, min_reviews=5, w_review=0.5, w_positive=0.3, w_rating=0.2):
        """전체 프로세스를 실행하여 인기도지수를 계산하고 내림차순 정렬된 결과 반환"""
        self.load_and_filter_data()
        grouped = self.compute_features()
        self.filter_by_review_count(grouped, min_reviews=min_reviews)
        self.calculate_popularity_index(w_review=w_review, w_positive=w_positive, w_rating=w_rating)
        return self.get_sorted_result()
