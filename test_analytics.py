"""Strict metric-engine tests. Synthetic fixtures are unit inputs, never market-data fallback."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import quantstats as qs

from analytics import calculate, equity_returns, ENGINE_VERSION


class AnalyticsTests(unittest.TestCase):
    def dated(self, values):
        return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="B"))

    def test_quantstats_version_is_pinned(self):
        self.assertEqual(ENGINE_VERSION, "0.0.81")

    def test_calculate_uses_quantstats_for_core_metrics(self):
        returns = self.dated([0.01, -0.02, 0.015, 0.004, -0.003, 0.006])
        out = calculate(returns, 0.03, 252)
        self.assertEqual(out["metric_engine"], "QuantStats")
        self.assertEqual(out["metric_status"], "AVAILABLE")
        self.assertAlmostEqual(out["total_return"], qs.stats.comp(returns))
        self.assertAlmostEqual(out["max_drawdown"], qs.stats.max_drawdown(returns))
        self.assertEqual(out["metric_observations"], len(returns))

    def test_equity_returns_includes_first_day_pnl(self):
        equity = self.dated([99000.0, 100980.0, 99970.2])
        out = equity_returns(equity, 100000.0)
        self.assertAlmostEqual(out.iloc[0], -0.01)
        self.assertAlmostEqual(out.iloc[1], 0.02)
        self.assertAlmostEqual(out.iloc[2], -0.01)

    def test_invalid_returns_abort_without_fill_or_clip(self):
        returns = self.dated([0.01, np.nan, 0.02])
        with self.assertRaisesRegex(ValueError, "no filling"):
            calculate(returns, 0.03, 252)

    def test_constant_returns_do_not_invent_denominator(self):
        returns = self.dated([0.001, 0.001, 0.001, 0.001])
        out = calculate(returns, 0.0, 252)
        self.assertIsNone(out["sharpe"])
        self.assertIsNone(out["var_95"])
        self.assertIn("sharpe", out["metric_reasons"])
        self.assertIn("var_95", out["metric_reasons"])

    def test_cvar_var_substitution_branch_is_blocked(self):
        returns = self.dated([0.001, 0.002, 0.003, 0.004, 0.005])
        out = calculate(returns, 0.0, 252)
        self.assertIsNone(out["cvar_95"])
        self.assertIn("No observations below", out["metric_reasons"]["cvar_95"])

    def test_no_download_path_is_called(self):
        returns = self.dated([0.01, -0.01, 0.02, -0.005])
        with patch("quantstats.utils.download_returns", side_effect=AssertionError("network path")):
            out = calculate(returns, 0.0, 252)
        self.assertEqual(out["metric_engine"], "QuantStats")


if __name__ == "__main__":
    unittest.main()
