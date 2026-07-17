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


class TestERGatedMoveConsumed(unittest.TestCase):
    """Phase 5A: move_consumed_factor should be gated on ER."""

    def _make_regime_data(self, er_value=0.35, hours=4.0):
        return {
            "regime_score": 1, "continuous_score": 1.5, "effective_moat_min": 45,
            "er_value": er_value,
            "time_pressure": {
                "hours_remaining": hours,
                "market_events": {"events": [], "moat_multiplier": 1.0, "risk_level": "NORMAL"},
            },
        }

    def test_high_er_allows_full_shrink(self):
        from engine import compute_smart_moat
        rd = self._make_regime_data(er_value=0.40)
        result = compute_smart_moat(rd, 5600, 5665, 5535, 50.0,
                                     expected_move_data={"move_consumed_pct": 1.5, "full_day_1sigma": 49.0})
        self.assertLess(result["move_consumed_factor"], 0.90)
        self.assertFalse(result["move_consumed_blocked"])

    def test_low_er_blocks_shrink(self):
        from engine import compute_smart_moat
        rd = self._make_regime_data(er_value=0.08)
        result = compute_smart_moat(rd, 5600, 5665, 5535, 50.0,
                                     expected_move_data={"move_consumed_pct": 1.5, "full_day_1sigma": 49.0})
        self.assertEqual(result["move_consumed_factor"], 1.0)
        self.assertTrue(result["move_consumed_blocked"])

    def test_moderate_er_half_effect(self):
        from engine import compute_smart_moat
        rd = self._make_regime_data(er_value=0.20)
        result = compute_smart_moat(rd, 5600, 5665, 5535, 50.0,
                                     expected_move_data={"move_consumed_pct": 1.5, "full_day_1sigma": 49.0})
        self.assertGreaterEqual(result["move_consumed_factor"], 0.85)
        self.assertLess(result["move_consumed_factor"], 1.0)
        self.assertFalse(result["move_consumed_blocked"])


class TestPortfolioHeat(unittest.TestCase):
    """Phase 5B: Portfolio concentration risk detection."""

    def _mock_pos(self, pos_type="Call Spread"):
        from unittest.mock import MagicMock
        p = MagicMock()
        p.type = pos_type
        return p

    def test_all_calls_is_danger(self):
        from engine import calculate_portfolio_heat
        positions = [self._mock_pos("Call Spread"), self._mock_pos("Call Spread")]
        result = calculate_portfolio_heat(positions)
        self.assertEqual(result["level"], "DANGER")
        self.assertIn("TOP-SIDE", result["warning"])

    def test_balanced_is_safe(self):
        from engine import calculate_portfolio_heat
        positions = [self._mock_pos("Call Spread"), self._mock_pos("Put Spread")]
        result = calculate_portfolio_heat(positions)
        self.assertEqual(result["level"], "SAFE")
        self.assertIsNone(result["warning"])

    def test_high_total_risk_bumps_level(self):
        """Bug C: balanced sides but total $-risk over the ceiling = DANGER (exposure, not just balance)."""
        from engine import calculate_portfolio_heat
        from types import SimpleNamespace
        positions = [SimpleNamespace(type="Call Spread", credit=0.50, contracts=20),
                     SimpleNamespace(type="Put Spread", credit=0.50, contracts=20)]
        result = calculate_portfolio_heat(positions)
        self.assertEqual(result["level"], "DANGER")
        self.assertIsNotNone(result["total_max_loss"])
        self.assertGreater(result["total_max_loss"], 7500)

    def test_red_leg_blocks_safe(self):
        """Bug C: a balanced, small book can't read SAFE while a leg is flagged to close."""
        from engine import calculate_portfolio_heat
        from types import SimpleNamespace
        positions = [SimpleNamespace(type="Call Spread", credit=0.50, contracts=1),
                     SimpleNamespace(type="Put Spread", credit=0.50, contracts=1)]
        evaluated = [{"type": "Call Spread", "moat": 8.0,
                      "exit_strategy": {"escalation_level": "CRITICAL_EJECT", "action": "CLOSE_SOON"}},
                     {"type": "Put Spread", "moat": 40.0,
                      "exit_strategy": {"escalation_level": "SAFE", "action": "HOLD"}}]
        result = calculate_portfolio_heat(positions, evaluated_positions=evaluated)
        self.assertNotEqual(result["level"], "SAFE")


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


class TestGexHysteresisAndSideAware(unittest.TestCase):
    """2026-06-01: GEX regime deadband + side-aware mean_reverting + mean-reversion read."""

    def test_stabilize_flips_only_past_band(self):
        from engine import stabilize_gex_regime
        self.assertEqual(stabilize_gex_regime(50_000_000, None), "POSITIVE")
        self.assertEqual(stabilize_gex_regime(-50_000_000, None), "NEGATIVE")

    def test_stabilize_sticky_within_band(self):
        from engine import stabilize_gex_regime
        # within the +/-20M deadband: hold the previous strong regime instead of flipping
        self.assertEqual(stabilize_gex_regime(1_000_000, "POSITIVE"), "POSITIVE")
        self.assertEqual(stabilize_gex_regime(-6_000_000, "POSITIVE"), "POSITIVE")
        self.assertEqual(stabilize_gex_regime(1_000_000, None), "NEUTRAL")

    def test_mean_reversion_on_off(self):
        from engine import mean_reversion_status
        on = mean_reversion_status({"gex_regime": "POSITIVE"},
                                   {"regime_state": "STATE B: MODERATE CHOP", "er_value": 0.2}, None)
        self.assertTrue(on["on"])
        off = mean_reversion_status({"gex_regime": "NEGATIVE"},
                                    {"regime_state": "STATE C", "er_value": 0.5}, None)
        self.assertFalse(off["on"])

    def test_side_aware_call_below_magnet_not_protected(self):
        """Bug D: a short call BELOW the gamma magnet (wall above strike) is NOT mean-reverting-
        protected even in positive GEX — the magnet drags price toward the strike (6/1 7605 call)."""
        from engine import evaluate_positions, clear_rec_state
        from unittest.mock import MagicMock
        clear_rec_state()
        pos = MagicMock()
        pos.id = 77; pos.type = "Call Spread"; pos.strike = 7605.0
        pos.credit = 0.65; pos.contracts = 10; pos.breach_start_time = None
        gex = {"gex_regime": "POSITIVE", "gamma_wall_spx": 7617, "put_wall_spx": 7517,
               "call_wall_spx": 7617, "net_gex": 80_000_000}
        result = evaluate_positions(
            [pos], 7580.0, MagicMock(),
            regime_score=1, effective_moat_min=50, directional_bias="BULLISH",
            range_position=50.0, hours_remaining=4.0, momentum_label="MILD DRIFT UP",
            gex_data=gex, rsi_14=60.0, er_value=0.3,
        )
        self.assertFalse(result[0]["mean_reverting"])
        self.assertTrue(result[0]["trend_continuation"])

    def test_rsi_50_price_below_when_overbought(self):
        from engine import compute_rsi_50_price
        closes = [100 + i for i in range(30)]   # steady uptrend → RSI>50 → target BELOW last close
        p = compute_rsi_50_price(closes)
        self.assertIsNotNone(p)
        self.assertLess(p, closes[-1])

    def test_rsi_50_price_above_when_oversold(self):
        from engine import compute_rsi_50_price
        closes = [100 - i for i in range(30)]   # steady downtrend → RSI<50 → target ABOVE last close
        p = compute_rsi_50_price(closes)
        self.assertIsNotNone(p)
        self.assertGreater(p, closes[-1])

    def test_rsi_50_price_insufficient_data(self):
        from engine import compute_rsi_50_price
        self.assertIsNone(compute_rsi_50_price([100, 101, 102]))

    def test_magnet_forces_wall_favored_positive_gex(self):
        from engine import compute_magnet_forces
        r = compute_magnet_forces(
            spx_price=7595.0,
            gex_data={"gex_regime": "POSITIVE", "net_gex": 100e6, "gamma_wall_spx": 7617.0},
            rsi_14=66.0,
            regime_data={"er_value": 0.35, "regime_state": "STATE A: TRENDING", "directional_bias": "BULLISH"},
            expected_move_data={"conditional_1sigma": 45.0},
            rsi_50_spx=7580.0, hours_remaining=3.0,
        )
        self.assertFalse(r["trend_dominant"])
        self.assertEqual(r["predicted_magnet"], "GEX Wall")
        self.assertEqual(r["predicted_level"], 7617)
        self.assertTrue(0 <= r["touch_prob"] <= 100)

    def test_magnet_forces_trend_dominant_negative_gex(self):
        from engine import compute_magnet_forces
        r = compute_magnet_forces(
            spx_price=7480.0,
            gex_data={"gex_regime": "NEGATIVE", "net_gex": -90e6, "gamma_wall_spx": 7520.0},
            rsi_14=28.0,
            regime_data={"er_value": 0.62, "regime_state": "STATE A: TRENDING", "directional_bias": "BEARISH"},
            expected_move_data={"conditional_1sigma": 50.0},
            rsi_50_spx=7500.0, hours_remaining=2.0,
        )
        self.assertTrue(r["trend_dominant"])
        self.assertEqual(r["predicted_magnet"], "Trend")
        self.assertIsNone(r["predicted_level"])

    def test_magnet_forces_returns_native_types(self):
        """Regression (2026-06-01 serialization crash): numpy.float64 inputs must yield NATIVE
        Python types — Pydantic cannot serialize numpy.bool_/float64 (crashed serialize_response)."""
        import numpy as np
        from engine import compute_magnet_forces
        r = compute_magnet_forces(
            spx_price=np.float64(7595.0),
            gex_data={"gex_regime": "POSITIVE", "net_gex": np.float64(100e6), "gamma_wall_spx": np.float64(7617.0)},
            rsi_14=np.float64(66.0),
            regime_data={"er_value": np.float64(0.35), "regime_state": "STATE A: TRENDING", "directional_bias": "BULLISH"},
            expected_move_data={"conditional_1sigma": np.float64(45.0)},
            rsi_50_spx=np.float64(7580.0), hours_remaining=np.float64(3.0),
        )
        self.assertIsInstance(r["trend_dominant"], bool)
        self.assertNotIsInstance(r["trend_dominant"], np.generic)
        for f in r["forces"]:
            self.assertIsInstance(f["strength"], int)


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


class TestSurgeDetection(unittest.TestCase):
    """Phase 6A: Rolling surge detector."""

    def test_no_surge_small_move(self):
        from engine import detect_surge
        snapshots = [{"spx_price": 5600.0, "timestamp": "2026-05-28 14:00:00 UTC"}]
        result = detect_surge(5605.0, snapshots, er_value=0.35, hours_remaining=4.0)
        self.assertEqual(result["surge_type"], "NONE")

    def test_trend_surge_high_er(self):
        from engine import detect_surge
        snapshots = [{"spx_price": 5600.0, "timestamp": "2026-05-28 14:00:00 UTC"},
                     {"spx_price": 5610.0, "timestamp": "2026-05-28 14:05:00 UTC"}]
        # 0.7% move with ER 0.40 = TREND_SURGE
        result = detect_surge(5640.0, snapshots, er_value=0.40, hours_remaining=4.0)
        self.assertEqual(result["surge_type"], "TREND_SURGE")
        self.assertEqual(result["surge_direction"], "BULLISH")
        self.assertGreater(result["fade_multiplier"], 0)

    def test_volatile_surge_low_er(self):
        from engine import detect_surge
        snapshots = [{"spx_price": 5600.0, "timestamp": "2026-05-28 14:00:00 UTC"},
                     {"spx_price": 5610.0, "timestamp": "2026-05-28 14:05:00 UTC"}]
        # 0.7% move with ER 0.10 = VOLATILE_SURGE
        result = detect_surge(5640.0, snapshots, er_value=0.10, hours_remaining=4.0)
        self.assertEqual(result["surge_type"], "VOLATILE_SURGE")


class TestGapRejection(unittest.TestCase):
    """Phase 6H: Gap & Crap detection."""

    def test_gap_up_rejected(self):
        from engine import detect_gap_rejection
        ib_data = {"state": "IB_ESTABLISHED", "gap_pct": 0.8, "ib_high_spx": 5650.0, "ib_low_spx": 5620.0}
        result = detect_gap_rejection(spx_price=5610.0, ib_data=ib_data)
        self.assertTrue(result["rejected"])
        self.assertEqual(result["direction"], "BEARISH")

    def test_no_rejection_inside_ib(self):
        from engine import detect_gap_rejection
        ib_data = {"state": "IB_ESTABLISHED", "gap_pct": 0.8, "ib_high_spx": 5650.0, "ib_low_spx": 5620.0}
        result = detect_gap_rejection(spx_price=5635.0, ib_data=ib_data)
        self.assertFalse(result["rejected"])


class TestLiveSpreadQuoteLookup(unittest.TestCase):
    """Phase 7: Test spread buyback price computation from mock quotes.
    SPX $5 spread maps to SPY ~$1 spread. SPY mid × width_ratio = SPX equivalent.
    """

    def test_call_spread_mid_price(self):
        from data_fetcher import get_spread_buyback_price
        # SPX 7560/7565 → SPY 756/757 (ratio=10.0, $5 SPX = $1 SPY)
        quotes = {
            (756.0, "CALL"): {"bid": 0.16, "ask": 0.18, "mid": 0.17},
            (757.0, "CALL"): {"bid": 0.07, "ask": 0.09, "mid": 0.08},
        }
        result = get_spread_buyback_price(quotes, "Call Spread", 7560.0, spx_spy_ratio=10.0, spread_width_spx=5.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["pricing_source"], "LIVE")
        # SPY spread = 0.17 - 0.08 = 0.09, × width_ratio 5 = 0.45
        self.assertAlmostEqual(result["spread_mid"], 0.45, places=2)
        self.assertEqual(result["width_ratio"], 5.0)

    def test_put_spread_mid_price(self):
        from data_fetcher import get_spread_buyback_price
        # SPX 7500/7495 → SPY 750/749 (ratio=10.0)
        quotes = {
            (750.0, "PUT"): {"bid": 0.50, "ask": 0.52, "mid": 0.51},
            (749.0, "PUT"): {"bid": 0.38, "ask": 0.40, "mid": 0.39},
        }
        result = get_spread_buyback_price(quotes, "Put Spread", 7500.0, spx_spy_ratio=10.0, spread_width_spx=5.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["pricing_source"], "LIVE")
        # SPY spread = 0.51 - 0.39 = 0.12, × width_ratio 5 = 0.60
        self.assertAlmostEqual(result["spread_mid"], 0.60, places=2)

    def test_missing_strike_returns_none(self):
        from data_fetcher import get_spread_buyback_price
        quotes = {
            (755.0, "CALL"): {"bid": 0.10, "ask": 0.12, "mid": 0.11},
        }
        result = get_spread_buyback_price(quotes, "Call Spread", 7600.0, spx_spy_ratio=10.0)
        self.assertIsNone(result)


class TestSPXWDirectPricing(unittest.TestCase):
    """Phase 9E: Test SPXW direct pricing mode (no SPY conversion needed)."""

    def test_spxw_call_spread_direct(self):
        from data_fetcher import get_spread_buyback_price
        # SPXW quotes with SPX strikes directly
        quotes = {
            (7580.0, "CALL"): {"bid": 0.40, "ask": 0.50, "mid": 0.45},
            (7585.0, "CALL"): {"bid": 0.10, "ask": 0.15, "mid": 0.125},
        }
        result = get_spread_buyback_price(
            quotes, "Call Spread", 7580.0, quote_source="SPXW", spread_width_spx=5.0
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["pricing_source"], "SPXW")
        # Direct: 0.45 - 0.125 = 0.325, width_ratio = 1.0
        self.assertAlmostEqual(result["spread_mid"], 0.33, places=2)
        self.assertEqual(result["width_ratio"], 1.0)

    def test_spxw_put_spread_direct(self):
        from data_fetcher import get_spread_buyback_price
        quotes = {
            (7500.0, "PUT"): {"bid": 0.55, "ask": 0.65, "mid": 0.60},
            (7495.0, "PUT"): {"bid": 0.30, "ask": 0.40, "mid": 0.35},
        }
        result = get_spread_buyback_price(
            quotes, "Put Spread", 7500.0, quote_source="SPXW", spread_width_spx=5.0
        )
        self.assertIsNotNone(result)
        # Direct: 0.60 - 0.35 = 0.25
        self.assertAlmostEqual(result["spread_mid"], 0.25, places=2)

    def test_spxw_ask_side_close_exceeds_mid(self):
        """P1-5: the realistic ask-side close (buy short@ask, sell long@bid) is >= the mid."""
        from data_fetcher import get_spread_buyback_price
        quotes = {
            (7580.0, "CALL"): {"bid": 0.40, "ask": 0.50, "mid": 0.45},
            (7585.0, "CALL"): {"bid": 0.10, "ask": 0.15, "mid": 0.125},
        }
        result = get_spread_buyback_price(
            quotes, "Call Spread", 7580.0, quote_source="SPXW", spread_width_spx=5.0
        )
        self.assertIn("spread_ask_close", result)
        # short ask 0.50 − long bid 0.10 = 0.40 (vs mid 0.33)
        self.assertAlmostEqual(result["spread_ask_close"], 0.40, places=2)
        self.assertGreaterEqual(result["spread_ask_close"], result["spread_mid"])

    def test_spy_fallback_still_works(self):
        from data_fetcher import get_spread_buyback_price
        # SPY proxy mode (default)
        quotes = {
            (756.0, "CALL"): {"bid": 0.16, "ask": 0.18, "mid": 0.17},
            (757.0, "CALL"): {"bid": 0.07, "ask": 0.09, "mid": 0.08},
        }
        result = get_spread_buyback_price(
            quotes, "Call Spread", 7560.0, spx_spy_ratio=10.0,
            spread_width_spx=5.0, quote_source="SPY"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["pricing_source"], "LIVE")
        self.assertAlmostEqual(result["spread_mid"], 0.45, places=2)


class TestPostEventDetection(unittest.TestCase):
    """Phase 9H: Test post-event regime shift detection."""

    def test_no_event_returns_none(self):
        from engine import detect_post_event_shift
        events = {"events": [], "moat_multiplier": 1.0, "risk_level": "NORMAL", "event_time_et": None}
        result = detect_post_event_shift(events, [], 7560.0, 0.5, 50.0, 50.0)
        self.assertIsNone(result)

    def test_event_breakout_detected(self):
        from engine import detect_post_event_shift
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        # Simulate: we're 10min after a 14:00 ET event
        now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("US/Eastern"))
        current_hour = now_et.hour + now_et.minute / 60.0
        # Set event_time so we're 10 min past it
        fake_event_time = current_hour - (10.0 / 60.0)
        events = {"event_time_et": fake_event_time}

        # Pre-event snapshot 15 min before event
        pre_ts = datetime.now(timezone.utc)
        from datetime import timedelta
        pre_ts = pre_ts - timedelta(minutes=25)
        snap = {
            "spx_price": 7540.0, "er_value": 0.30, "rsi_14": 50.0,
            "timestamp": pre_ts.strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        result = detect_post_event_shift(events, [snap], 7560.0, 0.45, 65.0, 80.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["phase"], "POST_EVENT")
        self.assertEqual(result["shift_type"], "EVENT_BREAKOUT")
        self.assertGreater(result["spx_move_pts"], 10)


class TestImportSmokeTest(unittest.TestCase):
    """Verify all backend modules import cleanly — catches syntax errors and bad references."""

    def test_engine_imports(self):
        import engine
        for fn in ['analyze_market_regime', 'evaluate_positions', 'generate_recommendations',
                    'compute_smart_moat', 'generate_market_insights', 'auto_propose_positions',
                    'detect_surge', 'compute_initial_balance', 'detect_gap_rejection',
                    'calculate_portfolio_heat', 'detect_post_event_shift']:
            self.assertTrue(hasattr(engine, fn), f"engine.{fn} missing")

    def test_main_imports(self):
        import main
        self.assertTrue(hasattr(main, 'app'))

    def test_data_fetcher_imports(self):
        import data_fetcher
        for fn in ['fetch_alpaca_market_data', 'compute_expected_move', 'fetch_gex_data',
                    'fetch_live_option_quotes', 'get_spread_buyback_price',
                    '_lookup_spread_direct', '_lookup_spread_spy_proxy']:
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


class TestProfitAwareEscalation(unittest.TestCase):
    """Regression: profitable positions in warning zone should not get CRITICAL_EJECT."""

    def test_profitable_position_caps_escalation(self):
        """A 67% profitable position in warning zone should get TAKE_PROFIT, not CRITICAL_EJECT."""
        from engine import evaluate_positions, _escalation_state, ESCALATION_LEVELS
        from database import PositionDB
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # Pre-seed escalation to CRITICAL_EJECT (simulating 12+ minutes in danger zone)
        _escalation_state[999] = {
            "level": "CRITICAL_EJECT",
            "entered_at": now,
            "escalated_at": now,
        }

        pos = PositionDB(id=999, type="Call Spread", strike=7580.0, credit=0.60)
        # SPXW quotes use (strike, right) tuple keys
        live_quotes = {
            (7580.0, "CALL"): {"bid": 0.15, "ask": 0.25, "mid": 0.20},   # short leg
            (7585.0, "CALL"): {"bid": 0.01, "ask": 0.05, "mid": 0.03},   # long leg (5 pts wide)
        }
        results = evaluate_positions(
            db_positions=[pos],
            db_session=None,
            spx_price=7560.0,  # moat = 20 pts (in warning zone)
            regime_score=3,
            effective_moat_min=39,
            hours_remaining=2.4,
            live_quotes=live_quotes,
            spx_spy_ratio=10.0,
            quote_source="SPXW",
        )
        self.assertEqual(len(results), 1)
        exit_strat = results[0]["exit_strategy"]
        # Must NOT be CRITICAL_EJECT or URGENT_CLOSE when profitable
        self.assertNotIn(exit_strat["escalation_level"], ("CRITICAL_EJECT", "URGENT_CLOSE"),
                         f"Profitable position should not get {exit_strat['escalation_level']}")
        # Clean up
        _escalation_state.pop(999, None)

    def test_unprofitable_position_keeps_escalation(self):
        """A losing position in warning zone should retain CRITICAL_EJECT."""
        from engine import evaluate_positions, _escalation_state
        from database import PositionDB
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        _escalation_state[998] = {
            "level": "CRITICAL_EJECT",
            "entered_at": now,
            "escalated_at": now,
        }

        pos = PositionDB(id=998, type="Call Spread", strike=7580.0, credit=0.30)
        results = evaluate_positions(
            db_positions=[pos],
            db_session=None,
            spx_price=7560.0,  # moat = 20 pts, but credit only 0.30 → likely losing
            regime_score=3,
            effective_moat_min=39,
            hours_remaining=2.4,
            spx_spy_ratio=10.0,
        )
        self.assertEqual(len(results), 1)
        exit_strat = results[0]["exit_strategy"]
        # With no live quotes and heuristic buyback, a 0.30 credit at 20 pts moat
        # should be estimated as losing → escalation should NOT be capped
        # (escalation cap only applies at profit_pct >= 50)
        self.assertIn(exit_strat["escalation_level"], ("CRITICAL_EJECT", "URGENT_CLOSE", "CLOSE_RECOMMENDED"),
                      "Unprofitable position should retain high escalation")
        _escalation_state.pop(998, None)

    def test_est_pricing_does_not_cap_escalation(self):
        """P0-1: with EST (heuristic) pricing, a CRITICAL_EJECT must NOT be softened to
        TAKE_PROFIT/CLOSE_RECOMMENDED — an untrustworthy price can't mask real danger."""
        from engine import evaluate_positions, _escalation_state
        from database import PositionDB
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        _escalation_state[997] = {"level": "CRITICAL_EJECT", "entered_at": now, "escalated_at": now}
        pos = PositionDB(id=997, type="Call Spread", strike=7580.0, credit=0.60)
        results = evaluate_positions(
            db_positions=[pos], db_session=None, spx_price=7560.0,
            regime_score=3, effective_moat_min=39, hours_remaining=2.4,
            spx_spy_ratio=10.0,   # NO live_quotes → pricing_source == "EST"
        )
        exit_strat = results[0]["exit_strategy"]
        self.assertEqual(results[0]["pricing_source"], "EST")
        self.assertNotEqual(exit_strat["action"], "TAKE_PROFIT",
                            "EST pricing must not produce a TAKE_PROFIT downgrade")
        self.assertIn(exit_strat["escalation_level"], ("CRITICAL_EJECT", "URGENT_CLOSE"),
                      "EST pricing must not cap escalation below URGENT")
        _escalation_state.pop(997, None)


class TestSignalOutcomeTracker(unittest.TestCase):
    """Tests for the Signal Outcome Tracker v2 (accuracy_tracker.py)."""

    def test_exit_signal_correct_when_position_deteriorated(self):
        """EXIT signal is CORRECT when final cost > buyback at signal time."""
        from accuracy_tracker import _grade_signal
        signal = {
            "is_exit_signal": True,
            "buyback_at_signal": 0.20,
            "credit": 0.60,
            "realized_pl": 0.10,  # closed at $0.50 → final_cost = 0.60 - 0.10 = 0.50
            "close_reason": "manual",
            "worst_moat_after": 8.0,
        }
        result = _grade_signal(signal)
        self.assertEqual(result["signal_grade"], "CORRECT")
        self.assertAlmostEqual(result["exit_savings"], 0.30)  # 0.50 - 0.20

    def test_exit_signal_premature_when_position_recovered(self):
        """EXIT signal is PREMATURE when position recovered and cost less to hold."""
        from accuracy_tracker import _grade_signal
        signal = {
            "is_exit_signal": True,
            "buyback_at_signal": 0.20,
            "credit": 0.60,
            "realized_pl": 0.55,  # closed at $0.05 → final_cost = 0.05
            "close_reason": "manual",
            "worst_moat_after": 25.0,  # Never entered danger
        }
        result = _grade_signal(signal)
        self.assertEqual(result["signal_grade"], "PREMATURE")
        self.assertAlmostEqual(result["exit_savings"], -0.15)  # 0.05 - 0.20

    def test_exit_signal_justified_when_risk_was_real(self):
        """EXIT signal is JUSTIFIED when premature but moat hit gamma trap."""
        from accuracy_tracker import _grade_signal
        signal = {
            "is_exit_signal": True,
            "buyback_at_signal": 0.20,
            "credit": 0.60,
            "realized_pl": 0.55,  # final_cost = 0.05
            "close_reason": "manual",
            "worst_moat_after": 5.0,  # Hit gamma trap!
        }
        result = _grade_signal(signal)
        self.assertEqual(result["signal_grade"], "JUSTIFIED")

    def test_exit_signal_justified_when_over_cap(self):
        """2026-06-01: EXIT is JUSTIFIED (not PREMATURE) when the position was over the sizing
        cap, even if it recovered and never entered the warning zone."""
        from accuracy_tracker import _grade_signal
        signal = {
            "is_exit_signal": True,
            "buyback_at_signal": 0.20,
            "credit": 0.60,
            "realized_pl": 0.55,  # final_cost = 0.05 (recovered)
            "close_reason": "manual",
            "worst_moat_after": 40.0,  # never entered the warning zone
            "over_limit_at_signal": True,
        }
        result = _grade_signal(signal)
        self.assertEqual(result["signal_grade"], "JUSTIFIED")

    def test_hold_signal_correct_on_profitable_trade(self):
        """HOLD signal is CORRECT when trade ended profitably."""
        from accuracy_tracker import _grade_signal
        signal = {
            "is_exit_signal": False,
            "credit": 0.60,
            "realized_pl": 0.60,
            "close_reason": "expired_otm",
            "worst_moat_after": 30.0,
        }
        result = _grade_signal(signal)
        self.assertEqual(result["signal_grade"], "CORRECT")

    def test_hold_signal_wrong_on_losing_trade(self):
        """HOLD signal is WRONG when trade lost money."""
        from accuracy_tracker import _grade_signal
        signal = {
            "is_exit_signal": False,
            "credit": 0.60,
            "realized_pl": -4.40,
            "close_reason": "expired_itm",
            "worst_moat_after": -5.0,
        }
        result = _grade_signal(signal)
        self.assertEqual(result["signal_grade"], "WRONG")

    def test_track_signal_transitions_and_tracking(self):
        """track_signal logs transitions and updates tracking on same action."""
        from accuracy_tracker import track_signal, _active_signals, clear_position_state

        # Clean state
        clear_position_state(777)

        # First call: creates new signal
        track_signal(777, "Call Spread", 7580.0, 0.60, "HOLD", 2, 40.0,
                     spx_price=7540.0, buyback=0.10, hours_remaining=3.0)
        self.assertIn(777, _active_signals)
        sig = _active_signals[777]
        self.assertEqual(sig["action"], "HOLD")
        self.assertEqual(sig["moat_at_signal"], 40.0)
        self.assertEqual(sig["tracking_samples"], 0)

        # Second call same action: updates tracking
        track_signal(777, "Call Spread", 7580.0, 0.60, "HOLD", 2, 35.0,
                     spx_price=7545.0, buyback=0.15, hours_remaining=2.5)
        self.assertEqual(_active_signals[777]["worst_moat_after"], 35.0)
        self.assertEqual(_active_signals[777]["worst_buyback_after"], 0.15)
        self.assertEqual(_active_signals[777]["tracking_samples"], 1)

        # Third call different action: transition
        track_signal(777, "Call Spread", 7580.0, 0.60, "CLOSE_SOON", 3, 20.0,
                     spx_price=7560.0, buyback=0.25, hours_remaining=2.0)
        self.assertEqual(_active_signals[777]["action"], "CLOSE_SOON")
        self.assertEqual(_active_signals[777]["moat_at_signal"], 20.0)
        self.assertTrue(_active_signals[777]["is_exit_signal"])

        # Clean up
        clear_position_state(777)

    def test_take_profit_classified_as_exit(self):
        """TAKE_PROFIT should be classified as an exit signal."""
        from accuracy_tracker import _EXIT_ACTIONS
        self.assertIn("TAKE_PROFIT", _EXIT_ACTIONS)

    def test_resolve_expired_grades_and_clears(self):
        """P0-6: an open signal is graded + cleared at expiry (no unresolved leak)."""
        from accuracy_tracker import (track_signal, resolve_expired_positions,
                                      _active_signals, clear_position_state)
        clear_position_state(8888)
        track_signal(8888, "Put Spread", 7550.0, 0.74, "HOLD_FOR_EXPIRY",
                     regime_score=2, moat=30.0, buyback=0.30)
        self.assertIn(8888, _active_signals)
        # Expired OTM (moat > 0) → resolved, graded, removed from active
        n = resolve_expired_positions([{"id": 8888, "moat": 12.0, "credit": 0.74}])
        self.assertEqual(n, 1)
        self.assertNotIn(8888, _active_signals)
        # Idempotent — nothing left to resolve
        self.assertEqual(resolve_expired_positions([{"id": 8888, "moat": 12.0, "credit": 0.74}]), 0)


class TestPositionSizing(unittest.TestCase):
    """P0-3 sizing guardrail (added 2026-05-29 from the live-session sizing lesson)."""

    def test_todays_20lot_flagged_over_limit(self):
        from engine import calculate_position_risk
        r = calculate_position_risk(20, spread_width=5.0, credit=0.74,
                                    account_size=10000.0, max_risk=2000.0)
        self.assertTrue(r["over_limit"])
        self.assertAlmostEqual(r["max_loss"], 8520.0)
        self.assertEqual(r["pct_of_account"], 85.2)

    def test_within_cap_not_flagged(self):
        from engine import calculate_position_risk
        r = calculate_position_risk(4, spread_width=5.0, credit=0.74,
                                    account_size=10000.0, max_risk=2000.0)
        self.assertFalse(r["over_limit"])              # 4 lots = $1,704 < $2,000
        self.assertEqual(r["max_contracts_allowed"], 4)  # 2000 // 426 = 4

    def test_warn_tier_between_warn_and_hard(self):
        """P0-3 2-tier: a size between the warn and hard caps flags warn (amber), not over-limit (red)."""
        from engine import calculate_position_risk
        # 12 lots $5-wide @ $0.74 → max loss $5,112: above $4,500 warn, below $9,000 hard
        r = calculate_position_risk(12, spread_width=5.0, credit=0.74,
                                    account_size=18000.0, max_risk=9000.0, warn_risk=4500.0)
        self.assertTrue(r["warn_limit"])
        self.assertFalse(r["over_limit"])


class TestMagnetTouchProb(unittest.TestCase):
    """2026-06-02 live session: the magnet touch% must not overclaim on a level price has
    already tagged today, or one hugging spot (prob saturates ~100%). Increment #1 of the
    wasted-signals build (kills the recurring vacuous '~95% touch' read)."""

    GEX = {"gex_regime": "POSITIVE", "net_gex": 35_000_000.0, "gamma_wall_spx": 7636}
    EM = {"conditional_1sigma": 65.6}

    def test_already_touched_level_suppresses_touch_prob(self):
        from engine import compute_magnet_forces
        m = compute_magnet_forces(
            7592.9, self.GEX, 59.7,
            {"er_value": 0.09, "regime_state": "STATE B", "directional_bias": "LEAN BULLISH"},
            self.EM, rsi_50_spx=7588, hours_remaining=6.45, day_high=7595.4, day_low=7583.7)
        self.assertTrue(m["already_touched"])
        self.assertIsNone(m["touch_prob"])
        self.assertEqual(m["touch_basis"], "already_touched")
        self.assertIn("already tagged", m["headline"].lower())

    def test_far_untouched_level_keeps_touch_prob(self):
        from engine import compute_magnet_forces
        m = compute_magnet_forces(
            7593.0, self.GEX, 66,
            {"er_value": 0.33, "regime_state": "STATE A", "directional_bias": "BULLISH"},
            self.EM, rsi_50_spx=7590, hours_remaining=5.9, day_high=7596.0, day_low=7583.0)
        self.assertEqual(m["predicted_magnet"], "GEX Wall")
        self.assertIsNotNone(m["touch_prob"])
        self.assertEqual(m["touch_basis"], "distribution")

    def test_backward_compatible_without_day_range(self):
        from engine import compute_magnet_forces
        m = compute_magnet_forces(
            7593.0, self.GEX, 66,
            {"er_value": 0.33, "regime_state": "STATE A", "directional_bias": "BULLISH"},
            self.EM, rsi_50_spx=7590, hours_remaining=5.9)
        self.assertFalse(m["already_touched"])
        self.assertEqual(m["touch_basis"], "distribution")

    def test_touch_fields_are_native_types(self):
        from engine import compute_magnet_forces
        m = compute_magnet_forces(
            7592.9, self.GEX, 59.7,
            {"er_value": 0.09, "regime_state": "STATE B", "directional_bias": "LEAN BULLISH"},
            self.EM, rsi_50_spx=7588, hours_remaining=6.45, day_high=7595.4, day_low=7583.7)
        self.assertIsInstance(m["already_touched"], bool)  # native, not numpy.bool_ (pitfall #25)


class TestCardRecReconciliation(unittest.TestCase):
    """#2 (2026-06-02): a position with an open HIGH CLOSE rec must NOT render a GREEN 'hold' card
    (the live 6/2 contradiction — GREEN card vs HIGH CLOSE rec on the same position)."""

    REGIME = {"time_pressure": {"hours_remaining": 4.0}, "er_value": 0.2,
              "regime_state": "STATE B: MODERATE CHOP", "directional_bias": "NEUTRAL",
              "momentum": {"momentum_label": "RANGEBOUND"}, "rsi_14": 55.0,
              "regime_score": 2, "continuous_score": 2.1, "chop_value": 40.0, "vwap_dev": 0.05}

    def _pos(self):
        return {"id": 1, "type": "Put Spread", "strike": 7570, "moat": 46.0, "moat_pct": 57.0,
                "credit": 0.65, "estimated_buyback": 0.10, "reversal_score": 30,
                "exit_strategy": {"action": "HOLD", "escalation_level": "SAFE", "trigger_spx": 7595},
                "pricing_source": "SPXW"}

    def test_green_card_with_open_high_close_rec_becomes_yellow(self):
        from engine import generate_market_insights
        recs = [{"priority": "HIGH", "category": "CLOSE", "target_id": 1, "message": "stale day-low rec"}]
        out = generate_market_insights(self.REGIME, [self._pos()], {},
                                       expected_move_data={"conditional_1sigma": 50}, gex_data=None,
                                       spx_price=7616, day_high_spx=7620, day_low_spx=7583,
                                       recommendations=recs)
        card = out["position_cards"][0]
        self.assertNotEqual(card["light"], "GREEN")        # no GREEN-hold-while-CLOSE
        self.assertEqual(card["close_alerts"], 1)
        self.assertIsNotNone(card["close_alert_msg"])

    def test_green_card_with_no_close_rec_stays_green(self):
        from engine import generate_market_insights
        out = generate_market_insights(self.REGIME, [self._pos()], {},
                                       expected_move_data={"conditional_1sigma": 50}, gex_data=None,
                                       spx_price=7616, day_high_spx=7620, day_low_spx=7583,
                                       recommendations=[])
        card = out["position_cards"][0]
        self.assertEqual(card["light"], "GREEN")           # ~85% profit, big moat → safe
        self.assertEqual(card["close_alerts"], 0)


class TestExitConvictionDirectionAware(unittest.TestCase):
    """#3 (2026-06-02): a position below half the recommended moat should NOT get a HIGH CLOSE
    when price is trending AWAY from the strike (at_risk_side False) — the live 6/2 cry-wolf."""

    def _regime(self, bias="BULLISH"):
        return {"regime_score": 1, "effective_moat_min": 62, "directional_bias": bias,
                "momentum": {"momentum_label": "MILD DRIFT UP", "change_2h_spx_pts": 10},
                "time_pressure": {"hours_remaining": 4.0, "time_pressure_level": "LOW"},
                "er_value": 0.3, "regime_state": "STATE A: TRENDING"}

    def _put(self, at_risk):
        return {"id": 1, "type": "Put Spread", "strike": 7570, "moat": 30.0, "moat_pct": 37.0,
                "credit": 0.65, "estimated_pl": 0.2, "estimated_buyback": 0.45, "reversal_score": 20,
                "at_risk_side": at_risk, "contracts": 5,
                "exit_strategy": {"action": "HOLD_WITH_TRIGGER", "escalation_level": "SAFE"}}

    def _high_close(self, recs, pid=1):
        return [r for r in recs if r.get("target_id") == pid
                and r.get("priority") == "HIGH" and r.get("category") == "CLOSE"]

    def test_no_high_close_when_price_trending_away(self):
        from engine import generate_recommendations, clear_rec_state
        clear_rec_state()
        # price 7616 well above the 7570 put strike, day low 7600 (no near-miss), at_risk False
        recs = generate_recommendations([self._put(at_risk=False)], 7616.0, self._regime(),
                                        day_high_spx=7620.0, day_low_spx=7600.0, range_position=80.0)
        self.assertEqual(self._high_close(recs), [])

    def test_high_close_when_price_pressing_strike(self):
        from engine import generate_recommendations, clear_rec_state
        clear_rec_state()
        # price near the strike, day low 7583 (within 15 of strike), at_risk True
        recs = generate_recommendations([self._put(at_risk=True)], 7585.0, self._regime("BEARISH"),
                                        day_high_spx=7620.0, day_low_spx=7583.0, range_position=15.0)
        self.assertGreaterEqual(len(self._high_close(recs)), 1)


class TestTrendDominantHysteresis(unittest.TestCase):
    """#4 (2026-06-02): trend_dominant must not whipsaw on the ER~0.6 boundary — once ON it sticks
    (>=45 floor) until the trend truly fades; from OFF it needs the full >=55 turn-on."""

    GEX = {"gex_regime": "POSITIVE", "net_gex": 35_000_000.0, "gamma_wall_spx": 7700}
    EM = {"conditional_1sigma": 50}

    def _call(self, er, prev):
        from engine import compute_magnet_forces
        return compute_magnet_forces(
            7600.0, self.GEX, 50.0,
            {"er_value": er, "regime_state": "STATE A: TRENDING", "directional_bias": "BULLISH"},
            self.EM, rsi_50_spx=None, hours_remaining=6.5, prev_trend_dominant=prev)

    def test_from_off_stays_off_in_deadband(self):
        # er 0.3 → trend_strength ~52 (below the 55 turn-ON) → stays False when prev False
        self.assertFalse(self._call(0.3, prev=False)["trend_dominant"])

    def test_sticky_on_in_deadband(self):
        # same ~52, but already ON → stays ON (>=45 floor): no whipsaw off
        self.assertTrue(self._call(0.3, prev=True)["trend_dominant"])

    def test_clears_when_trend_fades(self):
        # er 0.2 → trend_strength ~43 (below the 45 OFF floor) → drops even if prev True
        self.assertFalse(self._call(0.2, prev=True)["trend_dominant"])


class TestProposalRRFloor(unittest.TestCase):
    """#5 (2026-06-02): a thin-credit spread can't be STRONG_ENTRY regardless of moat (6/2 $0.18)."""

    REGIME = {"time_pressure": {"hours_remaining": 5.0}, "directional_bias": "BULLISH",
              "regime_score": 1, "er_value": 0.2, "regime_state": "STATE A: TRENDING"}

    def test_thin_credit_never_strong(self):
        from engine import analyze_trade_proposal
        # huge moat, with-trend, positive GEX — would score STRONG — but $0.18 credit (~3.7% RR)
        r = analyze_trade_proposal("Put Spread", 7500, 0.18, 7616.0, self.REGIME, 40,
                                   7620.0, 7600.0, 80.0, [],
                                   gex_data={"gex_regime": "POSITIVE", "net_gex": 35e6,
                                             "put_wall_spx": 7400, "gamma_wall_spx": 7650})
        self.assertNotEqual(r["verdict"], "STRONG_ENTRY")

    def test_healthy_credit_can_be_strong(self):
        from engine import analyze_trade_proposal
        # same strong setup but a real $0.80 credit (~19% RR) is allowed to be STRONG
        r = analyze_trade_proposal("Put Spread", 7500, 0.80, 7616.0, self.REGIME, 40,
                                   7620.0, 7600.0, 80.0, [],
                                   gex_data={"gex_regime": "POSITIVE", "net_gex": 35e6,
                                             "put_wall_spx": 7400, "gamma_wall_spx": 7650})
        self.assertIn(r["verdict"], ("STRONG_ENTRY", "ACCEPTABLE"))  # not blocked by the RR floor


class TestZeroGammaFlip(unittest.TestCase):
    """#6 (2026-06-02): zero-gamma flip level interpolates where cumulative signed GEX crosses 0."""

    def test_flip_between_put_and_call_heavy(self):
        from data_fetcher import _compute_zero_gamma
        # puts (negative) below 600, calls (positive) above → cumulative crosses ~600
        flip = _compute_zero_gamma([(595, -100), (598, -60), (601, 60), (604, 120)], spot=600)
        self.assertIsNotNone(flip)
        self.assertTrue(595 <= flip <= 604)
        self.assertIsInstance(flip, float)

    def test_one_sided_returns_none(self):
        from data_fetcher import _compute_zero_gamma
        self.assertIsNone(_compute_zero_gamma([(595, 10.0), (600, 20.0)], spot=600))


class TestReportingBugFixes20260603(unittest.TestCase):
    """2026-06-03 fixes: proper net-GEX-vs-spot gamma flip (invariant spot>flip<=>net_gex>0);
    neg-GEX 'wall protecting you' false-comfort; 'all positions safe' gated on HIGH CLOSE recs;
    position-neutral regime-transition wording."""

    T = 2.0 / (252 * 6.5)  # ~2h to expiry, in years

    # --- proper gamma flip (vs-spot recompute) ---
    def test_gamma_flip_call_heavy_below_spot(self):
        from data_fetcher import _compute_gamma_flip
        # heavy call OI just above spot → net GEX > 0 at spot → flip must sit BELOW spot
        chain = [(590, 0.2, 500, -1.0), (595, 0.2, 800, -1.0),
                 (605, 0.2, 3000, 1.0), (610, 0.2, 3000, 1.0)]
        flip = _compute_gamma_flip(chain, self.T, 600.0)
        self.assertIsNotNone(flip)
        self.assertLess(flip, 600.0)   # spot > flip <=> net_gex > 0

    def test_gamma_flip_put_heavy_above_spot(self):
        from data_fetcher import _compute_gamma_flip
        # heavy put OI just below spot → net GEX < 0 at spot → flip must sit ABOVE spot
        chain = [(590, 0.2, 3000, -1.0), (595, 0.2, 3000, -1.0),
                 (605, 0.2, 800, 1.0), (610, 0.2, 500, 1.0)]
        flip = _compute_gamma_flip(chain, self.T, 600.0)
        self.assertIsNotNone(flip)
        self.assertGreater(flip, 600.0)

    def test_gamma_flip_one_sided_none(self):
        from data_fetcher import _compute_gamma_flip
        # all calls → net GEX never crosses zero in the band → no flip
        chain = [(605, 0.2, 1000, 1.0), (610, 0.2, 1000, 1.0), (615, 0.2, 1000, 1.0)]
        self.assertIsNone(_compute_gamma_flip(chain, self.T, 600.0))

    # --- neg-GEX wall must not claim "protecting you" ---
    REGIME = {"time_pressure": {"hours_remaining": 4.0}, "er_value": 0.2,
              "regime_state": "STATE B: MODERATE CHOP", "directional_bias": "NEUTRAL",
              "momentum": {"momentum_label": "RANGEBOUND"}, "rsi_14": 50.0,
              "regime_score": 2, "continuous_score": 2.1, "chop_value": 40.0, "vwap_dev": 0.05}

    def _put_pos(self):
        return {"id": 1, "type": "Put Spread", "strike": 7565, "moat": 30.0, "moat_pct": 37.0,
                "credit": 0.65, "estimated_buyback": 0.45, "reversal_score": 20,
                "exit_strategy": {"action": "HOLD", "escalation_level": "SAFE"}, "pricing_source": "SPXW"}

    def _wall_gex(self, regime):
        return {"gex_regime": regime, "net_gex": (-50e6 if regime == "NEGATIVE" else 50e6),
                "gamma_wall_spx": 7626, "put_wall_spx": 7570, "call_wall_spx": 7616, "top_levels": []}

    def test_neg_gex_wall_not_protecting(self):
        from engine import generate_market_insights
        out = generate_market_insights(self.REGIME, [self._put_pos()], {},
                                       expected_move_data={"conditional_1sigma": 50},
                                       gex_data=self._wall_gex("NEGATIVE"),
                                       spx_price=7600, day_high_spx=7620, day_low_spx=7560, recommendations=[])
        gp = out["position_cards"][0]["gex_proximity"]
        self.assertNotIn("protecting you", gp)
        self.assertIn("unreliable", gp)

    def test_pos_gex_wall_protecting(self):
        from engine import generate_market_insights
        out = generate_market_insights(self.REGIME, [self._put_pos()], {},
                                       expected_move_data={"conditional_1sigma": 50},
                                       gex_data=self._wall_gex("POSITIVE"),
                                       spx_price=7600, day_high_spx=7620, day_low_spx=7560, recommendations=[])
        gp = out["position_cards"][0]["gex_proximity"]
        self.assertIn("protecting you", gp)

    # --- 'all positions safe' must be gated on open HIGH CLOSE recs ---
    QUIET = {"time_pressure": {"hours_remaining": 3.0}, "er_value": 0.05,
             "regime_state": "STATE C: HIGH ENTROPY / WHIPSAW", "directional_bias": "NEUTRAL",
             "momentum": {"momentum_label": "RANGEBOUND"}, "rsi_14": 50.0,
             "regime_score": 3, "continuous_score": 3.0, "chop_value": 50.0, "vwap_dev": 0.05}

    def test_all_safe_suppressed_when_high_close_open(self):
        from engine import generate_market_insights
        safe_pos = {"id": 1, "type": "Put Spread", "strike": 7400, "moat": 46.0, "moat_pct": 57.0,
                    "credit": 0.65, "estimated_buyback": 0.30, "reversal_score": 20,
                    "exit_strategy": {"action": "HOLD", "escalation_level": "SAFE"}, "pricing_source": "SPXW"}
        recs = [{"priority": "HIGH", "category": "CLOSE", "target_id": 1, "message": "flagged"}]
        out = generate_market_insights(self.QUIET, [safe_pos], {},
                                       expected_move_data={"conditional_1sigma": 50}, gex_data=None,
                                       spx_price=7600, day_high_spx=7620, day_low_spx=7560, recommendations=recs)
        self.assertNotIn("All positions are safe", out["market_story"])
        self.assertNotEqual(out["market_light"], "GREEN")

    # --- regime-transition wording is position-neutral (no 'improving'/'degrading') ---
    def test_regime_transition_wording_neutral(self):
        from engine import _compute_regime_transition
        rows = [{"CHOP": 61.8, "ER": 0.05, "RSI_14": 50.0, "Close": 600.0,
                 "EMA_9": 600.0, "EMA_21": 600.0} for _ in range(7)]
        df = pd.DataFrame(rows)
        # current continuous_score far below the 30-min-ago value → score_delta < -0.5 → IMPROVING branch
        out = _compute_regime_transition(df, "CHOP", "ER", current_continuous_score=1.0)
        self.assertEqual(out["direction"], "IMPROVING")
        self.assertIn("Trend strengthening", out["label"])
        self.assertNotIn("improving", out["label"].lower())


class TestTailDayPreview(unittest.TestCase):
    """2026-06-03 sizing prominence: book-level max-loss preview ($ / % of account / green-days)."""

    def _leg(self, contracts, credit=0.5, pid=1, pr=None):
        d = {"id": pid, "type": "Put Spread", "strike": 7540.0, "credit": credit, "contracts": contracts}
        if pr is not None:
            d["position_risk"] = pr
        return d

    def test_empty_book(self):
        from engine import compute_tail_day_preview
        out = compute_tail_day_preview([])
        self.assertEqual(out["total_max_loss"], 0.0)
        self.assertEqual(out["max_lot"], 0)
        self.assertFalse(out["over_cap"])
        self.assertIn("No open positions", out["headline"])

    def test_oversized_book_math_and_flags(self):
        from engine import compute_tail_day_preview
        legs = [self._leg(10, pid=1), self._leg(10, pid=2), self._leg(10, pid=3)]
        out = compute_tail_day_preview(legs, account_size=15000.0, avg_win_day_ref=1300.0)
        # each leg: (5 - 0.5) * 10 * 100 = 4500; 3 legs = 13,500 = 90% of a $15k account
        self.assertEqual(out["total_max_loss"], 13500.0)
        self.assertEqual(out["pct_of_account"], 90.0)
        self.assertAlmostEqual(out["green_days_equivalent"], 10.4, places=1)
        self.assertTrue(out["over_warn"])
        self.assertTrue(out["over_cap"])
        self.assertEqual(out["max_lot"], 10)
        self.assertEqual(out["worst_leg"]["max_loss"], 4500.0)

    def test_prefers_position_risk_max_loss(self):
        from engine import compute_tail_day_preview
        out = compute_tail_day_preview([self._leg(5, pr={"max_loss": 999.0})], account_size=15000.0)
        self.assertEqual(out["total_max_loss"], 999.0)

    def test_native_types(self):
        from engine import compute_tail_day_preview
        out = compute_tail_day_preview([self._leg(30)])
        for k in ("total_max_loss", "pct_of_account", "green_days_equivalent"):
            self.assertIsInstance(out[k], float)
        self.assertIsInstance(out["max_lot"], int)
        self.assertIsInstance(out["over_cap"], bool)


class TestGexVelocity(unittest.TestCase):
    """2026-06-03: ΔGEX velocity + distance-to-zero gauge (the practical GEX-flip read)."""

    def _hist(self, vals, step=60.0, base=1_000_000.0):
        return [(base + i * step, v) for i, v in enumerate(vals)]

    def test_toward_positive_flip(self):
        from engine import compute_gex_velocity
        out = compute_gex_velocity(self._hist([-20e6, -15e6, -10e6, -5e6]), net_gex=-5e6)
        self.assertEqual(out["trend"], "RISING")
        self.assertTrue(out["toward_flip"])          # negative + rising → heading to a positive flip
        self.assertAlmostEqual(out["projected_min_to_flip"], 1.0, places=1)  # 5M left / 5M-per-min

    def test_deepening_negative_not_toward_flip(self):
        from engine import compute_gex_velocity
        out = compute_gex_velocity(self._hist([-20e6, -35e6, -50e6, -65e6]), net_gex=-65e6)
        self.assertEqual(out["trend"], "FALLING")
        self.assertFalse(out["toward_flip"])          # negative + falling = deepening, no flip
        self.assertIsNone(out["projected_min_to_flip"])
        self.assertIn("deepening", out["headline"])

    def test_warming_up_single_sample(self):
        from engine import compute_gex_velocity
        out = compute_gex_velocity([(1_000_000.0, -30e6)], net_gex=-30e6)
        self.assertEqual(out["samples"], 1)
        self.assertIn("warming up", out["headline"])

    def test_spot_to_flip_and_native_types(self):
        from engine import compute_gex_velocity
        out = compute_gex_velocity(self._hist([-20e6, -10e6]), net_gex=-10e6,
                                   spot=7560.0, zero_gamma_spx=7600.0)
        self.assertEqual(out["spot_to_flip"], -40.0)
        self.assertIsInstance(out["velocity_m_per_min"], float)
        self.assertIsInstance(out["samples"], int)
        self.assertIsInstance(out["toward_flip"], bool)
        self.assertIsInstance(out["headline"], str)


class TestSpxRsiAlignment(unittest.TestCase):
    """2026-06-04: SPX (^GSPC) RSI is FORWARD-FILLED onto the SPY df's bars — each bar takes the most
    recent SPX RSI at-or-before it, so the latest bar always gets the latest SPX RSI."""

    def test_ffill_maps_at_or_before(self):
        from data_fetcher import _align_rsi_to_index
        spx_idx = pd.date_range("2026-06-04 14:00", periods=10, freq="5min", tz="UTC")
        spx_rsi = pd.Series([50, 51, 52, 53, 54, 55, 56, 57, 58, 59], index=spx_idx, dtype=float)
        tgt = pd.date_range("2026-06-04 14:00:30", periods=10, freq="5min", tz="UTC")  # +30s offset
        out = _align_rsi_to_index(spx_rsi, tgt)
        self.assertIsNotNone(out)
        self.assertTrue(out.notna().all())
        self.assertEqual(out.iloc[0], 50.0)            # 14:00:30 → last SPX at-or-before = 14:00
        self.assertEqual(out.iloc[-1], 59.0)           # latest target gets the latest SPX RSI
        self.assertEqual(list(out.index), list(tgt))   # carries the SPY target index

    def test_stale_after_last_holds_last_value(self):
        from data_fetcher import _align_rsi_to_index
        spx_idx = pd.date_range("2026-06-04 14:00", periods=5, freq="5min", tz="UTC")  # ...→14:20
        spx_rsi = pd.Series([50, 51, 52, 53, 54], index=spx_idx, dtype=float)
        tgt = pd.date_range("2026-06-04 14:30", periods=2, freq="5min", tz="UTC")      # after last
        out = _align_rsi_to_index(spx_rsi, tgt)
        self.assertTrue((out == 54.0).all())           # ffill holds the latest SPX value (stale, by design)

    def test_target_before_first_is_nan(self):
        from data_fetcher import _align_rsi_to_index
        spx_idx = pd.date_range("2026-06-04 14:00", periods=5, freq="5min", tz="UTC")
        spx_rsi = pd.Series([50, 51, 52, 53, 54], index=spx_idx, dtype=float)
        tgt = pd.date_range("2026-06-04 13:00", periods=2, freq="5min", tz="UTC")      # before first
        out = _align_rsi_to_index(spx_rsi, tgt)
        self.assertTrue(out.isna().all())              # nothing at-or-before → NaN (caller keeps SPY RSI)

    def test_none_input_returns_none(self):
        from data_fetcher import _align_rsi_to_index
        tgt = pd.date_range("2026-06-04 14:00", periods=3, freq="5min", tz="UTC")
        self.assertIsNone(_align_rsi_to_index(None, tgt))


class TestRthFilter(unittest.TestCase):
    """2026-06-04: TA restricted to Regular Trading Hours so RSI/EMA/CHOP/ER track an RTH chart
    (the SPX index you trade) rather than the SPY all-session series that smears the overnight gap."""

    def _df(self):
        idx = pd.date_range("2026-06-02 08:00", "2026-06-04 19:30", freq="5min", tz="UTC")
        return pd.DataFrame({"Close": range(len(idx))}, index=idx)

    def test_keeps_only_regular_hours(self):
        from data_fetcher import _filter_to_rth
        import datetime as dt
        full = self._df()
        out = _filter_to_rth(full, min_bars=0)
        self.assertGreater(len(out), 0)
        self.assertLess(len(out), len(full))           # extended-hours bars dropped
        et = out.index.tz_convert("America/New_York")
        self.assertTrue(all(dt.time(9, 30) <= t < dt.time(16, 0) for t in et.time))

    def test_fallback_when_too_few_rth_bars(self):
        from data_fetcher import _filter_to_rth
        small = self._df().iloc[:5]                     # 5 pre-market bars only
        self.assertEqual(len(_filter_to_rth(small, min_bars=50)), 5)  # too few RTH → keep full series


class TestProposalSignalWiring(unittest.TestCase):
    """2026-06-02: wire the under-used signals into trade proposals — RSI-50 mean-reversion
    buffer/hazard, FADE-off de-rating, and gap-rejection penalty on the threatened side."""

    REGIME = {"time_pressure": {"hours_remaining": 3.0}, "directional_bias": "NEUTRAL",
              "regime_score": 1, "er_value": 0.2, "regime_state": "STATE A: TRENDING",
              "momentum": {"momentum_label": "RANGEBOUND"}, "vwap_dev": 0.05}
    GEX = {"gex_regime": "POSITIVE", "net_gex": 35e6, "put_wall_spx": 7500,
           "call_wall_spx": 7700, "gamma_wall_spx": 7650}

    def _propose(self, **over):
        from engine import auto_propose_positions
        kw = dict(spx_price=7600.0, regime_data=self.REGIME, smart_moat=25,
                  day_high_spx=7620.0, day_low_spx=7560.0, range_position=50.0,
                  existing_positions=[], gex_data=self.GEX)
        kw.update(over)
        return {p["strike"]: p for p in auto_propose_positions(**kw)}

    def test_rsi50_buffer_beats_hazard(self):
        from engine import analyze_trade_proposal
        fav = analyze_trade_proposal("Put Spread", 7560, 0.50, 7600.0, self.REGIME, 30,
                                     7620.0, 7580.0, 50.0, [], rsi_50_spx=7595)  # target above strike = buffer
        haz = analyze_trade_proposal("Put Spread", 7560, 0.50, 7600.0, self.REGIME, 30,
                                     7620.0, 7580.0, 50.0, [], rsi_50_spx=7555)  # target below strike = hazard
        self.assertGreater(fav["score"], haz["score"])

    def test_fade_off_lowers_scores(self):
        on = self._propose(mean_reversion={"on": True})
        off = self._propose(mean_reversion={"on": False})
        common = set(on) & set(off)
        self.assertTrue(common)
        for k in common:
            self.assertLess(off[k]["score"], on[k]["score"])  # FADE-off penalized

    def test_gap_rejection_penalizes_threatened_side(self):
        # BEARISH rejection → price expected to fall toward put strikes → penalize puts
        without = self._propose(gap_rejection={"rejected": False})
        withrej = self._propose(gap_rejection={"rejected": True, "direction": "BEARISH", "message": "x"})
        put_common = [k for k in (set(without) & set(withrej)) if without[k]["type"] == "Put Spread"]
        self.assertTrue(put_common)
        for k in put_common:
            self.assertLess(withrej[k]["score"], without[k]["score"])


if __name__ == '__main__':
    print("\n--- RUNNING QUANT ENGINE UNIT TESTS ---\n")
    unittest.main(verbosity=2)