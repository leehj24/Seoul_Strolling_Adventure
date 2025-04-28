# main.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from busy_recommend import busy  # <- plot_module.py 에서 busy 함수 가져오기

# busy 함수 실행 → fig 객체 반환
fig = busy('강남역')

plt.show()
