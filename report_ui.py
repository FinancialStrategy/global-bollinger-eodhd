"""v4 portal renderer; reuses exact Plotly traces, no market-data recalculation."""
import base64,json,re,shutil,zipfile,argparse
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from analytics import equity_returns, calculate, ENGINE_VERSION
from plotly.offline import get_plotlyjs

def plain(obj):
    if isinstance(obj,dict) and 'bdata' in obj and 'dtype' in obj:
        return plain(np.frombuffer(base64.b64decode(obj['bdata']),dtype=obj['dtype']).tolist())
    if isinstance(obj,dict): return {k:plain(v) for k,v in obj.items()}
    if isinstance(obj,list): return [plain(v) for v in obj]
    if isinstance(obj,float) and not np.isfinite(obj): return None
    return obj

def traces_from_html(text):
    decoder=json.JSONDecoder()
    # Only parse generated newPlot calls with JSON arguments; never evaluate HTML/JS.
    for match in re.finditer(r'Plotly\.newPlot\(\s*"',text):
        try:
            offset=match.end()-1; _,end=decoder.raw_decode(text,offset)
            offset=end
            while text[offset] in ' \t\r\n,': offset+=1
            traces,_=decoder.raw_decode(text,offset)
            if isinstance(traces,list): return plain(traces)
        except (ValueError,IndexError): continue
    raise ValueError('No supported Plotly trace data in report')

def write_portal(stage,config,prune=True):
    stage=Path(stage)
    summaries=json.loads((stage/'summary.json').read_text())
    audit=json.loads((stage/'audit.json').read_text())
    def mark_daily(row):
        row['investment_region']='Global / Reference Markets' if row['asset_class'] in ('Commodities','Precious Metals') else row['region']
        if row.get('status')=='PRICE_ONLY' and row.get('interval')!='daily':
            row['status']='REJECTED'
            row['reason']='DAILY_SOURCE_REQUIRED: provider interval is '+str(row.get('interval') or 'unknown')+'; no resampling or synthetic daily series used'
        return row
    audit=[mark_daily(dict(row)) for row in audit]
    assets=[]; published_summaries=[]
    end=min((pd.Timestamp(m['last_date']) for m in summaries if m['status']=='PASS'),default=None)
    windows={'FULL':None,'1Y':end-pd.DateOffset(years=1) if end is not None else None,'3Y':end-pd.DateOffset(years=3) if end is not None else None}
    for m in summaries:
        m=mark_daily(dict(m))
        if m.get('status')=='REJECTED' and 'DAILY_SOURCE_REQUIRED' in str(m.get('reason')):
            continue
        ident=m['id']; detail=json.loads((stage/(ident+'.json')).read_text())
        traces=traces_from_html((stage/(ident+'.html')).read_text())
        analysis={}
        if m['status']=='PASS':
            curves=[t for t in traces if t.get('name')=='OOS simulated equity']
            if len(curves)!=1: raise ValueError('Missing or ambiguous strategy equity: '+ident)
            curve=curves[0]
            equity=pd.Series(curve['y'],index=pd.to_datetime(curve['x']),dtype=float)
            r=equity_returns(equity,config['capital'])
            if not np.isclose(equity.iloc[-1]/config['capital']-1,m['total_return'],atol=1e-9,rtol=1e-8):
                raise ValueError('Initial capital does not reconcile with source report: '+ident)
            for key,start in windows.items():
                if start is not None and r.index[0]>start:
                    analysis[key]={'metric_status':'UNAVAILABLE','reason':'OOS history does not cover the comparison window'}
                    continue
                sample=r if key=='FULL' else r.loc[(r.index>start)&(r.index<=end)]
                if len(sample)<2:
                    analysis[key]={'metric_status':'UNAVAILABLE','reason':'Insufficient observations'}
                    continue
                analysis[key]=calculate(sample,config['annual_rf'],config['annual_bars'])
            m.update(analysis['FULL'])
            detail['metrics']=m
            (stage/(ident+'.json')).write_text(json.dumps(detail,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        assets.append(dict(meta=m,traces=traces,trades=detail.get('trades',[]),analytics=analysis))
        published_summaries.append(m)
    original=(stage/'index.html').read_text(encoding='utf-8') if (stage/'index.html').exists() else ''
    stamp=re.search(r'Generated ([0-9T:.+Z-]+)',original)
    payload=dict(assets=assets,audit=audit,rendered=datetime.now(timezone.utc).isoformat(),source_generated=stamp.group(1) if stamp else None,
        policy={'source':'EODHD','frequency':'daily','fallback':False,'synthetic_market_data':False,'imputation':False,'resampling':False},
        metrics={'engine':'QuantStats','version':ENGINE_VERSION,'annual_rf':config['annual_rf'],'annual_bars':config['annual_bars'],
                 'basis':'Net OOS strategy returns in local reference units; independent accounts',
                 'common_end':str(end.date()) if end is not None else None,
                 'windows':{k:str(v.date()) if v is not None else None for k,v in windows.items()}})
    (stage/'summary.json').write_text(json.dumps(published_summaries,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (stage/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (stage/'portal-data.js').write_text('window.PORTAL_DATA='+json.dumps(plain(payload),ensure_ascii=False,allow_nan=False).replace('<','\\u003c')+';',encoding='utf-8')
    (stage/'plotly.min.js').write_text(get_plotlyjs(),encoding='utf-8')
    for name in ('portal.html','portal.css','portal.js'):
        shutil.copyfile(Path(__file__).with_name(name),stage/('index.html' if name=='portal.html' else name))
    if prune:
        for file in stage.glob('*.html'):
            if file.name!='index.html' and not file.name.startswith('qs_'):
                file.unlink()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--output',default='netlify_portal_v4.zip');p.add_argument('--config',required=True,help='Explicit metric assumptions and original initial capital');args=p.parse_args()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as temp:
        root=Path(temp)
        with zipfile.ZipFile(args.source) as z:
            for entry in z.infolist():
                if not (root/entry.filename).resolve().is_relative_to(root.resolve()): raise ValueError('Unsafe ZIP path')
            z.extractall(root)
        write_portal(root,json.loads(Path(args.config).read_text()))
        with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as z:
            for file in root.iterdir():
                if file.is_file(): z.write(file,file.name)
    print('Portal ready:',args.output)
