import json,sys,tempfile,unittest,shutil
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adaptive_ui import validate_ui,validate_ui_delivery
from agent_panel import validate_program
from frontend_observation import validate_observation
from slot_protocol import frontend_revision

def document(source):return {'version':1,'datasets':{'h':{'file':'history.json'}},'root':{'id':'history','type':'table','source':source}}

class LinkedSelectionTests(unittest.TestCase):
 def test_data_observation_indexes_files_and_opens_only_registered_metadata(self):
  from registry import TaskRegistry
  from frontend_session import snapshot
  with tempfile.TemporaryDirectory() as directory:
   registry=TaskRegistry(Path(directory))
   try:
    ident=registry.prepare('读取已有数据')['task']['id']
    facts={'cases':[],'views':[],'availableTables':[{'file':'history.json','columns':[{'id':'time','unit':'s'}],'rows':600,'sample':[{'time':0}],'categories':{}}],'availableRecords':[],'availableReports':[],'availableImages':[]}
    with patch.object(registry.dashboard,'inspect',return_value=facts):
     index=snapshot(registry.dashboard,ident,'data');self.assertNotIn('sample',index['availableTables'][0]);self.assertLess(len(json.dumps(index)),12000)
     details=snapshot(registry.dashboard,ident,'data','history.json');self.assertEqual(details['availableTables'][0]['sample'],[{'time':0}]);self.assertEqual(details['availableTables'][0]['columns'][0]['unit'],'s')
     with self.assertRaises(ValueError):snapshot(registry.dashboard,ident,'data','../unknown.json')
   finally:registry.close()
 def test_symmetric_exports_keep_original_sampling_coordinates_in_field_order(self):
  from export_case import export_case
  with tempfile.TemporaryDirectory() as directory:
   work=Path(directory);case=work/'case';shutil.copytree(Path(__file__).parent/'fixtures/radial-52',case)
   target=work/'viewer.json';export_case(case,target,selectors=['T'],shape='sphere',radius=.01,time_unit='s',write_handoff=False)
   data=json.loads(target.read_text())['data'];mesh=data['meshes'][data['frames'][0]['mesh']]
   self.assertEqual(len(mesh['cellCenters']),len(data['frames'][0]['fields']['T']))
   self.assertEqual(mesh['samplingGeometry'],'spherical');self.assertEqual(len(set(mesh['cellIds'])),len(data['r']))
   for r,p in zip(data['r'],mesh['cellCenters']):self.assertAlmostEqual(r,sum(v*v for v in p)**.5)
 def test_declared_target_columns_and_units_are_checked_before_publication(self):
  with tempfile.TemporaryDirectory() as directory:
   work=Path(directory);(work/'history.json').write_text(json.dumps({'columns':['view','time','value'],'rows':[{'view':'a','time':10,'value':.5}]}))
   source={'kind':'dataset','dataset':'h','selection':{'viewColumn':'view','timeColumn':'time','timeUnit':'s'},'filter':[{'column':'view','op':'eq','context':'view'}]}
   ui=validate_ui(document(source));views={'a':{'task':{'timeUnit':'s','savedTimes':[10]}}};validate_ui_delivery(ui,views,'a',[],work)
   with self.assertRaisesRegex(ValueError,'单位'):validate_ui_delivery(ui,{'a':{'task':{'timeUnit':'d'}}},'a',[],work)
   with self.assertRaisesRegex(ValueError,'视图'):validate_ui_delivery(ui,{},None,[],work)
   source['selection']['timeColumn']='missing'
   with self.assertRaisesRegex(ValueError,'数据列'):validate_ui_delivery(validate_ui(document(source)),views,'a',[],work)
 def test_unbounded_bindings_and_missing_units_are_rejected(self):
  for binding in [{'timeColumn':'t'},{'view':'a','viewColumn':'id'},{'positionColumns':['x','y']},{'execute':'javascript'}]:
   with self.assertRaises(ValueError):validate_ui(document({'kind':'dataset','dataset':'h','selection':binding}))
 def test_circle_is_a_data_primitive_with_real_parameter_dependencies(self):
  validate_program({'annotations':[{'id':'layer','type':'circle','views':['a'],'position':['0','0','0'],'radius':'p.radius','axis':'y'}]})
  with self.assertRaises(ValueError):validate_program({'annotations':[{'id':'layer','type':'circle','position':['0','0','0'],'radius':'1','axis':'unknown'}]})
 def test_symmetric_annotations_require_real_sampling_data_for_probes(self):
  from presentation import validate_delivery
  views={'a':{'task':{'shape':'sphere','supportsExtrema':True,'fields':[{'id':'Cs'}]}}}
  program=validate_program({'annotations':[{'id':'layer','type':'circle','views':['a'],'position':['0','0','0'],'radius':'0.00025'},{'id':'sample','type':'probe','position':['0.0002','0','0'],'field':'Cs'}]})
  config={'rendering':{'program':program}};validate_delivery(config,views,'a')
  views['a']['task']['supportsExtrema']=False
  with self.assertRaisesRegex(ValueError,'原始单元中心'):validate_delivery(config,views,'a')
 def test_picked_position_is_bounded_and_invalidates_stale_agent_transactions(self):
  pick={'position':[.0002,0,0],'view':'a','time':10,'timeUnit':'s','field':'Cs'};validate_observation({'pickedPoint':pick})
  self.assertNotEqual(frontend_revision({}),frontend_revision({'uiState':{'pickedPoint':pick}}))
  with self.assertRaises(ValueError):validate_observation({'pickedPoint':{**pick,'position':[1,2]}})

if __name__=='__main__':unittest.main()
