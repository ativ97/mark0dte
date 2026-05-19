import unittest
import pandas as pd
import numpy as np
import sys
import os

# Ensure the backend directory is in the path so we can import main
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the brain from your main code
from main import analyze_market_regime


class TestQuantEngine(unittest.TestCase):

    def setUp(self):
        """
        Creates mock dataframes to feed into our engine before each test runs.
        """
        # Create a mock dataframe structure that pandas-ta would output
        self.columns = ['Close', 'EMA_9', 'EMA_21', 'RSI_14', 'CHOP_14_1_100', 'ER_10']

        # 1. Mock Data for a PERFECT TREND (State A)
        # EMAs wide apart, RSI healthy, CHOP low, ER high
        self.mock_trend_data = pd.DataFrame([[7400, 7350, 7300, 65.0, 30.0, 0.80]], columns=self.columns)

        # 2. Mock Data for EXTREME CHOP (State C)
        # EMAs touching, RSI in dead zone (50), CHOP high, ER low
        self.mock_chop_data = pd.DataFrame([[7400, 7400.5, 7400.1, 50.0, 65.0, 0.10]], columns=self.columns)

    def test_trend_detection(self):
        """Tests if the engine correctly identifies a perfect trend (Score 0)"""
        result = analyze_market_regime(self.mock_trend_data)

        # We EXPECT the score to be 0. If it's not, the test FAILS.
        self.assertEqual(result['regime_score'], 0, "Engine failed to identify a clean trend.")
        self.assertEqual(result['regime_state'], "STATE A: TRENDING")
        print("✓ Trend Detection Logic PASSED")

    def test_chop_detection(self):
        """Tests if the engine correctly identifies maximum entropy (Score 4)"""
        result = analyze_market_regime(self.mock_chop_data)

        # We EXPECT the score to be 4 (all indicators triggered).
        self.assertEqual(result['regime_score'], 4, "Engine failed to identify high entropy chop.")
        self.assertEqual(result['regime_state'], "STATE C: HIGH ENTROPY / WHIPSAW")
        print("✓ Whipsaw Detection Logic PASSED")

    def test_dynamic_column_extraction(self):
        """Ensures the CHOP and ER values are not falling back to defaults silently"""
        result = analyze_market_regime(self.mock_trend_data)

        # In our mock data, CHOP is 30.0 and ER is 0.80
        self.assertEqual(result['chop_value'], 30.0, "CHOP value extraction failed!")
        self.assertEqual(result['er_value'], 0.80, "ER value extraction failed!")
        print("✓ Dynamic Indicator Extraction PASSED")


if __name__ == '__main__':
    print("\n--- RUNNING QUANT ENGINE UNIT TESTS ---\n")
    unittest.main(verbosity=2)