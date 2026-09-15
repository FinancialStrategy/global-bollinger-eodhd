"""EODHD Bollinger research pipeline. Python 3.11+. No brokerage execution."""
from __future__ import annotations
import argparse, html, json, os, re, time, zipfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError
import numpy as np
import pandas as pd
from commodities import commodity_view

try:
    import quantstats as qs
except ImportError as exc:
    raise ImportError('quantstats is a required dependency (pip install quantstats). '
                      'Project policy: no fallback metrics engine exists.') from exc
try:
    from pypfopt import risk_models, expected_returns
    from pypfopt.efficient_frontier import EfficientFrontier
    from pypfopt.hierarchical_portfolio import HRPOpt
except ImportError as exc:
    raise ImportError('PyPortfolioOpt is a required dependency (pip install PyPortfolioOpt). '
                      'Project policy: no fallback portfolio-risk engine exists.') from exc
import inspect, warnings

EWMA_LAMBDA=0.94  # RiskMetrics decay factor for EWMA variance

def _finite(x):
    try: x = float(x)
    except (TypeError, ValueError): return None
    return x if np.isfinite(x) else None

def _qcall(fn, *args, **kwargs):
    # Pass only kwargs the installed version accepts; guards against minor API drift.
    params = inspect.signature(fn).parameters
    if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return fn(*args, **kwargs)

ROOT = Path(__file__).resolve().parent
VERSION = '4.1'
# Reviewed against user's 2026-09-14 catalog (SHA256 dfb1d249...b1).
# Explicit user mappings still take precedence. Catalog metadata is rechecked each run.
REVIEWED_INDICES = {
 'S&P/TSX Composite': ('GSPTSE.INDX','S&P TSX Composite Index (Canada)','CAD',None),
 'Bovespa': ('BVSP.INDX','BOVESPA Index','BRL',None),
 'S&P IPSA': ('SPIPSA.INDX','S&P CLX IPSA','CLP',None),
 'EURO STOXX 50': ('STOXX50E.INDX','Euro Stoxx 50','EUR','EU0009658145'),
 'AEX': ('AEX.INDX','AEX Amsterdam Index','EUR',None),
 'IBEX 35': ('IBEX.INDX','IBEX 35 Index','EUR',None),
 'Hang Seng': ('HSI.INDX','Hang Seng (Hong Kong)','HKD',None),
 'CSI 300': ('CSI300.INDX','Shanghai Shenzhen CSI 300','CNY',None),
}
DEFAULT = dict(start='2018-01-01', capital=100000., risk=.01, exposure=1.,
               commission=.0005, slippage=.0005, annual_rf=.03, annual_bars=252,
               bb_length=55, bb_std=1., atr_length=14, stop_atr=2., target_r=2.,
               trail_atr=2.5, trend_length=200, trend_filter=True, rsi_filter=False,
               adx_filter=False, adx_min=20., volume_filter=False, mode='Both',
               train_ratio=.7, optimize=False, max_age_days=7, min_rows=400)

# Exact provider-name aliases, not fuzzy search or invented ticker mappings.
GROUPS = {
 'North America': ['S&P 500|S&P 500 Index','NASDAQ 100|NASDAQ 100 Index',
  'Dow Jones Industrial Average','NASDAQ Composite','S&P/TSX Composite', 'S&P/BMV IPC|IPC Mexico'],
 'Latin America': ['Bovespa|IBOVESPA','S&P MERVAL|MERVAL','S&P IPSA|IPSA','MSCI COLCAP|COLCAP'],
 'Europe': ['EURO STOXX 50','DAX|DAX Index','CAC 40','AEX|AEX Index','Swiss Market Index|SMI',
  'IBEX 35','FTSE MIB','OMX Stockholm 30|OMXS30','BIST 100|BIST 100 Index'],
 'Asia-Pacific': ['Nikkei 225','TOPIX','Hang Seng|Hang Seng Index','CSI 300','Shanghai Composite',
  'Taiwan Weighted|Taiwan Weighted Index','KOSPI|KOSPI Composite Index','S&P/ASX 200','Nifty 50|NIFTY 50'],
 'Middle East & Africa': ['Tadawul All Share|TASI','FTSE/JSE Top 40|JSE Top 40'],
 'Precious Metals': ['Gold','Silver','Platinum','Palladium'],
 'Commodities': ['Copper','WTI Crude Oil','Brent Crude Oil','Natural Gas','Heating Oil',
  'Gasoline','Corn','Wheat','Soybeans','Coffee','Cocoa','Sugar','Cotton']}

def universe():
    rows=[]
    for region, names in GROUPS.items():
        for name in names:
            rows.append(dict(id=f'A{len(rows)+1:02}', name=name.split('|')[0], aliases=name.split('|'),
                region=region, asset_class=region if region in ['Commodities','Precious Metals'] else 'Equity Index',
                provider_symbol='', provider_name='', instrument_type='', volume_verified=False))
    return rows

def write_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def initialize():
    for name, obj in [('config.json',DEFAULT),('universe.json',universe())]:
        if not (ROOT/name).exists(): write_json(ROOT/name,obj)

class DataError(Exception): pass

def api(path, token, params=None, object_response=False):
    url='https://eodhd.com/api/'+path+'?'+urlencode(dict(api_token=token,fmt='json',**(params or {})))
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={'User-Agent':'MK-BB-Research/2'}),timeout=30) as response:
                obj=json.load(response)
            if not isinstance(obj,dict if object_response else list): raise DataError('Unexpected provider payload')
            return obj
        except HTTPError as exc:
            if exc.code in (401,403): raise DataError(f'HTTP {exc.code}: access denied') from None
            if exc.code not in (429,500,502,503,504): raise DataError(f'HTTP {exc.code}') from None
        except (URLError,TimeoutError,ValueError): pass
        time.sleep(2**attempt)
    raise DataError('Provider unavailable after retries')

def catalog(token):
    records=[]
    for exchange in ('INDX','FOREX'):
        try:
            for row in api('exchange-symbol-list/'+exchange,token):
                row=dict(row); row['provider_symbol']=str(row.get('Code',''))+'.'+exchange
                records.append(row)
        except DataError as exc:
            print(exchange, str(exc))
            if 'HTTP 401' in str(exc): raise
    write_json(ROOT/'private/catalog.json',records)
    return records

def resolve(asset, records):
    norm=lambda s: ' '.join(str(s).casefold().split())
    if not asset['provider_symbol'] and asset['name'] in REVIEWED_INDICES:
        symbol,name,currency,isin=REVIEWED_INDICES[asset['name']]
        hits=[r for r in records if r.get('provider_symbol')==symbol]
        if len(hits)!=1: raise DataError('REVIEWED_MAPPING_MISSING: '+symbol)
        r=hits[0]
        if (r.get('Name')!=name or r.get('Currency')!=currency or r.get('Type')!='INDEX'
                or (isin and r.get('Isin')!=isin)):
            raise DataError('REVIEWED_MAPPING_METADATA_CHANGED: '+symbol)
        return dict(r,instrument_type='Equity index reference series')
    # ISO metal/USD identity must actually exist in the current FOREX catalog.
    metal_codes={'Gold':'XAUUSD','Silver':'XAGUSD','Platinum':'XPTUSD','Palladium':'XPDUSD'}
    if asset['asset_class']=='Precious Metals' and not asset['provider_symbol']:
        code=metal_codes.get(asset['name'])
        hits=[r for r in records if r['provider_symbol']==str(code)+'.FOREX']
        if len(hits)!=1: raise DataError('UNRESOLVED: USD spot-metal pair absent or ambiguous in FOREX catalog')
        return dict(hits[0],instrument_type='Spot metal quoted in USD')
    if asset['provider_symbol']:
        hits=[r for r in records if r['provider_symbol']==asset['provider_symbol']]
        if not asset['provider_name'] or not asset['instrument_type']:
            raise DataError('Explicit mapping needs provider_name and instrument_type')
        hits=[r for r in hits if norm(r.get('Name'))==norm(asset['provider_name'])]
    else:
        names={norm(n) for n in asset['aliases']}
        hits=[r for r in records if norm(r.get('Name')) in names]
        # No automatic spot/futures choice for commodities or metals.
        if asset['asset_class']!='Equity Index':
            raise DataError('UNRESOLVED: confirm spot/futures identity using private/catalog.json')
        hits=[r for r in hits if r['provider_symbol'].endswith('.INDX')]
    if len(hits)!=1: raise DataError(f'UNRESOLVED: {len(hits)} exact catalog matches')
    return hits[0]

def validate(df, cfg):
    required=['open','high','low','close']
    if not set(required).issubset(df.columns): raise DataError('Missing OHLC')
    df=df.sort_index().copy()
    if df.index.has_duplicates: raise DataError('Duplicate dates')
    for col in required: df[col]=pd.to_numeric(df[col],errors='coerce')
    x=df[required]
    if not np.isfinite(x.to_numpy()).all() or (x<=0).any().any():
        raise DataError('Nonpositive/nonfinite OHLC: incompatible with log-return engine')
    if ((df.high<df[['open','close','low']].max(axis=1)) |
        (df.low>df[['open','close','high']].min(axis=1))).any(): raise DataError('OHLC inconsistency')
    if len(df)<cfg['min_rows']: raise DataError('Insufficient history')
    if df.index.min()>pd.Timestamp(cfg['start'])+pd.Timedelta(days=10):
        raise DataError(f'Truncated requested history: requested={cfg["start"]}, first={df.index.min().date()}, last={df.index.max().date()}, rows={len(df)}')
    gaps=df.index.to_series().diff().dt.days.dropna()
    if len(gaps) and (float(gaps.median())>4 or int(gaps.max())>14):
        raise DataError(f'Not daily frequency: median gap {gaps.median():.0f}d, max {gaps.max():.0f}d. Daily frequency is mandatory; the series is rejected, never resampled or substituted')
    moves=df.close.pct_change(fill_method=None)
    if moves.abs().gt(.35).any():
        when=moves.abs().idxmax(); i=df.index.get_loc(when)
        raise DataError(f'Structural move >35%: date={when.date()}, change={moves.loc[when]:.2%}, previous_close={df.close.iloc[i-1]:.8g}, close={df.close.iloc[i]:.8g}; manual review required')
    age=(pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()-df.index[-1]).days
    if age<0: raise DataError('Future observation')
    if 'volume' not in df: df['volume']=np.nan
    df['volume']=pd.to_numeric(df.volume,errors='coerce')
    return df, int(age)

def fetch(asset, symbol, token, cfg):
    cache=ROOT/'private/cache'/f'{asset["id"]}.json'
    old=pd.DataFrame(); start=cfg['start']
    if cache.exists():
        saved=json.loads(cache.read_text())
        if saved['symbol']==symbol:
            old=pd.DataFrame(saved['rows']); old.index=pd.to_datetime(old.pop('date'))
            start=max(pd.Timestamp(cfg['start']),old.index[-1]-pd.Timedelta(days=10)).strftime('%Y-%m-%d')
    # Exclude current UTC day; completed EOD bars only.
    end=(pd.Timestamp.now(tz='UTC')-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    fresh=pd.DataFrame(api('eod/'+quote(symbol,safe='.'),token,{'from':start,'to':end,'period':'d','order':'a'}))
    if len(fresh):
        fresh.index=pd.to_datetime(fresh.pop('date'))
        if fresh.index.has_duplicates: raise DataError('Provider duplicate dates')
        if (fresh.index>pd.Timestamp(end)).any(): raise DataError('Unexpected current/future bar')
    df=pd.concat([old,fresh]); df=df[~df.index.duplicated(keep='last')]
    df=df[df.index>=pd.Timestamp(cfg['start'])]  # history window starts at cfg['start']; cached pre-window bars are dropped
    # Preserve raw diagnostic observations for rejected series, outside published files.
    if not df.empty:
        diagnostic=df.sort_index()
        rows=json.loads(diagnostic.rename_axis('date').reset_index().to_json(orient='records',date_format='iso'))
        write_json(ROOT/'private/probes'/f'{asset["id"]}.json',{'symbol':symbol,'rows':rows})
    df,age=validate(df,cfg)
    rows=json.loads(df.rename_axis('date').reset_index().to_json(orient='records',date_format='iso'))
    write_json(cache,{'symbol':symbol,'rows':rows})
    return df,age

def features(df,c):
    d=df.copy(); close=d.close
    d['basis']=close.rolling(c['bb_length']).mean()
    sd=close.rolling(c['bb_length']).std(ddof=0)*c['bb_std']
    d['upper']=d.basis+sd; d['lower']=d.basis-sd
    tr=pd.concat([d.high-d.low,(d.high-close.shift()).abs(),(d.low-close.shift()).abs()],axis=1).max(axis=1)
    smooth=lambda x,n: x.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    d['atr']=smooth(tr,c['atr_length'])
    delta=close.diff(); gain=smooth(delta.clip(lower=0),14); loss=smooth(-delta.clip(upper=0),14)
    d['rsi']=100-100/(1+gain/loss.replace(0,np.nan))
    d.loc[(loss==0)&(gain>0),'rsi']=100; d.loc[(gain==0)&(loss>0),'rsi']=0
    d.loc[(gain==0)&(loss==0),'rsi']=50
    up=d.high.diff(); down=-d.low.diff(); denom=smooth(tr,14)
    plus=100*smooth(up.where((up>down)&(up>0),0),14)/denom
    minus=100*smooth(down.where((down>up)&(down>0),0),14)/denom
    d['adx']=smooth(100*(plus-minus).abs()/(plus+minus).replace(0,np.nan),14)
    trend=close.rolling(c['trend_length']).mean()
    # Last opposite-band regime, not repeated upper-band re-crossings.
    raw=pd.Series(np.where(close>d.upper,1,np.where(close<d.lower,-1,np.nan)),index=d.index)
    regime=raw.ffill().fillna(0) # state only: never fill prices
    signal=regime.where(regime.ne(regime.shift(fill_value=0)),0).astype(int)
    d['raw_signal']=signal
    eligible=pd.Series(True,index=d.index)
    if c['trend_filter']: eligible &= ((signal==1)&(close>trend))|((signal==-1)&(close<trend))
    if c['rsi_filter']: eligible &= ((signal==1)&(d.rsi>=55))|((signal==-1)&(d.rsi<=45))
    if c['adx_filter']: eligible &= d.adx>=c['adx_min']
    if c['volume_filter']: eligible &= d.volume>d.volume.rolling(20).mean()
    d['signal']=signal.where(eligible,0)
    return d

def backtest(d,c,start_date=None):
    cash=c['capital']; p=None; curve=[]; trades=[]; active=[]
    slip=c['slippage']; fee=c['commission']
    def close_position(base,reason,date):
        nonlocal cash,p
        price=base*(1-p['side']*slip)
        gross=p['side']*p['qty']*(price-p['entry'])
        cost=p['qty']*price*fee; cash+=gross-cost
        trades.append(dict(entry_date=str(p['date'].date()),exit_date=str(date.date()),
            direction=p['side'],entry=p['entry'],exit=price,quantity=p['qty'],
            net_pnl=gross-cost-p['fee'],reason=reason))
        p=None
    for i,(date,row) in enumerate(d.iterrows()):
        was_active=p is not None
        prev=d.iloc[i-1] if i else None
        allowed=i>0 and (start_date is None or date>=pd.Timestamp(start_date))
        if allowed:
            # Gap protection has priority over market reversal orders.
            if p:
                s=p['side']
                if s*(row.open-p['stop'])<=0: close_position(row.open,'gap_stop',date)
                elif s*(row.open-p['target'])>=0: close_position(p['target'],'gap_target_limit',date)
            if p and int(prev.raw_signal)==-p['side']: close_position(row.open,'opposite_regime',date)
            direction=int(prev.signal)
            mode_ok=c['mode']=='Both' or (direction==1 and c['mode']=='Long Only') or (direction==-1 and c['mode']=='Short Only')
            if not p and direction and mode_ok and cash>0 and np.isfinite(prev.atr) and prev.atr>0:
                entry=row.open*(1+direction*slip)
                distance=float(prev.atr*c['stop_atr']) # previous completed bar only
                qty=min(cash*c['risk']/distance,cash*c['exposure']/(entry*(1+fee)))
                if entry-distance>0 and qty>0:
                    cost=qty*entry*fee; cash-=cost
                    p=dict(side=direction,entry=entry,qty=qty,fee=cost,date=date,
                        stop=entry-direction*distance,target=entry+direction*distance*c['target_r'])
            if p:
                was_active=True; s=p['side']
                hit_stop=row.low<=p['stop'] if s==1 else row.high>=p['stop']
                hit_target=row.high>=p['target'] if s==1 else row.low<=p['target']
                if hit_stop: close_position(p['stop'],'stop_first',date)
                elif hit_target: close_position(p['target'],'target',date)
            # CLOSE-based trailing becomes active NEXT bar, never retroactively.
            if p and c['trail_atr']>0 and np.isfinite(row.atr):
                stop=row.close-p['side']*c['trail_atr']*row.atr
                p['stop']=max(p['stop'],stop) if p['side']==1 else min(p['stop'],stop)
        value=cash+(p['side']*p['qty']*(row.close-p['entry']) if p else 0)
        if value<=0: raise DataError('Equity nonpositive: risk model invalid')
        curve.append(value); active.append(int(was_active))
    if p:
        close_position(d.close.iloc[-1],'end_of_test',d.index[-1]); curve[-1]=cash
    out=pd.DataFrame({'equity':curve,'exposed':active},index=d.index)
    if start_date is not None: out=out.loc[pd.Timestamp(start_date):]
    return out,pd.DataFrame(trades)

def metrics(eq,tr,c):
    """Performance & risk ratios via QuantStats. No hand-rolled fallback engine."""
    r=eq.equity.pct_change(); r.iloc[0]=eq.equity.iloc[0]/c['capital']-1
    n=c['annual_bars']; rf=c['annual_rf']
    def q(name,*args,**kwargs):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')  # degenerate-series warnings map to None below
                return _finite(_qcall(getattr(qs.stats,name),*args,**kwargs))
        except Exception: return None
    pnl=tr.net_pnl if len(tr) else pd.Series(dtype=float)
    # Anchor at the initial capital so drawdowns are measured from capital (v3 definition):
    r_dd=pd.Series(np.concatenate([[0.0],np.asarray(r,dtype=float)]))
    return dict(
        total_return=_finite(qs.stats.comp(r)),
        cagr=q('cagr',r,periods=n),
        max_drawdown=q('max_drawdown',r_dd),
        volatility=q('volatility',r,periods=n),
        sharpe=q('sharpe',r,rf=rf,periods=n),
        sortino=q('sortino',r,rf=rf,periods=n),
        calmar=q('calmar',r,periods=n),
        omega=q('omega',r,rf=rf,periods=n),
        var_95=q('var',r,confidence=0.95),
        cvar_95=q('cvar',r,confidence=0.95),
        skew=q('skew',r),
        kurtosis=q('kurtosis',r),
        tail_ratio=q('tail_ratio',r),
        ulcer_index=q('ulcer_index',r_dd),
        trades=len(tr),
        win_rate=float((pnl>0).mean()) if len(pnl) else None,
        profit_factor=float(pnl[pnl>0].sum()/-pnl[pnl<0].sum()) if (pnl<0).any() else None,
        exposure=float(eq.exposed.mean()))

def analyze(df,c):
    split=int(len(df)*c['train_ratio']); date=df.index[split]
    best=c.copy(); trials=[]
    if c['optimize']:
        for length in [20,55,75]:
            for mult in [1.,1.5,2.]:
                candidate=dict(c,bb_length=length,bb_std=mult)
                train=features(df.iloc[:split],candidate)
                eq,tr=backtest(train,candidate,train.index[min(c['trend_length']+20,len(train)-2)])
                m=metrics(eq,tr,candidate)
                score=m['sharpe'] if m['trades']>=10 and m['sharpe'] is not None else -1e9
                trials.append(dict(length=length,mult=mult,score=score))
        winner=max(trials,key=lambda r:r['score'])
        if winner['score']>-1e9: best.update(bb_length=winner['length'],bb_std=winner['mult'])
    d=features(df,best); eq,tr=backtest(d,best,date)
    m=metrics(eq,tr,best); m['test_start']=str(date.date())
    m['bb_length']=best['bb_length']; m['bb_std']=best['bb_std']
    m['egarch_annual_pct']=None; m['egarch_status']='unavailable'
    try:
        from arch import arch_model
        returns=100*np.log(df.close).diff().dropna()
        fit=arch_model(returns,mean='Constant',vol='EGARCH',p=1,o=1,q=1,dist='t',rescale=False).fit(disp='off',show_warning=False)
        sigma=float(fit.conditional_volatility.iloc[-1]*np.sqrt(c['annual_bars']))
        ewma=float(returns.ewm(span=63).std().iloc[-1]*np.sqrt(c['annual_bars']))
        if fit.convergence_flag==0 and np.isfinite(sigma) and .2*ewma<=sigma<=5*ewma:
            m.update(egarch_annual_pct=sigma,egarch_status='OK')
        else: m['egarch_status']='convergence/plausibility rejected'
    except ImportError: m['egarch_status']='arch not installed'
    except Exception: m['egarch_status']='estimation failed'
    return d,eq,tr,m,trials

def page(title,body):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'+html.escape(title)+'''</title><style>
body{font:16px Arial,sans-serif;margin:0;background:#101b2b;color:#eef2f6}main{max-width:1250px;margin:auto;padding:24px}h1{font-weight:400;color:#ee9b4c}a{color:#82c9ff}table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #526070}section{overflow-x:auto}select{padding:10px}p{line-height:1.6}
</style><main><h1>'''+html.escape(title)+'</h1>'+body+'</main></html>'

def portfolio_analytics(closes,cfg,names):
    """PyPortfolioOpt research block on exact common observation dates. No fill, no proxy."""
    out=dict(status='unavailable',risk_free=cfg['annual_rf'],names=names)
    if len(closes)<5:
        out['reason']='fewer than 5 validated OHLC series; a cross-market panel is required'
        return out
    prices=pd.DataFrame(closes).sort_index()
    clean=prices.pct_change(fill_method=None).dropna(how='any')
    if len(clean)<cfg['min_rows']:
        out['reason']=(f'exact common observations ({len(clean)}) below min_rows={cfg["min_rows"]}; '
                       'dates are never filled or proxied')
        return out
    mu=expected_returns.mean_historical_return(prices,frequency=cfg['annual_bars'])
    S=risk_models.sample_cov(prices,frequency=cfg['annual_bars'])
    ids=list(prices.columns)
    def perf(weights):
        w=np.array([weights.get(i,0.0) for i in ids])
        mu_v=mu.reindex(ids).to_numpy(); S_m=S.loc[ids,ids].to_numpy()
        ret=float(w@mu_v); vol=float(np.sqrt(w@S_m@w))
        return dict(expected_return=ret,volatility=vol,
                    sharpe=(ret-cfg['annual_rf'])/vol if vol>0 else None)
    def tidy(w):
        return {i:float(round(v,4)) for i,v in w.items() if v>1e-4}
    block=dict(n_assets=len(ids),n_observations=int(len(clean)),
               window_start=str(clean.index[0].date()),window_end=str(clean.index[-1].date()))
    try:
        ef=EfficientFrontier(mu,S); ef.max_sharpe(risk_free_rate=cfg['annual_rf'])
        w=ef.clean_weights(); block['max_sharpe']=dict(weights=tidy(w),**perf(w))
    except Exception as exc: block['max_sharpe_error']=f'{type(exc).__name__}: {exc}'
    try:
        ef=EfficientFrontier(mu,S); ef.min_volatility()
        w=ef.clean_weights(); block['min_volatility']=dict(weights=tidy(w),**perf(w))
    except Exception as exc: block['min_volatility_error']=f'{type(exc).__name__}: {exc}'
    try:
        hrp=HRPOpt(clean); hrp.optimize()
        w={k:float(v) for k,v in hrp.clean_weights().items()}
        block['hrp']=dict(weights=tidy(w),**perf(w))
    except Exception as exc: block['hrp_error']=f'{type(exc).__name__}: {exc}'
    out.update(status='OK',**block)
    return out

def build(token):
    initialize(); cfg=json.loads((ROOT/'config.json').read_text()); assets=json.loads((ROOT/'universe.json').read_text())
    if not (0<cfg['risk']<=.1 and 0<cfg['exposure']<=1 and .5<=cfg['train_ratio']<=.9):
        raise DataError('Invalid risk/exposure/train_ratio settings')
    if cfg['stop_atr']<=0 or cfg['target_r']<=0 or cfg['bb_length']<2:
        raise DataError('Invalid stop/target/Bollinger parameters')
    if len([a for a in assets if a['asset_class']=='Equity Index'])!=30: raise DataError('Registry must contain exactly 30 equity indices')
    records=catalog(token); audit=[]; summaries=[]; returns={}; closes={}; names={}
    from tempfile import mkdtemp
    stage=Path(mkdtemp(prefix='bb-build-',dir=ROOT))
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    for asset in assets:
        row={k:asset[k] for k in ('id','name','region','asset_class')}
        try:
            if asset['asset_class']=='Commodities' and not asset['provider_symbol']:
                try:
                    m,body=commodity_view(asset,cfg,token,api)
                except ValueError as exc:
                    raise DataError(str(exc)) from None
                row.update(m)
                summaries.append(row.copy())
                (stage/(asset['id']+'.html')).write_text(page(asset['name'],body))
                write_json(stage/(asset['id']+'.json'),row)
                audit.append(row); print(asset['id'],asset['name'],row['status'])
                continue
            resolved=resolve(asset,records); symbol=resolved['provider_symbol']
            row.update(symbol=symbol,currency=resolved.get('Currency',''),provider_name=resolved.get('Name',''),
                instrument_type=resolved.get('instrument_type',asset.get('instrument_type') or 'Cash Index'))
            df,age=fetch(asset,symbol,token,cfg)
            row.update(last_date=str(df.index[-1].date()),age_days=age,observations=len(df))
            if age>cfg['max_age_days']: raise DataError('STALE: calendar-age threshold; check exchange holidays')
            if cfg['volume_filter'] and not asset['volume_verified']:
                raise DataError('Volume filter requested but volume semantics not verified')
            d,eq,tr,m,trials=analyze(df,cfg)
            volume_ok=asset['volume_verified'] and d.volume.tail(55).gt(0).all()
            row.update(status='PASS',vwap_eligible=bool(volume_ok))
            m.update(row); summaries.append(m); returns[asset['id']]=df.close.pct_change(fill_method=None)
            closes[asset['id']]=df.close; names[asset['id']]=asset['name']
            f=make_subplots(rows=5,cols=1,shared_xaxes=True,vertical_spacing=.04,row_heights=[.36,.18,.14,.16,.16])
            f.add_trace(go.Candlestick(x=d.index,open=d.open,high=d.high,low=d.low,close=d.close,name='OHLC'),row=1,col=1)
            for col in ['basis','upper','lower']:
                f.add_trace(go.Scatter(x=d.index,y=d[col],name=col),row=1,col=1)
            if volume_ok:
                vwap=(((d.high+d.low+d.close)/3*d.volume).rolling(55).sum()/d.volume.rolling(55).sum())
                f.add_trace(go.Scatter(x=d.index,y=vwap,name='55-bar rolling VWAP'),row=1,col=1)
            f.add_trace(go.Scatter(x=eq.index,y=eq.equity,name='OOS simulated equity'),row=2,col=1)
            bh=cfg['capital']*d.loc[eq.index,'close']/d.loc[eq.index[0],'close']
            f.add_trace(go.Scatter(x=eq.index,y=bh,name='B&H gross, no costs'),row=2,col=1)
            f.add_trace(go.Scatter(x=eq.index,y=100*(eq.equity/eq.equity.cummax().clip(lower=cfg['capital'])-1),name='Drawdown %',fill='tozeroy'),row=3,col=1)
            r_roll=eq.equity.pct_change(); r_roll.iloc[0]=eq.equity.iloc[0]/cfg['capital']-1
            try:
                roll_sharpe=_qcall(qs.stats.rolling_sharpe,r_roll,rf=cfg['annual_rf'],
                                   periods=cfg['annual_bars'],window=min(126,len(r_roll)))
            except Exception: roll_sharpe=None
            if roll_sharpe is not None and int(roll_sharpe.notna().sum())>1:
                f.add_trace(go.Scatter(x=roll_sharpe.index,y=roll_sharpe,name='Rolling Sharpe 126d',fill='tozeroy'),row=4,col=1)
            r_full=df.close.pct_change(fill_method=None)
            ewma_var=(r_full**2).ewm(alpha=1-EWMA_LAMBDA,adjust=False).mean()
            ewma_pct=np.sqrt(ewma_var)*np.sqrt(cfg['annual_bars'])*100
            m['ewma_annual_pct']=_finite(float(ewma_pct.iloc[-1]))
            f.add_trace(go.Scatter(x=ewma_pct.index,y=ewma_pct,name='EWMA volatility (ann. %)',fill='tozeroy'),row=5,col=1)
            f.update_layout(height=1300,template='plotly_dark',title=asset['name'])
            body='<a href="index.html">Back</a><p>Research on reference prices; not executable index/futures P&L. Each series uses independent capital. Short borrow, futures rolls and FX conversion are not modeled.</p>'
            body+=f.to_html(full_html=False,include_plotlyjs=True)
            body+=pd.DataFrame([m]).to_html(index=False,escape=True)+tr.to_html(index=False,escape=True)
            (stage/(asset['id']+'.html')).write_text(page(asset['name'],body))
            write_json(stage/(asset['id']+'.json'),dict(metrics=m,trades=tr.to_dict('records'),optimization=trials))
        except DataError as exc: row.update(status='REJECTED',reason=str(exc))
        audit.append(row); print(asset['id'],asset['name'],row['status'])
    write_json(stage/'portfolio.json',portfolio_analytics(closes,cfg,names))
    write_json(ROOT/'private/latest_audit.json',audit)
    if not summaries: raise DataError('No valid fresh series: previous deployment retained; inspect private/latest_audit.json')
    stamp=datetime.now(timezone.utc).isoformat()
    links=''.join('<tr data-region="'+html.escape(m['region'],quote=True)+'"><td>'+html.escape(m['region'])+'</td><td><a href="'+m['id']+'.html">'+html.escape(m['name'])+'</a></td><td>'+m['last_date']+'</td><td>'+(str(round(m['total_return']*100,2)) if m.get('total_return') is not None else 'N/A — price observations only')+'</td></tr>' for m in summaries)
    body='<p>By Murat KONUKLAR · EODHD only · Generated '+stamp+'</p><p id="age"></p><p>Displayed '+str(len(summaries))+'/'+str(len(assets))+' instruments. Price-only commodity observations are separate from OHLC backtests. Daily retrieval does not imply daily source frequency. No proxy or synthetic market data.</p>'
    body+='<label>Region <select id="region"><option>All</option>'+''.join('<option>'+html.escape(x)+'</option>' for x in GROUPS)+'</select></label><section><table><tr><th>Region</th><th>Instrument</th><th>Data date</th><th>OOS return %</th></tr>'+links+'</table></section><h2>Data Audit</h2><section>'+pd.DataFrame(audit).to_html(index=False,escape=True)+'</section>'
    body+='''<script>document.querySelector('#region').onchange=e=>document.querySelectorAll('tr[data-region]').forEach(r=>r.hidden=e.target.value!=='All'&&r.dataset.region!==e.target.value);const hours=(Date.now()-Date.parse('''+json.dumps(stamp)+'''))/3600000;document.querySelector('#age').textContent=hours>36?'WARNING: build is over 36 hours old; scheduled update may have failed.':'Build age: '+hours.toFixed(1)+' hours';</script>'''
    (stage/'index.html').write_text(page('Global Bollinger — EODHD Analytics',body))
    write_json(stage/'audit.json',audit); write_json(stage/'summary.json',summaries)
    # Pairwise exact common observations, no fill across market holidays.
    pd.DataFrame(returns).corr(min_periods=100).to_csv(stage/'correlations.csv')
    from report_ui import write_portal
    write_portal(stage)
    for file in stage.iterdir():
        if token and token.encode() in file.read_bytes(): raise DataError('Secret detected: publication blocked')
    target=ROOT/'netlify_site.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for file in stage.iterdir(): z.write(file,file.name)
    print('Build OK:',target,'HTML:',stage/'index.html')

def deploy():
    if os.getenv('PUBLISH_APPROVED')!='true': raise DataError('Set PUBLISH_APPROVED=true only after checking site access and data display license')
    token=os.environ['NETLIFY_AUTH_TOKEN']; site=os.environ['NETLIFY_SITE_ID']
    if not re.fullmatch(r'[A-Za-z0-9-]+',site): raise DataError('Invalid Netlify site ID')
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/zip'}
    req=Request('https://api.netlify.com/api/v1/sites/'+site+'/deploys',data=(ROOT/'netlify_site.zip').read_bytes(),headers=headers)
    try:
        with urlopen(req,timeout=120) as response: result=json.load(response)
        for _ in range(60):
            with urlopen(Request('https://api.netlify.com/api/v1/deploys/'+result['id'],headers={'Authorization':'Bearer '+token}),timeout=30) as response: state=json.load(response)
            if state['state']=='ready': print('Deployment ready:',state.get('ssl_url',state.get('url'))); return
            if state['state']=='error': raise DataError('Netlify deploy failed')
            time.sleep(5)
        raise DataError('Deployment pending: check Netlify dashboard')
    except (HTTPError,URLError): raise DataError('Netlify request failed; inspect account/site permissions') from None

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--init',action='store_true'); parser.add_argument('--catalog',action='store_true'); parser.add_argument('--deploy',action='store_true')
    args=parser.parse_args()
    try:
        initialize()
        print('EODHD Bollinger v'+VERSION)
        if args.init: print('Configuration and universe created; existing settings preserved.')
        elif args.deploy: deploy()
        else:
            token=os.getenv('EODHD_API_TOKEN','').strip()
            if not token: raise DataError('Set EODHD_API_TOKEN using Colab Secrets / GitHub Actions Secrets')
            if args.catalog: catalog(token)
            else: build(token)
    except DataError as exc: raise SystemExit(str(exc)) from None
