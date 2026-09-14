# Global Bollinger — EODHD Python / Colab / Netlify (v4.0)

Tabbed Plotly research portal over EODHD end-of-day data: 30 global equity indices,
4 precious metals and 11 economic commodity reference series.

## Tabs
- **Executive** — daily command view: coverage KPIs, validation health, median OOS
  performance across the 30 equity indices, regional coverage chart, strategy ranking.
- **Investment Universe** — full registry with Region and Instrument Group combo-box
  filters and live counters.
- **Index Lab** — per-instrument deep dive: price with Bollinger bands, trade markers,
  OOS simulated equity vs buy & hold, drawdown.
- **Commodities** — native date/value observations (no OHLCV; no backtest).
- **Risk & Performance** — QuantStats ratios per instrument (Sharpe, Sortino, Calmar,
  Omega, VaR/CVaR, skew, kurtosis, tail ratio, ulcer index, max drawdown, CAGR),
  PyPortfolioOpt portfolio research on exact common observation dates (max Sharpe,
  min volatility, HRP weights), EGARCH conditional volatility via `arch`.
- **Trade Log** — full OOS trade journal with CSV export.
- **Data Audit** — validation outcomes with exact rejection reasons.

## Metric stack
- `quantstats` — all per-instrument performance/risk ratios.
- `PyPortfolioOpt` — portfolio-level weights and risk (common exact dates, never filled).
- `arch` — EGARCH conditional volatility.

## Policy: no fallback, no synthetic data
- Missing `quantstats`/`PyPortfolioOpt` aborts the build with an explicit error.
- No proxy, synthetic or filled market data anywhere in the production path.
- Synthetic fixtures exist only in `test_engine.py`, isolated from all outputs.
- A failed build never replaces the previous deployment.

## Setup
1. Extract this package to the root of a private GitHub repository (keep existing
   `config.json` and `universe.json`). Include `.github/workflows/daily.yml`.
2. Define `EODHD_API_TOKEN` (GitHub Actions secret / Colab secret).
3. `pip install -r requirements.txt`, then `python -m unittest -v test_engine`.
4. `python bb_eodhd.py` builds `netlify_site.zip`; `python bb_eodhd.py --deploy` publishes
   (requires `PUBLISH_APPROVED=true`, `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`).

## Colab
Upload this ZIP, set `EODHD_API_TOKEN` in Colab Secrets, run the cells in order.
The notebook does not publish by itself; it builds the validated site package.

## Automation
The daily workflow runs tests, rebuilds and (when approved) deploys. Reference-series
simulations only; indices are not directly tradable. FX conversion, short borrow and
futures roll costs are not modeled.
