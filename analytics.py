"""Strict QuantStats adapter. No downloads, imputation or alternate metric engines."""
from importlib.metadata import version
import numpy as np
import pandas as pd
import quantstats as qs

ENGINE_VERSION = '0.0.81'
if version('quantstats') != ENGINE_VERSION:
    raise RuntimeError('QuantStats version mismatch. Install requirements.txt; no alternate engine is allowed.')


def validate_returns(returns):
    if not isinstance(returns, pd.Series) or not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError('Metrics require a dated return series, not a ticker or prices.')
    if len(returns) < 2 or returns.index.has_duplicates or not returns.index.is_monotonic_increasing:
        raise ValueError('Metrics require at least two uniquely ordered observations.')
    if not np.isfinite(returns.to_numpy(dtype=float)).all() or (returns <= -1).any():
        raise ValueError('Invalid returns: no filling or clipping is allowed.')
    if returns.min() >= 0 and returns.max() > 1:
        raise ValueError('Return series is ambiguous to QuantStats price detection; calculation blocked.')
    return returns.astype(float)


def equity_returns(equity, capital):
    if not np.isfinite(capital) or capital <= 0 or equity.empty or not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError('A positive explicit initial capital and complete positive equity series are required.')
    r = equity.pct_change(fill_method=None)
    r.iloc[0] = equity.iloc[0] / capital - 1
    return validate_returns(r)


def calculate(returns, annual_rf, annual_bars):
    r = validate_returns(returns)
    if not np.isfinite(annual_rf) or annual_rf < 0 or annual_bars != int(annual_bars) or annual_bars <= 0:
        raise ValueError('Explicit nonnegative annual hurdle and positive annualization factor required.')
    n = int(annual_bars)
    values, reasons = {}, {}
    def metric(key, fn, condition=True, reason='Undefined denominator'):
        if not condition:
            values[key] = None; reasons[key] = reason; return
        value = float(fn())
        values[key] = value if np.isfinite(value) else None
        if not np.isfinite(value): reasons[key] = 'QuantStats returned a nonfinite result; no replacement used'
    metric('total_return', lambda: qs.stats.comp(r))
    metric('cagr', lambda: qs.stats.cagr(r, periods=n))
    metric('volatility', lambda: qs.stats.volatility(r, periods=n, prepare_returns=False))
    metric('max_drawdown', lambda: qs.stats.max_drawdown(r))
    metric('sharpe', lambda: qs.stats.sharpe(r, rf=annual_rf, periods=n), r.std(ddof=1) > 1e-14, 'Zero return volatility')
    hurdle = (1 + annual_rf)**(1/n)-1
    metric('sortino', lambda: qs.stats.sortino(r, rf=annual_rf, periods=n), (r < hurdle).any(), 'No returns below the daily hurdle')
    metric('calmar', lambda: qs.stats.calmar(r, periods=n, prepare_returns=False), values['max_drawdown'] < 0, 'No drawdown')
    metric('ulcer_index', lambda: qs.stats.ulcer_index(r))
    metric('var_95', lambda: qs.stats.value_at_risk(r, confidence=.95, prepare_returns=False), r.std(ddof=1) > 1e-14, 'Zero return volatility')
    # QuantStats substitutes VaR when its tail is empty. Block that branch explicitly.
    threshold = values['var_95']
    metric('cvar_95', lambda: qs.stats.conditional_value_at_risk(r, confidence=.95, prepare_returns=False), threshold is not None and (r < threshold).any(), 'No observations below the normal VaR threshold; no VaR substitution')
    values.update(metric_engine='QuantStats', metric_engine_version=ENGINE_VERSION,
                  metric_status='AVAILABLE', metric_reasons=reasons, annual_rf=float(annual_rf), annual_bars=n,
                  metric_start=str(r.index[0].date()), metric_end=str(r.index[-1].date()), metric_observations=len(r))
    return values
