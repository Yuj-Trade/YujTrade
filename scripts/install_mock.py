import sys
import pandas as pd
import numpy as np
from types import ModuleType

mock_pandas_ta = ModuleType("pandas_ta")
mock_momentum = ModuleType("pandas_ta.momentum")
mock_overlap = ModuleType("pandas_ta.overlap")
mock_volatility = ModuleType("pandas_ta.volatility")
mock_trend = ModuleType("pandas_ta.trend")
mock_volume = ModuleType("pandas_ta.volume")

def make_aroon_result(high, low, length=14, **kwargs):
    n = len(high)
    return pd.DataFrame({"AROONU_14": np.random.uniform(0, 100, n), "AROOND_14": np.random.uniform(0, 100, n), "AROONOSC_14": np.random.uniform(-100, 100, n)}, index=high.index)

print("install_mock.py created")
