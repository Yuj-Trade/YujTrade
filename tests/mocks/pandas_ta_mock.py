"""
Mock for pandas_ta module to allow tests to run without the actual dependency.
"""
import sys
from types import ModuleType

# Create mock module
mock_pandas_ta = ModuleType('pandas_ta')
mock_momentum = ModuleType('pandas_ta.momentum')
mock_overlap = ModuleType('pandas_ta.overlap')
mock_volatility = ModuleType('pandas_ta.volatility')
mock_trend = ModuleType('pandas_ta.trend')
mock_volume = ModuleType('pandas_ta.volume')

# Add functions that are imported
for name in ['stoch', 'roc', 'stochrsi', 'trix', 'uo', 'squeeze', 'cmo']:
    setattr(mock_momentum, name, lambda *args, **kwargs: None)

for name in ['ichimoku', 'supertrend', 'kama']:
    setattr(mock_overlap, name, lambda *args, **kwargs: None)

for name in ['bbands', 'atr', 'kc', 'massi', 'donchian']:
    setattr(mock_volatility, name, lambda *args, **kwargs: None)

for name in ['adx', 'aroon', 'psar', 'dpo']:
    setattr(mock_trend, name, lambda *args, **kwargs: None)

for name in ['cmf', 'obv', 'ad', 'eom', 'efi', 'pvt', 'kvo', 'pvo', 'nvi', 'pvi']:
    setattr(mock_volume, name, lambda *args, **kwargs: None)

mock_pandas_ta.momentum = mock_momentum
mock_pandas_ta.overlap = mock_overlap
mock_pandas_ta.volatility = mock_volatility
mock_pandas_ta.trend = mock_trend
mock_pandas_ta.volume = mock_volume

# Add to sys.modules
sys.modules['pandas_ta'] = mock_pandas_ta
sys.modules['pandas_ta.momentum'] = mock_momentum
sys.modules['pandas_ta.overlap'] = mock_overlap
sys.modules['pandas_ta.volatility'] = mock_volatility
sys.modules['pandas_ta.trend'] = mock_trend
sys.modules['pandas_ta.volume'] = mock_volume

print("pandas_ta mock installed")
