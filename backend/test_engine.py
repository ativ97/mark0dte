import unittest
import pandas as pd
import numpy as np
import sys
import os

# Ensure the backend directory is in the path so we can import engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the brain from your newly modularized code
from engine import analyze_market_regime


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


class TestConditionalExpectedMove(unittest.TestCase):
    """C1: Expected move should account for move already consumed from open."""

    def test_move_consumed_reduces_sigma(self):
        from data_fetcher import compute_expected_move
        result = compute_expected_move(5600, 15.0, vix9d=14.0, hours_remaining=4.0, day_open_spx=5535.0)
        self.assertLess(result["conditional_1sigma"], result["expected_1sigma"])
        self.assertGreater(result["move_consumed_pts"], 0)
        self.assertGreater(result["move_consumed_pct"], 1.0)

    def test_no_open_no_adjustment(self):
        from data_fetcher import compute_expected_move
        result = compute_expected_move(5600, 15.0, hours_remaining=4.0)
        self.assertEqual(result["conditional_1sigma"], result["expected_1sigma"])
        self.assertEqual(result["move_consumed_pts"], 0.0)

    def test_small_move_no_discount(self):
        from data_fetcher import compute_expected_move
        result = compute_expected_move(5600, 15.0, vix9d=14.0, hours_remaining=4.0, day_open_spx=5598.0)
        # 2 pts is well below 0.3σ threshold — no discount
        self.assertEqual(result["conditional_1sigma"], result["expected_1sigma"])

    def test_recommended_moat_uses_conditional(self):
        from data_fetcher import compute_expected_move
        base = compute_expected_move(5600, 15.0, vix9d=14.0, hours_remaining=4.0)
        consumed = compute_expected_move(5600, 15.0, vix9d=14.0, hours_remaining=4.0, day_open_spx=5500.0)
        self.assertLess(consumed["recommended_moat"], base["recommended_moat"])


class TestMoveConsumedSmartMoat(unittest.TestCase):
    """C4: Smart moat should tighten when intraday move is mostly consumed."""

    def _make_regime_data(self, hours=4.0):
        return {
            "regime_score": 1, "continuous_score": 1.5, "effective_moat_min": 45,
            "er_value": 0.35,
            "time_pressure": {
                "hours_remaining": hours,
                "market_events": {"events": [], "moat_multiplier": 1.0, "risk_level": "NORMAL"},
            },
        }

    def test_move_consumed_reduces_moat(self):
        from engine import compute_smart_moat
        rd = self._make_regime_data()
        base = compute_smart_moat(rd, 5600, 5665, 5535, 50.0)
        consumed = compute_smart_moat(rd, 5600, 5665, 5535, 50.0,
                                       expected_move_data={"move_consumed_pct": 1.5, "full_day_1sigma": 49.0})
        self.assertLess(consumed["smart_moat"], base["smart_moat"])
        self.assertLess(consumed["move_consumed_factor"], 1.0)

    def test_no_move_data_no_change(self):
        from engine import compute_smart_moat
        rd = self._make_regime_data()
        result = compute_smart_moat(rd, 5600, 5665, 5535, 50.0)
        self.assertEqual(result["move_consumed_factor"], 1.0)

    def test_move_consumed_floor(self):
        from engine import compute_smart_moat
        rd = self._make_regime_data()
        # Extreme: 5σ consumed — factor should floor at 0.65
        result = compute_smart_moat(rd, 5600, 5665, 5535, 50.0,
                                     expected_move_data={"move_consumed_pct": 5.0, "full_day_1sigma": 49.0})
        self.assertGreaterEqual(result["move_consumed_factor"], 0.65)


class TestReversalScore(unittest.TestCase):
    """C2: Reversal score should suppress false EJECT signals."""

    def _mock_pos(self, pos_type="Call Spread", strike=5630.0):
        from unittest.mock import MagicMock
        pos = MagicMock()
        pos.id = 99
        pos.type = pos_type
        pos.strike = strike
        pos.credit = 0.55
        pos.breach_start_time = None
        return pos

    def test_high_reversal_downgrades_exit(self):
        from engine import evaluate_positions, clear_rec_state
        from unittest.mock import MagicMock
        clear_rec_state()
        mock_db = MagicMock()
        gex = {"gex_regime": "POSITIVE", "gamma_wall_spx": 5615, "put_wall_spx": 5500,
               "call_wall_spx": 5650, "net_gex": 200000}
        result = evaluate_positions(
            [self._mock_pos()], 5610.0, mock_db,
            regime_score=1, effective_moat_min=40, directional_bias="BULLISH",
            range_position=92.0, hours_remaining=3.0, momentum_label="ACTIVE RALLY",
            gex_data=gex, rsi_14=68.0, er_value=0.08,
        )
        pos = result[0]
        self.assertTrue(pos["exit_strategy"].get("reversal_downgrade", False))
        self.assertEqual(pos["exit_strategy"]["action"], "HOLD_WITH_TRIGGER")
        self.assertGreaterEqual(pos["reversal_score"], 50)

    def test_low_reversal_keeps_exit(self):
        from engine import evaluate_positions, clear_rec_state
        from unittest.mock import MagicMock
        clear_rec_state()
        mock_db = MagicMock()
        # Neutral conditions: no reversal signals
        result = evaluate_positions(
            [self._mock_pos()], 5610.0, mock_db,
            regime_score=1, effective_moat_min=40, directional_bias="NEUTRAL",
            range_position=55.0, hours_remaining=3.0, momentum_label="RANGEBOUND",
            gex_data=None, rsi_14=50.0, er_value=0.40,
        )
        pos = result[0]
        self.assertFalse(pos["exit_strategy"].get("reversal_downgrade", False))
        self.assertLess(pos["reversal_score"], 50)


class TestTimeAdjustedTakeProfit(unittest.TestCase):
    """C3: Take profit threshold should vary with time remaining."""

    def _make_positions(self, profit_pct=85):
        """Create a position with given profit percentage."""
        credit = 0.50
        est_buyback = round(credit * (1 - profit_pct / 100), 2)
        return [{
            "id": 1, "type": "Put Spread", "strike": 5400, "credit": credit,
            "moat": 100, "estimated_buyback": est_buyback, "estimated_pl": round(credit - est_buyback, 2),
            "exit_strategy": {"action": "HOLD"}, "breakeven_event": None,
        }]

    def _regime(self, hours):
        return {
            "regime_score": 1, "regime_state": "STATE A: TRENDING",
            "directional_bias": "NEUTRAL", "er_value": 0.3,
            "effective_moat_min": 40,
            "time_pressure": {"hours_remaining": hours},
            "momentum": {"momentum_label": "RANGEBOUND"},
        }

    def test_early_day_needs_90pct(self):
        from engine import generate_recommendations
        # 85% profit, 4h left — should NOT trigger take profit (threshold is 90%)
        recs = generate_recommendations(
            self._make_positions(85), 5500.0, self._regime(4.0), 5550, 5450, 50.0)
        tp_recs = [r for r in recs if "TAKE PROFIT" in r.get("message", "")]
        self.assertEqual(len(tp_recs), 0, "Should not trigger take profit at 85% with >3h left")

    def test_early_day_triggers_at_90pct(self):
        from engine import generate_recommendations
        recs = generate_recommendations(
            self._make_positions(92), 5500.0, self._regime(4.0), 5550, 5450, 50.0)
        tp_recs = [r for r in recs if "TAKE PROFIT" in r.get("message", "")]
        self.assertEqual(len(tp_recs), 1, "Should trigger take profit at 92% with >3h left")

    def test_midday_triggers_at_80pct(self):
        from engine import generate_recommendations
        recs = generate_recommendations(
            self._make_positions(82), 5500.0, self._regime(2.5), 5550, 5450, 50.0)
        tp_recs = [r for r in recs if "TAKE PROFIT" in r.get("message", "")]
        self.assertEqual(len(tp_recs), 1, "Should trigger take profit at 82% with 2.5h left")

    def test_final_hour_triggers_at_50pct(self):
        from engine import generate_recommendations
        recs = generate_recommendations(
            self._make_positions(55), 5500.0, self._regime(0.5), 5550, 5450, 50.0)
        tp_recs = [r for r in recs if "TAKE PROFIT" in r.get("message", "")]
        self.assertEqual(len(tp_recs), 1, "Should trigger take profit at 55% in final hour")


class TestMomentumLabelFix(unittest.TestCase):
    """#37: RANGEBOUND should not fire when ER shows directional signal."""

    def _make_df(self, change_2h_pct=0.05, er=0.50):
        """Create a minimal DataFrame for momentum context testing."""
        n_bars = 30
        base_price = 550.0
        # Create bars with a slight trend matching change_2h_pct
        close_start = base_price * (1 - change_2h_pct / 100)
        closes = np.linspace(close_start, base_price, n_bars)
        df = pd.DataFrame({
            "Close": closes,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "RSI_14": [55.0] * n_bars,
            "ER_10": [er] * n_bars,
        })
        df.index = pd.date_range("2026-05-26 09:30", periods=n_bars, freq="5min",
                                  tz="America/New_York")
        return df

    def test_rangebound_when_er_low(self):
        from engine import _compute_momentum_context
        df = self._make_df(change_2h_pct=0.05, er=0.08)
        result = _compute_momentum_context(df)
        self.assertEqual(result["momentum_label"], "RANGEBOUND")

    def test_no_rangebound_when_er_high(self):
        from engine import _compute_momentum_context
        df = self._make_df(change_2h_pct=0.05, er=0.50)
        result = _compute_momentum_context(df)
        self.assertNotEqual(result["momentum_label"], "RANGEBOUND",
                           "RANGEBOUND should not fire when ER > 0.25")
        self.assertIn("DRIFT", result["momentum_label"])


class TestImportSmokeTest(unittest.TestCase):
    """Verify all backend modules import cleanly — catches syntax errors and bad references."""

    def test_engine_imports(self):
        import engine
        for fn in ['analyze_market_regime', 'evaluate_positions', 'generate_recommendations',
                    'compute_smart_moat', 'generate_market_insights', 'auto_propose_positions']:
            self.assertTrue(hasattr(engine, fn), f"engine.{fn} missing")

    def test_main_imports(self):
        import main
        self.assertTrue(hasattr(main, 'app'))

    def test_data_fetcher_imports(self):
        import data_fetcher
        for fn in ['fetch_alpaca_market_data', 'compute_expected_move', 'fetch_gex_data']:
            self.assertTrue(hasattr(data_fetcher, fn), f"data_fetcher.{fn} missing")


class TestGenerateMarketInsightsEdgeCases(unittest.TestCase):
    """Regression tests for generate_market_insights edge cases."""

    def test_trigger_spx_none_does_not_crash(self):
        """trigger_spx=None in exit_strategy must not cause TypeError."""
        from engine import generate_market_insights
        regime_data = {
            "regime_state": "STATE C HIGH ENTROPY / WHIPSAW",
            "regime_score": 4,
            "er_value": 0.04,
            "directional_bias": "NEUTRAL",
            "time_pressure": {"hours_remaining": 2.0, "time_pressure_level": "LOW"},
            "momentum": {"momentum_label": "RANGEBOUND"},
            "rsi_14": 50.0,
        }
        pos = {
            "id": 1, "type": "Call Spread", "strike": 7555.0, "credit": 0.60,
            "moat": 36.0, "moat_pct": 50.0,
            "exit_strategy": {"action": "CLOSE_SOON", "trigger_spx": None, "escalation_level": 1},
            "estimated_buyback": 0.30, "reversal_score": 0,
        }
        # Should not raise TypeError
        result = generate_market_insights(
            regime_data=regime_data,
            evaluated_positions=[pos],
            smart_moat_data={"smart_moat": 30, "moat_explanation": "test"},
        )
        self.assertIn("position_cards", result)
        self.assertEqual(len(result["position_cards"]), 1)


if __name__ == '__main__':
    print("\n--- RUNNING QUANT ENGINE UNIT TESTS ---\n")
    unittest.main(verbosity=2)