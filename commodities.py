"""EODHD Commodities API adapter v2.1: native observations, never fabricated OHLC.
Source: https://eodhd.com/financial-apis/commodities-api
"""
import html
import numpy as np
import pandas as pd

# Explicit reference identities; these are not exchange-traded futures contracts.
SPECS = {
 'WTI Crude Oil':('WTI','daily',14),
 'Brent Crude Oil':('BRENT','daily',14),
 'Natural Gas':('NATURAL_GAS','daily',14),
 'Heating Oil':('HEATING_OIL_NYH','daily',14),
 'Gasoline':('GASOLINE_US','daily',14),
 'Copper':('COPPER','daily',14),
 'Corn':('CORN','daily',14),
 'Wheat':('WHEAT','daily',14),
 'Coffee':('COFFEE_MILD_ARABICA','daily',14),
 'Sugar':('SUGAR','daily',14),
 'Cotton':('COTTON','daily',14),
}

def parse_observations(payload, interval, start):
    if not isinstance(payload,dict) or not isinstance(payload.get('meta'),dict) or not isinstance(payload.get('data'),list):
        raise ValueError('COMMODITY_SCHEMA_ERROR: expected meta + data')
    meta=payload['meta']
    if meta.get('interval')!=interval:
        raise ValueError('COMMODITY_FREQUENCY_MISMATCH')
    if not meta.get('name') or not meta.get('unit'):
        raise ValueError('COMMODITY_METADATA_MISSING')
    d=pd.DataFrame(payload['data'])
    if not {'date','value'}.issubset(d.columns): raise ValueError('COMMODITY_EMPTY_OR_INVALID')
    d['date']=pd.to_datetime(d.date,errors='coerce')
    if d.date.isna().any() or d.date.duplicated().any(): raise ValueError('COMMODITY_INVALID_DATES')
    d['value']=pd.to_numeric(d.value,errors='coerce')
    # Missing provider observations are removed and counted, never filled.
    missing=int(d.value.isna().sum()); d=d.dropna(subset=['value'])
    if not np.isfinite(d.value).all(): raise ValueError('COMMODITY_NONFINITE_VALUES')
    end=pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()-pd.Timedelta(days=1)
    d=d.set_index('date').sort_index().loc[pd.Timestamp(start):end,['value']]
    if d.empty: raise ValueError('COMMODITY_NO_OBSERVATIONS_IN_RANGE')
    gaps=d.index.to_series().diff().dt.days.dropna()
    if len(gaps) and (float(gaps.median())>4 or int(gaps.max())>14):
        raise ValueError(f'COMMODITY_NOT_DAILY: median gap {gaps.median():.0f}d, max {gaps.max():.0f}d. Daily frequency is mandatory; the series is rejected, never resampled or substituted')
    return d,meta,missing

def commodity_view(asset,cfg,token,api):
    if asset['name'] not in SPECS:
        raise ValueError('UNAVAILABLE: not in documented Commodities API list; no substitute used')
    code,interval,max_age=SPECS[asset['name']]
    payload=api('commodities/historical/'+code,token,{'interval':interval},object_response=True)
    d,meta,missing=parse_observations(payload,interval,cfg['start'])
    age=int((pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()-d.index[-1]).days)
    if age>max_age: raise ValueError('STALE_COMMODITY: exceeds '+str(max_age)+' calendar days for '+interval)
    # Negative prices are valid provider observations (e.g. historical WTI).
    # No log returns, ATR, intraday stop tests or artificial OHLC here.
    n=cfg['bb_length']; basis=d.value.rolling(n).mean(); sd=d.value.rolling(n).std(ddof=0)*cfg['bb_std']
    label='INSUFFICIENT_BB_HISTORY'
    if pd.notna(basis.iloc[-1]):
        label='ABOVE_UPPER' if d.value.iloc[-1]>basis.iloc[-1]+sd.iloc[-1] else 'BELOW_LOWER' if d.value.iloc[-1]<basis.iloc[-1]-sd.iloc[-1] else 'INSIDE_BANDS'
    out=dict(status='PRICE_ONLY',symbol='commodities/historical/'+code,
        provider_name=meta['name'],instrument_type='Economic commodity reference series',
        interval=interval,unit=meta['unit'],last_date=str(d.index[-1].date()),age_days=age,
        first_date=str(d.index[0].date()),observations=len(d),missing_values=missing,
        latest=float(d.value.iloc[-1]),bb_state=label,bb_periods=n,
        backtest_eligible=False,vwap_eligible=False,total_return=None,
        reason='Date/value only; no OHLCV. Data obtained via EODHD; upstream FRED/EIA/IMF.')
    import plotly.graph_objects as go
    f=go.Figure()
    for name,values in [('Observed price',d.value),('BB basis',basis),('Upper',basis+sd),('Lower',basis-sd)]:
        f.add_trace(go.Scatter(x=d.index,y=values,name=name))
    f.update_layout(template='plotly_dark',height=650,title=meta['name'],yaxis_title=meta['unit'])
    body='<a href="index.html">Back</a><p>PRICE ONLY · '+html.escape(interval)+' observations · '+str(n)+'-observation Bollinger bands.</p>'
    body+='<p>No OHLCV: ATR, stop/target backtest and VWAP are disabled. Observation dates are not historical availability timestamps; no backtest is inferred from these revised reference data.</p>'
    body+=f.to_html(full_html=False,include_plotlyjs=True)+pd.DataFrame([out]).to_html(index=False,escape=True)
    return out,body
