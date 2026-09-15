'use strict';
const D=window.PORTAL_DATA,$=id=>document.getElementById(id), colors=['#67bafa','#f4b76f','#b199e8','#42c9a0','#f17d87'];
const valid=D.assets.filter(a=>a.meta.status==='PASS'), commodities=D.assets.filter(a=>a.meta.status==='PRICE_ONLY');
const escapeHTML=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,d=2)=>x===null||x===undefined||!Number.isFinite(Number(x))?'—':Number(x).toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const pct=x=>x==null?'—':num(x*100)+'%';
const median=a=>{const v=a.filter(x=>Number.isFinite(x)).sort((x,y)=>x-y),n=v.length;if(!n)return null;const m=n>>1;return n%2?v[m]:(v[m-1]+v[m])/2;};
let tab='overview';
const config={responsive:true,displaylogo:false,scrollZoom:true,displayModeBar:true,toImageButtonOptions:{format:'png',scale:2},modeBarButtonsToRemove:['lasso2d','select2d']};
const base=()=>({paper_bgcolor:'#111d30',plot_bgcolor:'#111d30',font:{family:'Segoe UI,Arial',color:'#aebed2',size:12},margin:{l:72,r:28,t:40,b:70},hovermode:'x unified',dragmode:'zoom',legend:{orientation:'h',y:1.13,x:0},xaxis:{gridcolor:'#24344a',showspikes:true,spikemode:'across',spikesnap:'cursor',rangeslider:{visible:false}},yaxis:{gridcolor:'#24344a',automargin:true,zerolinecolor:'#40516a',fixedrange:false}});
function rangeY(traces,range){let lo=Infinity,hi=-Infinity;const left=range?Date.parse(range[0]):-Infinity,right=range?Date.parse(range[1]):Infinity;
 for(const t of traces){if(t.visible===false||t.visible==='legendonly')continue;const arrays=t.type==='candlestick'?[t.low,t.high]:[t.y];
 for(let i=0;i<(t.x||[]).length;i++){const x=Date.parse(t.x[i]);if(x<left||x>right)continue;for(const a of arrays){const y=a?.[i];if(typeof y==='number'&&Number.isFinite(y)){lo=Math.min(lo,y);hi=Math.max(hi,y);}}}}
 if(!Number.isFinite(lo))return null;const pad=(hi-lo||Math.abs(hi)*.02||1)*.07;return [lo-pad,hi+pad];}
window.portalRangeY=rangeY;
function autoscale(id){const el=$(id);if(!el.data)return;const r=el.layout.xaxis?.autorange?null:el.layout.xaxis?.range;const y=rangeY(el.data,r);if(y)Plotly.relayout(el,{'yaxis.range':y,'yaxis.autorange':false});}
async function timeChart(id,traces,unit,opts){const clean=traces.map((t,i)=>{const v=structuredClone(t);delete v.xaxis;delete v.yaxis;v.line={...v.line,color:colors[i%colors.length],width:i?1.4:2};return v;});
 const layout=base();layout.yaxis.title={text:unit};layout.xaxis.type='date';if(opts&&opts.slider)layout.xaxis.rangeslider={visible:true,thickness:.06};
 const yr=rangeY(clean,null);if(yr)layout.yaxis.range=yr;
 await Plotly.newPlot(id,clean,layout,config);const el=$(id);
 el.on('plotly_relayout',ev=>{if(Object.keys(ev).some(k=>k.startsWith('xaxis.range')||k==='xaxis.autorange'))autoscale(id);});
 el.on('plotly_restyle',()=>autoscale(id));}
function table(id,rows,cols){$(id).innerHTML='<table><thead><tr>'+cols.map(c=>'<th>'+escapeHTML(c[0])+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+escapeHTML(typeof c[1]==='function'?c[1](r):r[c[1]])+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
function bars(id,rows,value,unit){const layout=base();layout.hovermode='closest';layout.margin.l=160;layout.margin.b=60;layout.xaxis={title:{text:unit},gridcolor:'#24344a',zerolinecolor:'#91a3ba'};layout.yaxis={automargin:true};$(id).style.height=Math.max(360,rows.length*29+90)+'px';return Plotly.newPlot(id,[{type:'bar',orientation:'h',y:rows.map(r=>r.name),x:rows.map(value),marker:{color:rows.map(r=>value(r)>=0?colors[0]:colors[4])},hovertemplate:'%{y}: %{x:.2f}<extra></extra>'}],layout,config);}
function options(id,assets){$(id).innerHTML=assets.map(a=>'<option value="'+escapeHTML(a.meta.id)+'">'+escapeHTML(a.meta.name)+'</option>').join('');}
function periods(id,charts){$(id).innerHTML=['1M','3M','6M','1Y','3Y','ALL'].map(p=>'<button type="button" data-period="'+p+'">'+p+'</button>').join('')+'<button type="button" data-period="AUTO">Auto</button>';
 $(id).onclick=async e=>{const period=e.target.dataset.period;if(!period)return;for(const b of $(id).querySelectorAll('button'))b.classList.toggle('active',b.dataset.period===period);
 for(const chart of charts){const el=$(chart);if(!el.data?.length)continue;if(period==='AUTO'){autoscale(chart);continue;}if(period==='ALL'){await Plotly.relayout(el,{'xaxis.autorange':true});autoscale(chart);continue;}
 const dates=el.data.flatMap(t=>t.x||[]).map(x=>Date.parse(x)).filter(Number.isFinite);if(!dates.length)continue;const end=new Date(Math.max(...dates)),start=new Date(end);start.setUTCMonth(start.getUTCMonth()-({'1M':1,'3M':3,'6M':6,'1Y':12,'3Y':36}[period]));await Plotly.relayout(el,{'xaxis.range':[start.toISOString(),end.toISOString()],'xaxis.autorange':false});autoscale(chart);}};}
async function market(){const a=valid.find(a=>a.meta.id===$('marketAsset').value);if(!a){$('marketInfo').textContent='No eligible OHLC series.';return;}
 const m=a.meta;$('marketInfo').innerHTML='<strong>'+escapeHTML(m.name)+'</strong> · '+escapeHTML(m.symbol)+'<br>Latest data: '+escapeHTML(m.last_date)+' · OOS: '+escapeHTML(m.test_start)+' → '+escapeHTML(m.last_date)+' · Net return '+pct(m.total_return)+' · Sharpe '+num(m.sharpe);
 const price=a.traces.filter(t=>!t.yaxis||t.yaxis==='y');
 if($('tradeMarkers').checked)for(const side of [1,-1]){const rows=a.trades.filter(t=>t.direction===side);if(rows.length)price.push({type:'scatter',mode:'markers',x:rows.map(t=>t.entry_date),y:rows.map(t=>t.entry),name:side===1?'Long entry':'Short entry',marker:{symbol:side===1?'triangle-up':'triangle-down',size:9,color:side===1?colors[3]:colors[4]}});}
 await timeChart('price',price,m.currency||'Price',{slider:true});await timeChart('equity',a.traces.filter(t=>t.yaxis==='y2'),'Capital');await timeChart('drawdown',a.traces.filter(t=>t.yaxis==='y3'),'%');const y4=a.traces.filter(t=>t.yaxis==='y4'),y5=a.traces.filter(t=>t.yaxis==='y5');
 if(y4.length)await timeChart('rollsharpe',y4,'Sharpe (ann.)');else $('rollsharpe').innerHTML='<div class="notice">Rolling Sharpe needs one full rebuild with the current engine (traces are built at build time).</div>';
 if(y5.length)await timeChart('ewma',y5,'Ann. %');else $('ewma').innerHTML='<div class="notice">EWMA volatility needs one full rebuild with the current engine (traces are built at build time).</div>';
 $('marketPeriods').querySelector('[data-period="1Y"]').click();}
async function commodity(){const a=commodities.find(a=>a.meta.id===$('commodityAsset').value);if(!a){$('commodityInfo').textContent='No commodity data available.';return;}const m=a.meta;$('commodityInfo').innerHTML='<strong>'+escapeHTML(m.name)+'</strong><br>'+escapeHTML(m.provider_name)+' · '+escapeHTML(m.interval)+' · '+escapeHTML(m.unit)+' · Latest observation '+escapeHTML(m.last_date);await timeChart('commodityChart',a.traces,m.unit);$('commodityPeriods').querySelector('[data-period="3Y"]').click();}
function overview(){const eqIdx=valid.filter(a=>a.meta.asset_class==='Equity Index');
 const vals=[
  ['Instruments in universe',String(D.audit.length),'registry validated against the EODHD catalog on every run'],
  ['Passing OHLC validation',String(valid.length),'equity indices + precious metals · backtest-eligible'],
  ['Median OOS net return · equity indices',pct(median(eqIdx.map(a=>a.meta.total_return))),'independent capital per series · net of costs'],
  ['Median OOS Sharpe · equity indices',num(median(eqIdx.map(a=>a.meta.sharpe))),'annualized · risk-free rate per build config']];
 $('kpis').innerHTML=vals.map(v=>'<div class="kpi"><small>'+v[0]+'</small><strong>'+v[1]+'</strong><span>'+v[2]+'</span></div>').join('');
 const regions=[...new Set(D.audit.map(a=>a.region))];const l=base();l.barmode='stack';l.hovermode='closest';l.margin.l=50;l.margin.b=90;l.yaxis.title={text:'Instruments'};
 Plotly.newPlot('coverage',['PASS','PRICE_ONLY','REJECTED'].map((s,i)=>({type:'bar',name:s,x:regions,y:regions.map(r=>D.audit.filter(a=>a.region===r&&a.status===s).length),marker:{color:[colors[3],colors[0],colors[4]][i]}})),l,config);
 bars('ranking',eqIdx.map(a=>a.meta).sort((a,b)=>a.total_return-b.total_return),r=>r.total_return*100,'OOS net return (%)');}
function universe(){const region=$('uRegion').value,group=$('uGroup').value;
 const rows=D.audit.filter(r=>(region==='All'||r.region===region)&&(group==='All'||r.asset_class===group));
 $('universeCount').textContent='Showing '+rows.length+' of '+D.audit.length+' instruments';
 table('universeTable',rows,[['ID','id'],['Instrument','name'],['Region','region'],['Group','asset_class'],['Symbol','symbol'],['Status','status'],['Data date','last_date'],['Observations','observations'],['Instrument type','instrument_type']]);}
function portfolioCard(){const p=D.portfolio,el=$('portfolioCard');
 if(!p){el.innerHTML='<div class="notice">Portfolio analytics unavailable: portfolio.json missing from this build.</div>';return;}
 if(p.status!=='OK'){el.innerHTML='<div class="notice">Portfolio analytics unavailable: '+escapeHTML(p.reason||'unknown')+'</div>';return;}
 const names=p.names||{};
 const card=(title,b,err)=>{if(!b)return '<div class="pcard"><h3>'+title+'</h3><p class="note">'+escapeHTML(err||'not available')+'</p></div>';
  const w=Object.entries(b.weights||{}).sort((x,y)=>y[1]-x[1]).slice(0,5).map(([id,v])=>'<div class="wrow"><span>'+escapeHTML(names[id]||id)+'</span><b>'+num(v*100)+'%</b></div>').join('');
  return '<div class="pcard"><h3>'+title+'</h3><dl><dt>Expected return (ann.)</dt><dd>'+pct(b.expected_return)+'</dd><dt>Volatility (ann.)</dt><dd>'+pct(b.volatility)+'</dd><dt>Sharpe</dt><dd>'+num(b.sharpe)+'</dd></dl>'+(w?'<div class="weights">Top weights'+w+'</div>':'')+'</div>';};
 el.innerHTML='<div class="cards">'+card('Maximum Sharpe',p.max_sharpe,p.max_sharpe_error)+card('Minimum volatility',p.min_volatility,p.min_volatility_error)+card('Hierarchical risk parity',p.hrp,p.hrp_error)+'</div>'
 +'<p class="note">'+p.n_assets+' validated series · '+p.n_observations+' exact common observations · window '+escapeHTML(p.window_start)+' → '+escapeHTML(p.window_end)+' · pairwise-complete means/covariance · risk-free '+pct(p.risk_free)+' · reference research, not an investable allocation.</p>';}
function risk(){portfolioCard();
 const rows=valid.map(a=>a.meta);
 bars('riskChart',rows.filter(r=>Number.isFinite(r.egarch_annual_pct)).sort((a,b)=>a.egarch_annual_pct-b.egarch_annual_pct),r=>r.egarch_annual_pct,'Annualized conditional volatility (%)');
 table('perfTable',rows,[['Instrument','name'],['Total return',r=>pct(r.total_return)],['CAGR',r=>pct(r.cagr)],['Ann. volatility',r=>pct(r.volatility)],['Sharpe',r=>num(r.sharpe)],['Sortino',r=>num(r.sortino)],['Calmar',r=>num(r.calmar)],['Omega',r=>num(r.omega)],['Max drawdown',r=>pct(r.max_drawdown)],['Win rate',r=>pct(r.win_rate)],['Profit factor',r=>num(r.profit_factor)],['Trades','trades'],['Exposure',r=>pct(r.exposure)]]);
 table('riskTable',rows,[['Instrument','name'],['Daily VaR 95%',r=>pct(r.var_95)],['Daily CVaR 95%',r=>pct(r.cvar_95)],['Skew',r=>num(r.skew)],['Kurtosis',r=>num(r.kurtosis)],['Tail ratio',r=>num(r.tail_ratio)],['Ulcer index',r=>num(r.ulcer_index)],['EGARCH (ann.)',r=>num(r.egarch_annual_pct)+'%'],['EWMA (ann.)',r=>num(r.ewma_annual_pct)+'%'],['Model status','egarch_status'],['Max drawdown',r=>pct(r.max_drawdown)]]);}
function trades(){const a=valid.find(a=>a.meta.id===$('tradeAsset').value);table('tradeTable',a?.trades||[],[['Entry','entry_date'],['Exit','exit_date'],['Side',r=>r.direction===1?'Long':'Short'],['Entry price',r=>num(r.entry)],['Exit price',r=>num(r.exit)],['Quantity',r=>num(r.quantity)],['Net P&L',r=>num(r.net_pnl)],['Exit reason','reason']]);}
function audit(){const q=$('auditSearch').value.toLowerCase(),s=$('auditStatus').value;table('auditTable',D.audit.filter(r=>(!s||r.status===s)&&(r.name+' '+(r.symbol||'')).toLowerCase().includes(q)),[['Asset','name'],['Region','region'],['Symbol','symbol'],['Status','status'],['Data date','last_date'],['Observations','observations'],['Reason','reason']]);}
const tabs=[['overview','Executive'],['universe','Investment Universe'],['market','Index Lab'],['commodities','Commodities'],['risk','Risk & Performance'],['trades','Trade Log'],['audit','Data Audit']];
$('tabs').innerHTML=tabs.map(([id,label])=>'<button type="button" role="tab" id="tab-'+id+'" aria-controls="'+id+'" aria-selected="'+(id===tab)+'" data-tab="'+id+'">'+label+'</button>').join('');
for(const [id] of tabs)$(id).setAttribute('aria-labelledby','tab-'+id);
const renders={overview,universe,market,commodities:commodity,risk,trades,audit};
$('tabs').onclick=e=>{if(!e.target.dataset.tab)return;tab=e.target.dataset.tab;for(const [id] of tabs){$(id).hidden=id!==tab;$('tab-'+id).setAttribute('aria-selected',String(id===tab));}Promise.resolve(renders[tab]()).catch(err=>{$('freshness').textContent='Chart error: '+err.message;});};
$('tabs').onkeydown=e=>{const list=[...$('tabs').querySelectorAll('button')];let i=list.indexOf(document.activeElement);if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();i=(i+(e.key==='ArrowRight'?1:-1)+list.length)%list.length;list[i].focus();list[i].click();}};
options('marketAsset',valid);options('tradeAsset',valid);options('commodityAsset',commodities);
$('uRegion').innerHTML=['All',...new Set(D.audit.map(a=>a.region))].map(r=>'<option>'+escapeHTML(r)+'</option>').join('');
$('uGroup').innerHTML=['All',...new Set(D.audit.map(a=>a.asset_class))].map(r=>'<option>'+escapeHTML(r)+'</option>').join('');
periods('marketPeriods',['price','equity','drawdown','rollsharpe','ewma']);periods('commodityPeriods',['commodityChart']);
$('marketAsset').onchange=market;$('tradeMarkers').onchange=market;$('commodityAsset').onchange=commodity;$('tradeAsset').onchange=trades;$('auditSearch').oninput=audit;$('auditStatus').onchange=audit;$('uRegion').onchange=universe;$('uGroup').onchange=universe;
$('exportTrades').onclick=()=>{const a=valid.find(a=>a.meta.id===$('tradeAsset').value);if(!a?.trades.length)return;const keys=Object.keys(a.trades[0]);const safe=v=>'"'+String(v??'').replace(/"/g,'""').replace(/^[=+@]/,"'")+'"';const csv=[keys,...a.trades.map(r=>keys.map(k=>r[k]))].map(row=>row.map(safe).join(',')).join('\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8;'}));const link=document.createElement('a');link.href=url;link.download=a.meta.id+'-trades.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('buildDate').textContent='UI: '+D.rendered.slice(0,10);
const latest=D.assets.map(a=>a.meta.last_date).sort().at(-1);
$('freshness').textContent='Latest observation dates are shown per instrument · Newest observation: '+latest+' · Reloading the UI from an older report does not refresh data.';
window.addEventListener('resize',()=>document.querySelectorAll('section:not([hidden]) .js-plotly-plot').forEach(el=>Plotly.Plots.resize(el)));
overview();
if(D.source_generated){const hours=(Date.now()-Date.parse(D.source_generated))/3600000;if(hours>36)$('freshness').textContent+=' WARNING: data report generated '+Math.floor(hours)+' hours ago; check the daily update.';}
