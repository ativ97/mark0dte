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


if __name__ == '__main__':
    print("\n--- RUNNING QUANT ENGINE UNIT TESTS ---\n")
    unittest.main(verbosity=2)