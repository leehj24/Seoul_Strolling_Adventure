from popularityIndexCalculator import PopularityIndexCalculator

calculator = PopularityIndexCalculator("./data/zb_review_data_final.csv")
sorted_result_df = calculator.run_full_process()
print(sorted_result_df.head())
calculator.save_result("./data/popularity_index_result.csv")