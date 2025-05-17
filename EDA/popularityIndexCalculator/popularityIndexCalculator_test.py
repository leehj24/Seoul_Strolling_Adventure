from popularityIndexCalculator import PopularityIndexCalculator

file = r'E:\machin-prj\EDA\popularityIndexCalculator\zb_review_data_final.csv'
calculator = PopularityIndexCalculator(file)
sorted_result_df = calculator.run_full_process()
print(sorted_result_df.head())
calculator.save_result("./EDA/popularityIndexCalculator/popularity_index_result.csv")