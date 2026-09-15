"""EODHD Commodities API adapter v4: daily source observations, never fabricated OHLC.
Source: https://eodhd.com/financial-apis/commodities-api
"""
import html
import numpy as np
import pandas as pd

# Explicit reference identities; these are not exchange-traded futures contracts.
YAHOO_DAILY={
 'Gasoline':'RB=F','Copper':'HG=F','Corn':'ZC=F','Wheat':'ZW=F',
 'Coffee':'KC=F','Sugar':'SB=F','Cotton':'CT=F',
}

def _yahoo_daily_payload(symbol,start):
    """Yahoo Finance v8 chart API, interval=1d. Standard library only; no new dependency."""
    import json, urllib.request, urllib.parse
    p1=int(pd.Timestamp(start).timestamp()); p2=int(pd.Timestamp.now(tz='UTC').timestamp())
    url=('https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')
         +f'?interval=1d&period1={p1}&period2={p2}&events=history')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=30) as resp:
        payload=json.loads(resp.read().decode())
    chart=payload.get('chart',{}); result=chart.get('result') or []
    if not result: raise ValueError('YAHOO_UNAVAILABLE: '+str(chart.get('error')))
    r0=result[0]; ts=r0.get('timestamp') or []
    closes=(r0.get('indicators',{}).get('quote',[{}])[0]).get('close') or []
    meta=r0.get('meta',{})
    data=[{'date':pd.Timestamp(t,unit='s').strftime('%Y-%m-%d'),'value':float(v)}
          for t,v in zip(ts,closes) if v is not None]
    if not data: raise ValueError('YAHOO_NO_DAILY_DATA: '+symbol)
    return {'meta':{'interval':'daily','name':meta.get('longName') or symbol,
                    'unit':meta.get('currency') or 'USD'},'data':data}


SPECS = {
 'WTI Crude Oil':('WTI','daily',14),
 'Brent Crude Oil':('BRENT','daily',14),
 'Natural Gas':('NATURAL_GAS','daily',14),
 'Heating Oil':('HEATING_OIL_NYH','daily',14),
 'Gasoline':('GASOLINE_US','weekly',21),
 'Copper':('COPPER','monthly',90),
 'Corn':('CORN','monthly',90),
 'Wheat':('WHEAT','monthly',90),
 'Coffee':('COFFEE_MILD_ARABICA','monthly',90),
 'Sugar':('SUGAR','monthly',90),
 'Cotton':('COTTON','monthly',90),
}

def parse_observations(payload, interval, start):
    if not isinstance(payload,dict) or not isinstance(payload.get('meta'),dict) or not isinstance(payload.get('data'),list):
        raise ValueError('COMMODITY_SCHEMA_ERROR: expected meta + data')
    meta=payload['meta']
    if meta.get('interval')!=interval:
        raise ValueError('COMMODITY_FREQUENCY_MISMATCH')
    if interval!='daily':
        raise ValueError('DAILY_SOURCE_REQUIRED: provider interval is '+str(interval))
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
    if not gaps.empty and gaps.median()>3:
        raise ValueError('DAILY_SOURCE_REQUIRED: observed date spacing is not daily')
    return d,meta,missing

def commodity_view(asset,cfg,token,api):
    if asset['name'] not in SPECS:
        raise ValueError('UNAVAILABLE: not in documented Commodities API list; no substitute used')
    code,interval,max_age=SPECS[asset['name']]
    if interval!='daily':
        ysym=YAHOO_DAILY.get(asset['name'])
        if not ysym: raise ValueError(f'DAILY_SOURCE_REQUIRED: {asset["name"]} has no daily source mapping')
        payload=_yahoo_daily_payload(ysym,cfg['start']); interval='daily'; max_age=14; data_source='Yahoo Finance daily'
    else:
        payload=api('commodities/historical/'+code,token,{'interval':interval},object_response=True); data_source='EODHD Commodities'
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
        provider_name=data_source+': '+meta['name'],instrument_type='Economic commodity reference series',
        interval=interval,unit=meta['unit'],last_date=str(d.index[-1].date()),age_days=age,
        first_date=str(d.index[0].date()),observations=len(d),missing_values=missing,
        latest=float(d.value.iloc[-1]),bb_state=label,bb_periods=n,
        backtest_eligible=False,vwap_eligible=False,total_return=None,
        reason='Daily date/value only; no OHLCV. Source: '+data_source+'.')
    import plotly.graph_objects as go
    f=go.Figure()
    for name,values in [('Observed price',d.value),('BB basis',basis),('Upper',basis+sd),('Lower',basis-sd)]:
        f.add_trace(go.Scatter(x=d.index,y=values,name=name))
    f.update_layout(template='plotly_dark',height=650,title=meta['name'],yaxis_title=meta['unit'])
    body='<a href="index.html">Back</a><p>PRICE ONLY · daily observations · '+str(n)+'-observation Bollinger bands.</p>'
    body+='<p>No OHLCV: ATR, stop/target backtest and VWAP are disabled. Observation dates are not historical availability timestamps; no backtest is inferred from these revised reference data.</p>'
    body+=f.to_html(full_html=False,include_plotlyjs=True)+pd.DataFrame([out]).to_html(index=False,escape=True)
    return out,body
