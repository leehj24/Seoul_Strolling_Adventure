
import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
from IPython.display import display



# .env 파일 불러오기
load_dotenv()

# 환경 변수 읽기
service_key = os.getenv("SERVICE_KEY")
file_path = os.getenv("File_path")


place_df = pd.read_csv(file_path)
display(place_df.head())
display(place_df.info())
print(place_df.info())

options = webdriver.ChromeOptions()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(service=Service(), options=options)

wait = WebDriverWait(driver, 10)
combined_data = []

def search_place_and_scrape(query):
    try:
        driver.get("https://map.kakao.com/")
        time.sleep(2)
        search_box = driver.find_element(By.ID, "search.keyword.query")
        search_box.clear()
        search_box.send_keys(query)
        search_box.send_keys(Keys.RETURN)
        time.sleep(3)

        # 인기도순 버튼 클릭
        try:
            sort_btn = driver.find_element(By.CSS_SELECTOR, "#info\.search\.place\.sort > li:nth-child(2) > a")
            sort_btn.click()
            time.sleep(2)
        except:
            pass

        # 첫 번째 결과
        first_item = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#info\\.search\\.place\\.list > li:nth-child(1)")))

        try:
            name_tag = first_item.find_element(By.CSS_SELECTOR, "a[data-id='name']")
            name = name_tag.get_attribute("title")
        except:
            name = None
        try:
            score_tag = first_item.find_element(By.CSS_SELECTOR, "em[data-id='scoreNum']")
            score = score_tag.get_attribute("title")
        except:
            score = None
        try:
            addr_tag = first_item.find_element(By.CSS_SELECTOR, "p[data-id='address']")
            addr = addr_tag.get_attribute("title")
        except:
            addr = None

        print(f"[장소 수집] 이름: {name}, 평점: {score}, 주소: {addr}")

        # 상세페이지
        detail_btn = first_item.find_element(By.CSS_SELECTOR, "a.moreview")
        driver.execute_script("arguments[0].click();", detail_btn)
        time.sleep(2)
        driver.switch_to.window(driver.window_handles[-1])

        # 후기 탭
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='#comment']")))
            driver.find_element(By.CSS_SELECTOR, "a[href='#comment']").click()
            time.sleep(2)
        except:
            pass

        # 리뷰 더보기
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            try:
                more_btn = driver.find_element(By.CSS_SELECTOR, "a.btn_more")
                if more_btn.is_displayed():
                    driver.execute_script("arguments[0].click();", more_btn)
                    time.sleep(2)
                else:
                    break
            except:
                break

        # 리뷰
        reviews = driver.find_elements(By.CSS_SELECTOR, "ul.list_review > li")
        if reviews:
            print(f"[리뷰 수집] 총 {len(reviews)}개의 리뷰를 찾음.")
            for idx, r in enumerate(reviews, start=1):
                try:
                    btn_more = r.find_elements(By.CSS_SELECTOR, "span.btn_more")
                    if btn_more:
                        driver.execute_script("arguments[0].click();", btn_more[0])
                        time.sleep(1)
                except:
                    pass
                
                try:
                    stars = r.find_elements(By.CSS_SELECTOR, "span.wrap_grade > span.figure_star.on")
                    rating = len(stars)
                except:
                    rating = None
                try:
                    reviewer = r.find_element(By.CSS_SELECTOR, "span.name_user").text
                except:
                    reviewer = None
                try:
                    date = r.find_element(By.CSS_SELECTOR, "span.txt_date").text
                except:
                    date = None
                try:
                    content = r.find_element(By.CSS_SELECTOR, "p.desc_review").text
                except:
                    content = None

                print(f"[{idx}] 리뷰 - 닉네임: {reviewer}, 별점: {rating}, 날짜: {date}, 내용: {content}")

                combined_data.append({
                    "검색어": query,
                    "장소명": name,
                    "평점": score,
                    "주소": addr,
                    "리뷰닉네임": reviewer,
                    "별점": rating,
                    "날짜": date,
                    "리뷰내용": content
                })
        else:
            print("[리뷰 없음] 리뷰가 없으므로 장소 정보만 저장.")
            combined_data.append({
                "검색어": query,
                "장소명": name,
                "평점": score,
                "주소": addr,
                "리뷰닉네임": None,
                "별점": None,
                "날짜": None,
                "리뷰내용": None
            })

        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        return True

    except Exception as e:
        print(f"[오류 발생] 검색어 '{query}' 로 검색 실패: {e}")
        return False

# 전체 반복 실행
# 전체 반복 실행 (상위 502행까지만 반복)
for idx, row in place_df.iloc[:502].iterrows():
    keyword = str(row.get("title", "")).strip()
    alt_keyword = str(row.get("addr1", "")).strip()
    
    success = search_place_and_scrape(keyword)
    if not success and alt_keyword:
        print(f"주소로 재검색: {alt_keyword}")
        search_place_and_scrape(alt_keyword)

driver.quit()
result_df = pd.DataFrame(combined_data)

# (수정부분) excel 파일 말고 csv 파일로 저장!! -> 에러나면 이 부분만 다시 실행
result_df.to_csv("./data/ZB_TourAPI_area_based_seoul_4_reviewCrawling.csv", index=False, encoding='utf-8-sig')
print("장소+리뷰 데이터 저장 완료: ZB_TourAPI_area_based_seoul_4_reviewCrawling.csv")
