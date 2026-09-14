"""v3 portal renderer; reuses exact Plotly traces, no market-data recalculation."""
import base64,json,re,shutil,zipfile,argparse
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
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

def write_portal(stage,prune=True):
    stage=Path(stage)
    summaries=json.loads((stage/'summary.json').read_text())
    audit=json.loads((stage/'audit.json').read_text())
    assets=[]
    for m in summaries:
        ident=m['id']; detail=json.loads((stage/(ident+'.json')).read_text())
        traces=traces_from_html((stage/(ident+'.html')).read_text())
        assets.append(dict(meta=m,traces=traces,trades=detail.get('trades',[])))
    original=(stage/'index.html').read_text(encoding='utf-8') if (stage/'index.html').exists() else ''
    stamp=re.search(r'Generated ([0-9T:.+Z-]+)',original)
    portfolio=json.loads((stage/'portfolio.json').read_text()) if (stage/'portfolio.json').exists() else None
    payload=dict(assets=assets,audit=audit,portfolio=portfolio,rendered=datetime.now(timezone.utc).isoformat(),source_generated=stamp.group(1) if stamp else None)
    (stage/'portal-data.js').write_text('window.PORTAL_DATA='+json.dumps(plain(payload),ensure_ascii=False,allow_nan=False).replace('<','\\u003c')+';',encoding='utf-8')
    (stage/'plotly.min.js').write_text(get_plotlyjs(),encoding='utf-8')
    for name in ('portal.html','portal.css','portal.js'):
        shutil.copyfile(Path(__file__).with_name(name),stage/('index.html' if name=='portal.html' else name))
    if prune:
        for a in assets: (stage/(a['meta']['id']+'.html')).unlink()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--output',default='netlify_portal_v3.zip');args=p.parse_args()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as temp:
        root=Path(temp)
        with zipfile.ZipFile(args.source) as z:
            for entry in z.infolist():
                if not (root/entry.filename).resolve().is_relative_to(root.resolve()): raise ValueError('Unsafe ZIP path')
            z.extractall(root)
        write_portal(root)
        with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as z:
            for file in root.iterdir():
                if file.is_file(): z.write(file,file.name)
    print('Portal ready:',args.output)
