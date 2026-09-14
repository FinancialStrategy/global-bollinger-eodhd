"""Synthetic fixtures only for unit tests, never used as market-data fallback."""
import unittest
import tempfile, contextlib, io, json, zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import bb_eodhd as b

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
        with tempfile.TemporaryDirectory() as temp, patch.object(b,'ROOT',Path(temp)), patch.object(b,'catalog',return_value=[]), patch.object(b,'resolve',side_effect=resolved), patch.object(b,'fetch',return_value=(d,0)), contextlib.redirect_stdout(io.StringIO()):
            b.build('UNIT_TEST_SECRET')
            with zipfile.ZipFile(Path(temp)/'netlify_site.zip') as z:
                self.assertIn('index.html',z.namelist())
                self.assertIn('A01.html',z.namelist())
                self.assertEqual(len(json.loads(z.read('audit.json'))),47)
                for name in z.namelist(): self.assertNotIn(b'UNIT_TEST_SECRET',z.read(name))
                self.assertIn('OOS simulated equity',z.read('A01.html').decode())

if __name__=='__main__': unittest.main()
