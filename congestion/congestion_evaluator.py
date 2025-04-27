import pandas as pd
from typing import Union, List

class CongestionEvaluator:
    def __init__(self, congestion_filepath: str):
        self.congestion = pd.read_csv(congestion_filepath)

        # '읍면동' 컬럼명을 'legaldong'으로 변경
        self.congestion.rename(columns={'읍면동': 'legaldong'}, inplace=True)

        # 필요한 컬럼만 남기기
        keep_cols = ['시도', '시군구', 'legaldong', '시간대', 'final_level']
        self.congestion = self.congestion[[col for col in keep_cols if col in self.congestion.columns]]


    def time_based_congestion_of_place(self, sido: str, sigungu: str, legaldong: str, time: Union[str, List[str]]) -> Union[str, None]:
        """
        설명 : 특정 장소에 대해 단일 시간대 또는 시간 구간에 해당하는 혼잡도 등급 반환
                단일 시간대 -> 해당 시간의 등급 반환
                시간 구간 -> 혼잡도 등급 평균 점수 계산 및 반올림하여 혼잡도 등급으로 변환 후 반환
        sido : 시도명
        sigungu : 시군구명
        legaldong : 법정동명(읍면동)
        time : 시간대(str) 또는 시간대 리스트(List[str])
        return : 혼잡도 등급 문자열 또는 None
        """
        try:
            # 해당 장소 데이터 필터링
            subset = self.congestion[(self.congestion['시도'] == sido) & (self.congestion['시군구'] == sigungu) & (self.congestion['legaldong'] == legaldong)]

            if isinstance(time, str):
                # 단일 시간대일 경우
                level = subset[subset['시간대'] == time]['final_level']
                return level.values[0] if not level.empty else None

            elif isinstance(time, list):
                # 시간 구간일 경우
                levels = subset[subset['시간대'].isin(time)]['final_level']
                if levels.empty:
                    return None
                
                # 혼잡도 등급을 숫자로 변환하여 평균 점수 계산
                numeric_scores = [self.level_to_score(lv) for lv in levels if self.level_to_score(lv) is not None]
                if not numeric_scores:
                    return None
                avg_score = round(sum(numeric_scores) / len(numeric_scores))
                return self.score_to_level(avg_score)
            
            else:
                return None
            
        except Exception:
            return None

    def recommended_place_in_certain_time(self, df_places: pd.DataFrame, time: Union[str, List[str]]) -> pd.DataFrame:
        """
        설명 : 특정 시간대 또는 시간 구간에 대해 '여유' 또는 '보통' 등급인 장소 추천 
        df_places: 장소 목록이 담긴 DataFrame (시도, 시군구, legaldong 컬럼 포함)
        time: 시간대(str) 또는 시간대 리스트(List[str])
        return: 추천된 장소 DataFrame (혼잡도 등급 포함)
        """
        results = []

        for _, row in df_places.iterrows():
            # 각 장소별로 시간대 기준 혼잡도 등급 계산
            level = self.time_based_congestion_of_place(row['시도'], row['시군구'], row['legaldong'], time)
            results.append(level)

        df_places = df_places.copy()
        df_places['혼잡도 등급'] = results

        # '여유' 또는 '보통' 등급인 장소만 필터링하여 반환
        return df_places[df_places['혼잡도 등급'].isin(['여유', '보통'])]

    def get_all_time_congestion_of_place(self, sido: str, sigungu: str, legaldong: str) -> pd.DataFrame:
        """
        설명 : 특정 장소의 모든 시간대별 혼잡도 정보 리턴
        sido: 시도명
        sigungu: 시군구명
        legaldong: 법정동명
        return: 해당 장소의 전체 시간대 혼잡도 정보 DataFrame
        """
        return self.congestion[(self.congestion['시도'] == sido) & (self.congestion['시군구'] == sigungu) & (self.congestion['legaldong'] == legaldong)].copy()

    def get_all_places_congestion_at_time(self, time: str) -> pd.DataFrame:
        """
        설명 : 특정 시간대에 모든 장소의 혼잡도 정보 반환
        time: 시간대 (예: '10시')
        return: 해당 시간대의 전체 장소 혼잡도 정보 DataFrame
        """
        return self.congestion[self.congestion['시간대'] == time].copy()

    @staticmethod
    def level_to_score(level: str) -> int:
        """
        설명 : 혼잡도 등급을 숫자로 변환
                여유=1, 보통=2, 붐빔=3, 매우 붐빔=4
        level: 혼잡도 등급 (여유/보통/붐빔/매우 붐빔)
        return: 해당 등급에 해당하는 숫자
        """
        mapping = {'여유': 1, '보통': 2, '붐빔': 3, '매우 붐빔': 4}
        return mapping.get(level, None)

    @staticmethod
    def score_to_level(score: int) -> str:
        """
        설명 : 숫자를 혼잡도 등급으로 변환
                1=여유, 2=보통, 3=붐빔, 4=매우 붐빔
        score: 숫자 점수
        return: 해당 점수에 해당하는 혼잡도 등급 문자열
        """
        mapping = {1: '여유', 2: '보통', 3: '붐빔', 4: '매우 붐빔'}
        return mapping.get(score, None)
    
