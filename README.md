# Global Bollinger EODHD Analytics

Institutional research portal for a fixed investment universe of 30 global major equity indices plus commodities and precious metals. Market data is sourced from EODHD daily observations only. The generated Netlify package is a static site with Plotly charts and precomputed Python analytics.

## What the portal provides

- Executive decision workspace with global filters for region, instrument group and comparison period.
- Investment Universe table showing every registered instrument, including accepted OHLC series, price-only commodity references and rejected data.
- Interactive Index Lab with OHLC candles, Bollinger bands, OOS equity, drawdown and trade markers.
- Performance and risk tabs using QuantStats 0.0.81 on validated net OOS strategy returns.
- Data Audit tab showing rejected or unavailable instruments without replacement data.

## Strict data policy

- EODHD is the only market-data provider.
- Daily observations are required for every published chart and calculation.
- No fallback provider is used.
- No proxy symbols are substituted.
- No synthetic market data is created.
- Missing prices, OHLC and volume are not fabricated, interpolated or filled.
- Weekly or monthly commodity references are rejected rather than resampled.
- Cached EODHD observations may preserve previously fetched provider data, but a failed or empty update cannot replace the requested run.

## Package responsibilities

- `quantstats==0.0.81`: sole return-based performance and risk metric engine.
- `plotly`: interactive chart rendering.
- `arch`: EGARCH diagnostic estimates for underlying reference prices.
- `PyPortfolioOpt`: not published in this release because no approved portfolio weights, mandate, benchmark, common base currency or implementation vehicle has been defined.
- `pyfolio`: not used as a second metric engine or fallback.

## Required secrets

Set these in GitHub Actions Secrets:

- `EODHD_API_TOKEN`
- `NETLIFY_AUTH_TOKEN`
- `NETLIFY_SITE_ID`

Set this in GitHub Actions Variables only after checking site access and license constraints:

- `PUBLISH_APPROVED=true`

Colab has its own Secrets panel. GitHub Secrets are not visible to Colab.

## Local or Colab run

```bash
pip install -r requirements.txt
python -m unittest discover -v
python bb_eodhd.py --init
python bb_eodhd.py
```

The build creates `netlify_site.zip`. Upload that ZIP to Netlify manually, or let GitHub Actions deploy it when the Netlify secrets and `PUBLISH_APPROVED` variable are configured.

## GitHub repository contents

Upload the full source package to the repository root. The repository should include `index.html` only after Netlify builds a site package; the source repository itself is driven by:

- `bb_eodhd.py`
- `analytics.py`
- `report_ui.py`
- `portal.html`
- `portal.css`
- `portal.js`
- `commodities.py`
- `netlify_setup.py`
- `config.json`
- `universe.json`
- `requirements.txt`
- `test_engine.py`
- `test_analytics.py`
- `Colab_Run.ipynb`
- `.github/workflows/daily.yml`

The recommended repository name remains `global-bollinger-eodhd`.
