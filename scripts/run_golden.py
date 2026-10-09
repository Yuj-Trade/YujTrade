import sys
sys.path.insert(0, "C:/ME/YujTrade")

# Use real pandas_ta (already installed)
print("Using real pandas_ta")

# Now test imports
import features.indicators.custom
import features.indicators.all_indicators
import features.feature_engineering
print("All imports successful")

# Now run the golden recording script logic
from strategy.signal_generator import SignalGenerator
from config.settings import ConfigManager
from common.core import TradingSignal
from data.data_validator import DataQualityChecker

# Monkey-patch the freshness check to always pass for golden tests
original_check_freshness = DataQualityChecker._check_data_freshness
def always_fresh(self, data, timeframe):
    return True
DataQualityChecker._check_data_freshness = always_fresh

class FakeProvider:
    def __init__(self, fixture_1h, fixture_1d):
        self.fixture_1h = fixture_1h
        self.fixture_1d = fixture_1d
    
    async def fetch_ohlcv_data(self, symbol, timeframe, limit=1000, bypass_cache=False):
        if timeframe == "1h":
            df = self.fixture_1h.copy()
        elif timeframe == "1d":
            df = self.fixture_1d.copy()
        else:
            return pd.DataFrame()
        return df.iloc[-limit:] if len(df) > limit else df

class FakeModelManager:
    async def predict_with_confidence(self, model_type, symbol, timeframe):
        return None
    
    async def record_signal_performance(self, model_type, symbol, timeframe, confidence, success):
        pass

import pandas as pd
import asyncio
import json
from pathlib import Path

async def record_signals_baseline():
    fixture_1h = pd.read_csv("tests/fixtures/ohlcv_1h.csv", index_col=0, parse_dates=True)
    fixture_1d = pd.read_csv("tests/fixtures/ohlcv_1d.csv", index_col=0, parse_dates=True)
    
    print(f"Loaded 1h fixture: {len(fixture_1h)} rows")
    print(f"Loaded 1d fixture: {len(fixture_1d)} rows")
    
    config = ConfigManager()
    fake_provider = FakeProvider(fixture_1h, fixture_1d)
    fake_model = FakeModelManager()
    
    signal_gen = SignalGenerator(
        data_provider=fake_provider,
        model_manager=fake_model,
        config_manager=config
    )
    
    all_signals = []
    
    for timeframe, fixture in [("1h", fixture_1h), ("1d", fixture_1d)]:
        print(f"Processing {timeframe}...")
        start_idx = 600 if timeframe == "1h" else 300
        for i in range(start_idx, len(fixture)):
            data_slice = fixture.iloc[:i+1]
            
            try:
                signal = await signal_gen.generate_signal(
                    symbol="BTC/USDT",
                    timeframe=timeframe,
                    data=data_slice,
                    include_external=False,
                    include_ml=False
                )
                
                if signal:
                    signal_dict = {
                        "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
                        "signal_type": signal.signal_type.value,
                        "entry": signal.entry_price,
                        "stop": signal.stop_loss,
                        "target": signal.exit_price,
                        "risk_reward_ratio": signal.risk_reward_ratio,
                        "confidence_score": signal.confidence_score,
                        "threshold_used": signal.threshold_used,
                    }
                    all_signals.append(signal_dict)
                    
            except Exception as e:
                print(f"  Error at index {i}: {e}")
    
    output_path = Path("tests/golden/signals_baseline.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(all_signals, f, indent=2)
    
    print(f"Recorded {len(all_signals)} signals to {output_path}")
    return all_signals

asyncio.run(record_signals_baseline())
