import sys,unittest,tempfile,types,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forecast import parse_csv,evaluate
from report import make_report
from timesfm_adapter import load as load_timesfm, backtest as backtest_timesfm
class ForecastTests(unittest.TestCase):
 def test_multi_series_missing_inspection(self):
  raw='t,id,v,c\n2024-01-01,a,-2,x\n2024-01-02,a,,y\n2024-01-03,a,0,z\n2024-01-01,b,2,x\n2024-01-02,b,3,y\n2024-01-03,b,4,z\n'
  h,g=parse_csv(raw,'t','v','id',['c']);self.assertEqual(len(g),2);self.assertEqual(g[0]['missing'],1);self.assertEqual(g[0]['rows_data'][0]['y'],-2)
 def test_duplicate_rejected(self):
  with self.assertRaisesRegex(ValueError,'duplicate timestamp'):
   parse_csv('t,v\n2024-01-01,1\n2024-01-01,2\n','t','v')
 def test_irregular_cadence_rejected(self):
  with self.assertRaisesRegex(ValueError,'stable cadence'):
   parse_csv('t,v\n2024-01-01,1\n2024-01-02,2\n2024-01-09,3\n','t','v')
 def test_missing_timestamp_slots_become_missing_values(self):
  raw='t,v\n2024-01-01,1\n2024-01-02,2\n2024-01-03,3\n2024-01-05,5\n'
  _,g=parse_csv(raw,'t','v');self.assertEqual(g[0]['gaps'],1);self.assertEqual(g[0]['missing'],1);self.assertEqual(g[0]['rows'],5)
 def test_folds_are_ordered_and_zero_scale_is_safe(self):
  r=evaluate([0.0]*40,2,1,3);self.assertEqual(r['fold_bounds'],[[0,34,36],[0,36,38],[0,38,40]]);self.assertIsNone(r['methods']['Last value']['mase']);self.assertIsNone(r['observed_coverage']);self.assertEqual(r['methods']['Last value']['mae'],0)
 def test_missing_holdout_excluded(self):
  vals=[float(i%4) for i in range(20)]+[None]+[float(i%4) for i in range(15)]
  r=evaluate(vals,2,4,3);self.assertLessEqual(r['methods']['Last value']['observations'],6)
 def test_negative_values_and_horizon_bound(self):
  r=evaluate([-4.,-3.,-2.,-1.]*10,2,4,3);self.assertTrue(r['forecast']);self.assertEqual(r['methods']['Last value']['observations'],6)
  with self.assertRaises(ValueError):evaluate([1]*100,61,1,3)
 def test_pdf_has_assumptions_and_long_name(self):
  r=evaluate([float(i%4) for i in range(40)],2,4,3)
  p={'winner':r['winner'],'horizon':2,'input_sha256':'f'*64,'series':[{'name':'North Division Weekly Demand with an unusually long planning label','rows':40,'start':'2024-01-01','end':'2024-02-09','cadence_label':'1.0 days','unit':'units','quality':{'duplicates':0,'gaps':0,'missing':1},'repair':'linear','methods':r['methods'],'forecast':r['forecast'],'history':[float(i%4) for i in range(40)],'interval_radius':None,'observed_coverage':None,'runtime_ms':1.1,'fold_bounds':r['fold_bounds']},{'name':'South series with long label','rows':40,'start':'2024-01-01','end':'2024-02-09','cadence_label':'1.0 days','unit':'units','quality':{'duplicates':0,'gaps':0,'missing':1},'repair':'linear','methods':r['methods'],'forecast':r['forecast'],'history':[float(i%4) for i in range(40)],'interval_radius':None,'observed_coverage':None,'runtime_ms':1.1,'fold_bounds':r['fold_bounds']}]}
  b=make_report(p);self.assertTrue(b.startswith(b'%PDF'));self.assertGreater(len(b),2000)
 def test_timesfm_missing_weights_refuses_before_import(self):
  with self.assertRaisesRegex(ValueError,'does not exist'):load_timesfm('/no/such/forecast-studio-checkpoint',40,2)
 def test_timesfm_adapter_contract_with_stub(self):
  class Arr(list):
   def tolist(self):return list(self)
  class Model:
   def __init__(self,**kw):pass
   def load_checkpoint(self,path,**kw):self.path=path
   def compile(self,c):self.config=c
   def forecast(self,horizon,inputs):return [[5.0]*horizon],[Arr([1.0,2.0,3.0])]
  class Config:
   def __init__(self,**kw):pass
  fake=types.ModuleType('timesfm');fake.TimesFM_2p5_200M_torch=Model;fake.ForecastConfig=Config
  np=types.ModuleType('numpy');np.float32='f32';np.asarray=lambda vals,dtype:vals
  from unittest.mock import patch
  from importlib import metadata
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'model.safetensors';path.write_bytes(b'stub weights')
   with patch.dict(sys.modules,{'timesfm':fake,'numpy':np}),patch.object(metadata,'version',return_value='2.0.2'):
    model,meta=load_timesfm(d,40,2)
   self.assertEqual(meta['checkpoint_sha256'],hashlib.sha256(b'stub weights').hexdigest());self.assertEqual(meta['package_version'],'2.0.2')
 def test_timesfm_backtest_uses_fold_prefix_and_quantile_channels(self):
  class QRows(list):
   def tolist(self):return [list(x) for x in self]
  class Model:
   def __init__(self):self.ends=[]
   def forecast(self,horizon,inputs):
    vals=inputs[0].tolist();self.ends.append(vals[-1]);point=[vals[-1]]*horizon
    rows=[[-1000.0,vals[-1]-1]+[vals[-1]-.75+i*.25 for i in range(7)]+[vals[-1]+1] for _ in range(horizon)]
    return [point],[QRows(rows)]
  from timesfm_adapter import backtest
  model=Model();values=[float(i) for i in range(40)];values[34]=None
  class Vector(list):
   def tolist(self):return list(self)
  fake_np=types.ModuleType('numpy');fake_np.float32='f32';fake_np.asarray=lambda vals,dtype:Vector(vals)
  from unittest.mock import patch
  with patch.dict(sys.modules,{'numpy':fake_np}): r=backtest(model,values,2,1,3,lambda v:[0.0 if x is None else x for x in v])
  self.assertEqual(model.ends[:3],[33.0,35.0,37.0]);self.assertEqual(model.ends[-1],39.0);self.assertEqual(r['fold_bounds'],[[0,34,36],[0,36,38],[0,38,40]]);self.assertEqual(r['observations'],5);self.assertIsNotNone(r['observed_coverage']);self.assertEqual(r['quantile_levels'][0],.1);self.assertEqual(r['quantiles'][0][0],38.0)
if __name__=='__main__':unittest.main()
