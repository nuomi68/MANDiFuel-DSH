import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry,atomic
from study import validate_study
from export_study import export_study,history_study

class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.registry=TaskRegistry(Path(self.temp.name)/'tasks');prepared=self.registry.prepare('燃料棒参数研究');self.ident=prepared['task']['id'];self.work=Path(prepared['workspace']);self.job=self.registry._job(self.ident)
    def tearDown(self):self.registry.close();self.temp.cleanup()
    def definition(self):return {'schema':'mandifuel.study/v1','kind':'scan','parameters':[{'id':'power','label':'线功率','unit':'W/m'}],'responses':[{'id':'maxT','label':'最高温度','unit':'K','goal':'min','bounds':{'max':700}}],'runs':[{'id':'a','status':'completed','parameters':{'power':10000},'responses':{'maxT':500}},{'id':'b','status':'completed','parameters':{'power':20000},'responses':{'maxT':900}}]}
    def model(self,ident,value):
        case=self.work/ident;case.mkdir();path=self.work/f'delivery/{ident}.json';path.parent.mkdir(exist_ok=True)
        atomic(path,{'schema':'mandifuel.viewer/v1','caseRoot':str(case),'task':{'shape':'mesh','radius':1,'cells':1,'fields':[{'id':'T','label':'温度','symbol':'T','unit':'K','range':[value-1,value+1]}]},'data':{'r':[0],'frames':[{'time':1,'mesh':'m','fields':{'T':[value]}}],'series':True,'meshes':{'m':{'points':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[0,1,2],'cells':[0]}}}})
        return {'id':ident,'label':'实际网格','viewer':str(path.relative_to(self.work))}
    def publish(self,study,views=()):
        export_study(self.work,'delivery/study.json',study,views);self.registry._import(self.job);self.registry._save(self.job);return self.registry.snapshot(self.ident)['task']
    def test_chart_only_study_is_valid_before_any_model(self):
        task=self.publish(self.definition());self.assertIsNone(task['importError']);self.assertFalse(task['modelReady']);self.assertEqual(task['study']['total'],2);self.assertNotIn('runs',task['study']);self.assertEqual(len(self.registry.study(self.ident)['runs']),2)
        with self.assertRaises(ValueError):self.registry.fields(self.ident)
    def test_two_parameter_groups_load_their_own_real_field_lazily(self):
        d=self.definition();views=[self.model('va',500),self.model('vb',900)]
        for row,view in zip(d['runs'],views):row.update(caseRoot=view['id'],viewIds=[view['id']])
        task=self.publish(d,views);self.assertTrue(task['resultReady']);self.assertIsNone(self.job['bundle']);self.assertTrue(all('bundle' not in v for v in self.job['views'].values()));self.assertEqual(self.registry.fields(self.ident,'va')['frames'][0]['fields']['T'],[500]);self.assertEqual(self.registry.fields(self.ident,'vb')['frames'][0]['fields']['T'],[900]);self.assertEqual(task['views'][0]['task']['fields'][0]['unit'],'K')
        self.registry.close();restored=TaskRegistry(self.registry.root)
        try:self.assertEqual(restored.fields(self.ident,'vb')['frames'][0]['fields']['T'],[900]);self.assertEqual(restored.study(self.ident)['runs'][0]['parameters']['power'],10000)
        finally:restored.close()
    def test_wrong_case_binding_keeps_previous_study_and_fields(self):
        d=self.definition();views=[self.model('va',500),self.model('vb',900)];d['runs'][0].update(caseRoot='va',viewIds=['va']);d['runs'][1].update(caseRoot='vb',viewIds=['vb']);self.publish(d,views);version=self.job['meta']['studyVersion'];d['runs'][0]['caseRoot']='vb';atomic(self.work/'delivery/study.json',d);self.registry._import(self.job)
        self.assertIn('目录不一致',self.job['meta']['importError']);self.assertEqual(self.job['meta']['studyVersion'],version);self.assertEqual(self.registry.fields(self.ident,'va')['frames'][0]['fields']['T'],[500])
    def test_view_cannot_be_silently_shared_by_different_parameter_groups(self):
        d=self.definition()
        for row in d['runs']:row['viewIds']=['raw']
        with self.assertRaisesRegex(ValueError,'唯一绑定'):validate_study(d,['raw'])
    def test_failed_solve_cannot_become_zero_response_or_result(self):
        d=self.definition();d['runs'][0]['status']='failed'
        with self.assertRaisesRegex(ValueError,'失败'):validate_study(d)
        d['runs'][0]['responses']={};self.assertEqual(validate_study(d)['runs'][0]['responses'],{})
    def test_missing_response_is_preserved_as_missing(self):
        d=self.definition();d['runs'][0]['responses']={};self.publish(d);self.assertNotIn('maxT',self.registry.study(self.ident)['runs'][0]['responses'])
    def test_only_response_change_preserves_view_revision(self):
        d=self.definition();d['runs'][0]['viewIds']=['va'];task=self.publish(d,[self.model('va',500)]);version=task['study']['version'];view_version=task['views'][0]['version'];d['runs'][1]['responses']['maxT']=850;task=self.publish(d)
        self.assertGreater(task['study']['version'],version);self.assertEqual(task['views'][0]['version'],view_version)
    def test_changed_model_is_not_served_under_old_parameter_binding(self):
        d=self.definition();d['runs'][0]['viewIds']=['va'];self.publish(d,[self.model('va',500)]);path=self.work/'delivery/va.json';bundle=json.loads(path.read_text());bundle['data']['frames'][0]['fields']['T']=[700];atomic(path,bundle)
        with self.assertRaisesRegex(ValueError,'尚未登记'):self.registry.fields(self.ident,'va')
    def test_presentation_observation_does_not_expand_a_thousand_runs(self):
        d=self.definition();d['runs'].extend({'id':f'plan-{i}','status':'queued','parameters':{'power':i+1},'responses':{}} for i in range(1000));self.publish(d);facts=self.registry.dashboard.inspect(self.ident)
        self.assertEqual(facts['study']['total'],1002);self.assertEqual(facts['cases'],[]);self.assertLess(len(json.dumps(facts)),12000);self.assertNotIn('runs',facts['study']);self.assertFalse((self.work/'STUDY_HANDOFF.md').exists())
    def test_invalid_plot_and_nonfinite_data_are_rejected(self):
        d=self.definition();d['charts']=[{'id':'plot','type':'response','x':'power','y':'unknown'}]
        with self.assertRaises(ValueError):validate_study(d)
        d.pop('charts');d['runs'][0]['responses']['maxT']=float('nan')
        with self.assertRaises(ValueError):validate_study(d)
    def test_history_adapter_uses_explicit_sources_and_retains_failure(self):
        d=self.definition();d.pop('runs');d['responses'][0]['source']='reporting_response.fuel_max';history=[{'point':{'id':'a','power':1},'status':'completed','reporting_response':{'fuel_max':600}},{'point':{'id':'旧失败输入','power':2},'status':'prepare_failed','response':99999,'error':'bad input'}];s=history_study(history,d)
        self.assertEqual(s['runs'][0]['responses']['maxT'],600);self.assertEqual(s['runs'][1]['responses'],{});self.assertEqual(s['runs'][1]['status'],'failed')
    def test_presentation_child_can_attach_existing_study_without_exporting_model(self):
        (self.work/'delivery').mkdir();atomic(self.work/'delivery/study.json',self.definition());result=self.registry.dashboard.publish(self.ident,{'study':'delivery/study.json'});self.assertIsNone(result['importError']);self.assertEqual(self.registry.snapshot(self.ident)['task']['study']['total'],2)
if __name__=='__main__':unittest.main()
