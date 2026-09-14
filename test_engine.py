"""Synthetic fixtures only for unit tests, never used as market-data fallback."""
import unittest
import tempfile, contextlib, io, json, zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import bb_eodhd as b
import commodities as cm
import netlify_setup as ns

class EngineTests(unittest.TestCase):
    def fixture(self):
        return pd.DataFrame(dict(open=[100.,100.,100.],high=[101.,101.,101.],low=[99.,99.,99.],
          close=[100.,100.,100.],atr=[1.,1.,1.],signal=[1,0,0],raw_signal=[1,0,0]),
          index=pd.date_range('2025-01-01',periods=3))
    def cfg(self): return dict(b.DEFAULT,commission=0.,slippage=0.,trail_atr=0.)
    def test_universe(self):
        u=b.universe(); self.assertEqual(len(u),47)
        self.assertEqual(sum(a['asset_class']=='Equity Index' for a in u),30)
    def test_next_open_previous_atr(self):
        d=self.fixture(); d.loc[d.index[1],'atr']=1000.
        eq,tr=b.backtest(d,self.cfg())
        self.assertEqual(tr.iloc[0].entry_date,'2025-01-02')
        self.assertAlmostEqual(tr.iloc[0].quantity,500.)
    def test_gap_stop(self):
        d=self.fixture(); d.loc[d.index[2],['open','high','low','close']]=[90,91,89,90]
        eq,tr=b.backtest(d,self.cfg())
        self.assertEqual(tr.iloc[0].exit,90.)
        self.assertEqual(tr.iloc[0].reason,'gap_stop')
    def test_stop_first(self):
        d=self.fixture(); d.loc[d.index[1],['high','low']]=[110,90]
        eq,tr=b.backtest(d,self.cfg()); self.assertEqual(tr.iloc[0].exit,98.)
    def test_trailing_not_retroactive(self):
        d=self.fixture(); d.loc[d.index[1],['high','low','close']]=[110,99,109]
        eq,tr=b.backtest(d,dict(self.cfg(),target_r=100.,trail_atr=2.))
        self.assertEqual(tr.iloc[0].exit_date,'2025-01-03')
        self.assertEqual(tr.iloc[0].exit,100.)
    def test_no_trades(self):
        d=self.fixture(); d['signal']=0
        eq,tr=b.backtest(d,self.cfg()); m=b.metrics(eq,tr,self.cfg())
        self.assertEqual(m['total_return'],0.); self.assertIsNone(m['sharpe'])
    def test_fee_reconciliation(self):
        d=self.fixture(); cfg=dict(self.cfg(),commission=.001,slippage=.001)
        eq,tr=b.backtest(d,cfg)
        self.assertAlmostEqual(eq.equity.iloc[-1]-cfg['capital'],tr.net_pnl.sum())
    def test_prefix_causality(self):
        rng=np.random.default_rng(10); close=100*np.exp(np.cumsum(rng.normal(0,.01,500)))
        d=pd.DataFrame(dict(open=close,close=close,high=close*1.01,low=close*.99,volume=100),index=pd.date_range('2020-01-01',periods=500))
        full=b.features(d,b.DEFAULT); prefix=b.features(d.iloc[:350],b.DEFAULT)
        pd.testing.assert_frame_equal(full.iloc[:350],prefix)
    def test_rsi_monotonic(self):
        close=np.arange(1.,301.)
        d=pd.DataFrame(dict(open=close,close=close,high=close,low=close,volume=100))
        self.assertEqual(b.features(d,b.DEFAULT).rsi.iloc[-1],100.)
    def test_no_fuzzy_resolution(self):
        a=b.universe()[0]
        with self.assertRaises(b.DataError): b.resolve(a,[dict(Name='S&P 500 ETF',provider_symbol='SPY.US')])
    def test_first_day_return(self):
        eq=pd.DataFrame({'equity':[99000.,99000.],'exposed':[1,0]},index=pd.date_range('2020-01-01',periods=2))
        self.assertAlmostEqual(b.metrics(eq,pd.DataFrame(),self.cfg())['total_return'],-.01)
    def test_html_build_smoke(self):
        rng=np.random.default_rng(11); close=100*np.exp(np.cumsum(rng.normal(0,.008,600)))
        d=pd.DataFrame(dict(open=close,close=close,high=close*1.01,low=close*.99,volume=100.),index=pd.bdate_range('2023-01-01',periods=600))
        u=b.universe()
        def resolved(a,records):
            if a['id']!='A01': raise b.DataError('TEST unresolved')
            return dict(provider_symbol='TEST.INDX',Currency='USD',Name='Test fixture')
        with tempfile.TemporaryDirectory() as temp, patch.object(b,'ROOT',Path(temp)), patch.object(b,'catalog',return_value=[]), patch.object(b,'resolve',side_effect=resolved), patch.object(b,'commodity_view',side_effect=ValueError('TEST commodity unavailable')), patch.object(b,'fetch',return_value=(d,0)), contextlib.redirect_stdout(io.StringIO()):
            b.build('UNIT_TEST_SECRET')
            with zipfile.ZipFile(Path(temp)/'netlify_site.zip') as z:
                self.assertIn('index.html',z.namelist())
                self.assertIn('A01.html',z.namelist())
                self.assertEqual(len(json.loads(z.read('audit.json'))),47)
                for name in z.namelist(): self.assertNotIn(b'UNIT_TEST_SECRET',z.read(name))
                self.assertIn('OOS simulated equity',z.read('A01.html').decode())

    def test_catalog_no_comm(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b,'ROOT',Path(temp)), patch.object(b,'api',return_value=[]) as a:
            b.catalog('secret')
            self.assertEqual([x.args[0] for x in a.call_args_list],['exchange-symbol-list/INDX','exchange-symbol-list/FOREX'])
    def test_commodity_native_observations(self):
        payload={'meta':{'name':'WTI','unit':'USD/bbl','interval':'daily'},'data':[
            {'date':'2020-04-20','value':-37.63},{'date':'2020-04-21','value':10.},
            {'date':'2020-04-22','value':None}]}
        df,meta,missing=cm.parse_observations(payload,'daily','2010-01-01')
        self.assertEqual(list(df.columns),['value']); self.assertEqual(missing,1)
        self.assertEqual(df.iloc[0].value,-37.63)
        with self.assertRaises(ValueError): cm.parse_observations(payload,'monthly','2010-01-01')
    def test_unavailable_commodity_not_substituted(self):
        with self.assertRaises(ValueError): cm.commodity_view({'name':'Cocoa'},b.DEFAULT,'unused',None)
    def test_metals_exact_catalog(self):
        asset=next(a for a in b.universe() if a['name']=='Gold')
        with self.assertRaises(b.DataError): b.resolve(asset,[])
        row=b.resolve(asset,[{'provider_symbol':'XAUUSD.FOREX','Name':'Gold / USD'}])
        self.assertEqual(row['instrument_type'],'Spot metal quoted in USD')
    def test_netlify_existing_no_post(self):
        with patch.object(ns,'request',return_value=[{'name':'global-bollinger-eodhd','id':'test-id'}]) as request, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ns.setup('global-bollinger-eodhd','unused',True),'test-id')
            self.assertEqual(request.call_count,1)
    def test_netlify_empty_creation(self):
        results=[[],[{'slug':'test-team'}],{'name':'global-bollinger-eodhd','id':'test-id'}]
        with patch.object(ns,'request',side_effect=results) as request, contextlib.redirect_stdout(io.StringIO()):
            ns.setup('global-bollinger-eodhd','unused',True)
            self.assertEqual(request.call_args.args,('test-team/sites','unused',{'name':'global-bollinger-eodhd'}))
    def test_reviewed_mappings(self):
        for name,(symbol,provider_name,currency,isin) in b.REVIEWED_INDICES.items():
            asset=next(a for a in b.universe() if a['name']==name)
            row=dict(provider_symbol=symbol,Name=provider_name,Currency=currency,Type='INDEX',Isin=isin)
            self.assertEqual(b.resolve(asset,[row])['provider_symbol'],symbol)
            with self.assertRaises(b.DataError): b.resolve(asset,[dict(row,Currency='WRONG')])
    def test_stoxx_duplicate_names_resolved_by_identity(self):
        asset=next(a for a in b.universe() if a['name']=='EURO STOXX 50')
        row=dict(provider_symbol='STOXX50E.INDX',Name='Euro Stoxx 50',Currency='EUR',Type='INDEX',Isin='EU0009658145')
        self.assertEqual(b.resolve(asset,[row,dict(row,provider_symbol='SX5E.INDX')])['provider_symbol'],'STOXX50E.INDX')
    def test_explicit_mapping_preserved(self):
        asset=next(a for a in b.universe() if a['name']=='EURO STOXX 50')
        asset.update(provider_symbol='SX5E.INDX',provider_name='Euro Stoxx 50',instrument_type='Index')
        self.assertEqual(b.resolve(asset,[dict(provider_symbol='SX5E.INDX',Name='Euro Stoxx 50')])['provider_symbol'],'SX5E.INDX')

if __name__=='__main__': unittest.main()
