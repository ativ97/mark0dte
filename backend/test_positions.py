import unittest
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import evaluate_positions
from config import (
    GAMMA_TRAP_THRESHOLD,
    WARNING_ZONE_THRESHOLD, BREACH_VERIFICATION_MINUTES,
    STATE_A_MIN_MOAT, STATE_B_MIN_MOAT, STATE_C_MIN_MOAT,
)


class MockPosition:
    """Simulates a PositionDB row without requiring a real database."""
    def __init__(self, id, type, strike, credit, breach_start_time=None):
        self.id = id
        self.type = type
        self.strike = strike
        self.credit = credit
        self.breach_start_time = breach_start_time


class TestEvaluatePositions(unittest.TestCase):

    def setUp(self):
        self.mock_db = MagicMock()

    # --- SAFE ZONE TESTS ---

    def test_put_spread_safe_zone(self):
        """Put Spread far from strike should be SAFE."""
        # SPX=5900, strike=5800 => moat=100
        pos = MockPosition(1, "Put Spread", 5800.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0, effective_moat_min=35)
        self.assertEqual(len(result), 1)
        self.assertIn("SAFE", result[0]["message"])
        self.assertEqual(result[0]["moat"], 100.0)
        self.assertIn("emerald", result[0]["status_color"])
        self.assertFalse(result[0]["at_risk_side"])

    def test_call_spread_safe_zone(self):
        """Call Spread far from strike should be SAFE."""
        # SPX=5900, strike=6000 => moat=100
        pos = MockPosition(1, "Call Spread", 6000.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0, effective_moat_min=35)
        self.assertEqual(result[0]["moat"], 100.0)
        self.assertIn("SAFE", result[0]["message"])

    # --- WARNING ZONE TESTS (regime-tiered) ---

    def test_warning_zone_state_a(self):
        """Warning zone with State A (score 0) should mention 200% premium stop."""
        # SPX=5900, strike=5880 => moat=20 (inside warning, outside gamma)
        pos = MockPosition(1, "Put Spread", 5880.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertEqual(result[0]["moat"], 20.0)
        self.assertIn("200%", result[0]["message"])
        self.assertIn("amber", result[0]["status_color"])

    def test_warning_zone_state_b(self):
        """Warning zone with State B (score 2) should mention hybrid stop."""
        pos = MockPosition(1, "Put Spread", 5880.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=2)
        self.assertIn("250%", result[0]["message"])
        self.assertIn("15-pt", result[0]["message"])

    def test_warning_zone_state_c(self):
        """Warning zone with State C (score 3) should mention asset-boundary only."""
        pos = MockPosition(1, "Put Spread", 5880.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=3)
        self.assertIn("Asset-boundary", result[0]["message"])
        self.assertIn("ignore premium", result[0]["message"].lower())

    # --- GAMMA TRAP TESTS ---

    def test_gamma_trap_starts_timer(self):
        """Moat <= 10 should start breach verification timer."""
        # SPX=5900, strike=5895 => moat=5
        pos = MockPosition(1, "Put Spread", 5895.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertEqual(result[0]["moat"], 5.0)
        self.assertIn("Gamma Trap", result[0]["message"])
        self.assertIn("amber", result[0]["bar_color"])
        # Timer should have been set
        self.assertIsNotNone(pos.breach_start_time)
        self.mock_db.commit.assert_called()

    def test_gamma_trap_verified_eject(self):
        """If breach timer has expired, should issue CRITICAL EJECT."""
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=BREACH_VERIFICATION_MINUTES + 1)
        pos = MockPosition(1, "Put Spread", 5895.0, 0.80, breach_start_time=expired_time)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertIn("CRITICAL EJECT", result[0]["message"])
        self.assertIn("red", result[0]["bar_color"])

    def test_gamma_trap_waiting_countdown(self):
        """If breach timer is running but not expired, show countdown."""
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        pos = MockPosition(1, "Put Spread", 5895.0, 0.80, breach_start_time=recent_time)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertIn("Gamma Trap", result[0]["message"])
        self.assertIn("Verification", result[0]["message"])
        self.assertIn("amber", result[0]["bar_color"])

    # --- WHIPSAW IMMUNITY ---

    def test_whipsaw_immunity_clears_timer(self):
        """If price recovers out of gamma trap, breach timer should be cleared."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=3)
        pos = MockPosition(1, "Put Spread", 5800.0, 0.80, breach_start_time=old_time)
        # SPX=5900, strike=5800 => moat=100 (well outside gamma trap)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertIsNone(pos.breach_start_time)
        self.assertIn("SAFE", result[0]["message"])
        self.mock_db.commit.assert_called()

    # --- EDGE CASES ---

    def test_moat_exactly_at_gamma_boundary(self):
        """Moat exactly at 10 points should trigger gamma trap."""
        # SPX=5900, strike=5890 => moat=10
        pos = MockPosition(1, "Put Spread", 5890.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertIn("Gamma Trap", result[0]["message"])

    def test_moat_exactly_at_warning_boundary(self):
        """Moat exactly at 25 points should trigger warning zone."""
        # SPX=5900, strike=5875 => moat=25
        pos = MockPosition(1, "Put Spread", 5875.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertIn("WARNING", result[0]["message"])

    def test_negative_moat_breached_strike(self):
        """Price through the strike should still trigger gamma trap (moat < 0)."""
        # SPX=5900, strike=5910 => moat=-10
        pos = MockPosition(1, "Put Spread", 5910.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0)
        self.assertIn("Gamma Trap", result[0]["message"])
        self.assertTrue(result[0]["moat"] < 0)

    def test_moat_pct_clamped_to_0_100(self):
        """moat_pct should never exceed 100 or go below 0."""
        pos_far = MockPosition(1, "Put Spread", 5000.0, 0.80)
        pos_breached = MockPosition(2, "Put Spread", 6000.0, 0.80)
        result = evaluate_positions([pos_far, pos_breached], 5900.0, self.mock_db, regime_score=0)
        self.assertLessEqual(result[0]["moat_pct"], 100)
        self.assertGreaterEqual(result[1]["moat_pct"], 0)

    def test_empty_positions_list(self):
        """No positions should return empty list without errors."""
        result = evaluate_positions([], 5900.0, self.mock_db, regime_score=2)
        self.assertEqual(result, [])

    def test_multiple_positions_evaluated_independently(self):
        """Each position should get its own moat/status independently."""
        pos1 = MockPosition(1, "Put Spread", 5800.0, 0.80)  # moat=100, safe
        pos2 = MockPosition(2, "Put Spread", 5895.0, 0.50)  # moat=5, gamma trap
        result = evaluate_positions([pos1, pos2], 5900.0, self.mock_db, regime_score=0, effective_moat_min=35)
        self.assertIn("SAFE", result[0]["message"])
        self.assertIn("Gamma Trap", result[1]["message"])

    # --- CAUTION ZONE TESTS ---

    def test_caution_zone_below_recommended_moat(self):
        """Moat above warning (25) but below recommended min (35) should show CAUTION."""
        # SPX=5900, strike=5870 => moat=30 (above 25, below 35)
        pos = MockPosition(1, "Put Spread", 5870.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0, effective_moat_min=35)
        self.assertIn("CAUTION", result[0]["message"])
        self.assertIn("below recommended", result[0]["message"])
        self.assertIn("amber", result[0]["bar_color"])

    def test_caution_zone_state_b_wider(self):
        """State B requires 50-pt moat; a 40-pt moat should be CAUTION."""
        # SPX=5900, strike=5860 => moat=40
        pos = MockPosition(1, "Put Spread", 5860.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=2, effective_moat_min=50)
        self.assertIn("CAUTION", result[0]["message"])

    def test_caution_zone_exactly_at_recommended(self):
        """Moat exactly at recommended min should be SAFE, not CAUTION."""
        # SPX=5900, strike=5865 => moat=35 (exactly at State A min)
        pos = MockPosition(1, "Put Spread", 5865.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0, effective_moat_min=35)
        self.assertIn("SAFE", result[0]["message"])

    # --- DIRECTIONAL RISK TESTS ---

    def test_put_spread_at_risk_in_bearish_bias(self):
        """Put Spread should be flagged as at-risk when bias is LEAN BEARISH."""
        pos = MockPosition(1, "Put Spread", 5870.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="LEAN BEARISH")
        self.assertTrue(result[0]["at_risk_side"])
        self.assertIn("CAUTION", result[0]["message"])
        self.assertIn("LEAN BEARISH", result[0]["message"])
        self.assertIn("higher risk", result[0]["message"])

    def test_call_spread_not_at_risk_in_bearish_bias(self):
        """Call Spread should NOT be at-risk when bias is bearish."""
        pos = MockPosition(1, "Call Spread", 5930.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="LEAN BEARISH")
        self.assertFalse(result[0]["at_risk_side"])

    def test_safe_zone_with_directional_note(self):
        """Safe position on at-risk side should show monitor note."""
        # SPX=5900, strike=5800 => moat=100 (well safe)
        pos = MockPosition(1, "Put Spread", 5800.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="BEARISH")
        self.assertIn("SAFE", result[0]["message"])
        self.assertIn("monitor", result[0]["message"].lower())
        self.assertTrue(result[0]["at_risk_side"])

    def test_neutral_bias_no_risk_flag(self):
        """NEUTRAL bias should not flag any side as at-risk."""
        pos = MockPosition(1, "Put Spread", 5870.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="NEUTRAL")
        self.assertFalse(result[0]["at_risk_side"])

    # --- RANGE PROXIMITY TESTS ---

    def test_put_spread_near_day_low(self):
        """Put Spread should flag range risk when SPX is near day's low."""
        # SPX=5900, strike=5800 => moat=100 (safe), but range_position=10% (near day low)
        pos = MockPosition(1, "Put Spread", 5800.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="NEUTRAL",
                                    range_position=10.0)
        self.assertTrue(result[0]["at_risk_side"])
        self.assertIn("near day low", result[0]["message"].lower())

    def test_call_spread_near_day_high(self):
        """Call Spread should flag range risk when SPX is near day's high."""
        pos = MockPosition(1, "Call Spread", 6000.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="NEUTRAL",
                                    range_position=90.0)
        self.assertTrue(result[0]["at_risk_side"])
        self.assertIn("near day high", result[0]["message"].lower())

    def test_put_spread_no_range_risk_at_day_high(self):
        """Put Spread should NOT flag range risk when SPX is near day's high."""
        pos = MockPosition(1, "Put Spread", 5800.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="NEUTRAL",
                                    range_position=90.0)
        self.assertFalse(result[0]["at_risk_side"])
        self.assertIn("SAFE", result[0]["message"])

    def test_range_risk_escalates_caution_message(self):
        """CAUTION zone + range risk should mention pressing toward strike."""
        # SPX=5900, strike=5870 => moat=30 (caution), range_position=15 (near low)
        pos = MockPosition(1, "Put Spread", 5870.0, 0.80)
        result = evaluate_positions([pos], 5900.0, self.mock_db, regime_score=0,
                                    effective_moat_min=35, directional_bias="NEUTRAL",
                                    range_position=15.0)
        self.assertIn("CAUTION", result[0]["message"])
        self.assertIn("pressing toward strike", result[0]["message"])


if __name__ == '__main__':
    print("\n--- RUNNING POSITION EVALUATOR UNIT TESTS ---\n")
    unittest.main(verbosity=2)
