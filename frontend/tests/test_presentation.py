import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry,atomic
from presentation import validate_presentation
from export_case import export_mesh

SOURCE=Path(__file__).resolve().parent/'fixtures/radial-52'

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.registry=TaskRegistry(Path(self.temp.name)/'tasks');self.prepared=self.registry.prepare('展示交付');self.ident=self.prepared['task']['id'];self.work=Path(self.prepared['workspace'])
        for name in ['0','constant','system']:shutil.copytree(SOURCE/name,self.work/'case'/name)
    def tearDown(self):self.registry.close();self.temp.cleanup()
    def test_view_observations_are_bound_to_the_current_instruction_revision(self):
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'mesh'}],'viewState':{'cameraView':'xy'}})
        revision=self.registry.snapshot(self.ident)['task']['presentation']['viewStateRevision']
        self.assertFalse(self.registry.dashboard.viewer_state(self.ident,{'view':'raw','cameraView':'3d','revision':revision-1})['observed'])
        self.assertTrue(self.registry.dashboard.viewer_state(self.ident,{'view':'raw','cameraView':'xy','revision':revision})['observed'])
        self.assertEqual(self.registry.dashboard.inspect(self.ident)['viewerState']['cameraView'],'xy')
    def test_mesh_without_results_has_no_fabricated_fields(self):
        export_mesh(self.work/'case',self.work/'delivery/mesh.json');self.registry._import(self.registry._job(self.ident));task=self.registry.snapshot(self.ident)['task']
        self.assertTrue(task['previewReady']);self.assertFalse(task['resultReady']);self.assertEqual(task['fields'],[]);self.assertNotIn('frames',self.registry.fields(self.ident))
    def test_live_import_does_not_wait_for_native_turn_end(self):
        self.registry.native_event(self.ident,{'kind':'status','status':'running'})
        export_mesh(self.work/'case',self.work/'delivery/mesh.json')
        end=time.monotonic()+4
        while time.monotonic()<end and not self.registry.snapshot(self.ident)['task']['modelReady']:time.sleep(.05)
        task=self.registry.snapshot(self.ident)['task'];self.assertTrue(task['modelReady']);self.assertEqual(task['status'],'running')
    def test_saved_output_preview_progresses_independently_and_retries_incomplete_saves(self):
        dashboard=self.registry.dashboard;dashboard.stop.set();dashboard.thread.join()
        with self.registry.lock:
            meta=self.registry._job(self.ident)['meta'];meta['status']='running';meta['presenter']={'state':'running'}
        dashboard.preview(self.ident)
        self.assertTrue(self.registry.snapshot(self.ident)['task']['previewReady'])
        shutil.copytree(SOURCE/'1',self.work/'case/1');dashboard.preview(self.ident)
        first=self.registry.snapshot(self.ident)['task'];self.assertTrue(first['resultReady']);self.assertEqual(first['defaultView'],'live-results')
        shutil.copytree(SOURCE/'1',self.work/'case/2');field=self.work/'case/2/T';valid=field.read_text();field.write_text('unfinished save')
        with self.assertRaises(ValueError):dashboard.preview(self.ident)
        self.assertEqual(self.registry.snapshot(self.ident)['task']['modelVersion'],first['modelVersion'])
        field.write_text(valid);dashboard.preview(self.ident)
        self.assertGreater(self.registry.snapshot(self.ident)['task']['modelVersion'],first['modelVersion'])
        self.assertEqual(self.registry.fields(self.ident)['frames'][-1]['time'],2)
        self.assertEqual(self.registry.snapshot(self.ident)['task']['status'],'running')
    def test_automatic_preview_preserves_explicit_models_and_does_not_guess_multi_case_ownership(self):
        dashboard=self.registry.dashboard;dashboard.stop.set();dashboard.thread.join()
        with self.registry.lock:self.registry._job(self.ident)['meta']['status']='running'
        shutil.copytree(self.work/'case',self.work/'second-case');dashboard.preview(self.ident)
        self.assertFalse(self.registry.snapshot(self.ident)['task']['modelReady'])
        shutil.rmtree(self.work/'second-case');dashboard.publish(self.ident,{'exports':[{'id':'user-view','caseRoot':'case','kind':'mesh'}]})
        shutil.copytree(SOURCE/'1',self.work/'case/1');before=self.registry.snapshot(self.ident)['task'];dashboard.preview(self.ident)
        self.assertEqual(self.registry.snapshot(self.ident)['task']['modelVersion'],before['modelVersion'])
    def test_uniform_field_facts_and_verified_days_do_not_use_expanded_color_range_as_data(self):
        shutil.copytree(SOURCE/'1',self.work/'case/1');field=self.work/'case/1/T'
        content=field.read_text();start=content.index('internalField');end=content.index('boundaryField',start);field.write_text(content[:start]+'internalField uniform 650;\n\n'+content[end:])
        control=self.work/'case/system/controlDict';control.write_text(control.read_text().replace('type seconds;','type days;'))
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'results','fields':['T']}]})
        task=self.registry.snapshot(self.ident)['task'];variable=task['fields'][0]
        self.assertEqual(variable['dataRange'],[650,650]);self.assertGreater(variable['range'][1],650)
        self.assertEqual(task['views'][0]['task']['timeUnit'],'d')
        observed=self.registry.dashboard.inspect(self.ident)['fieldFacts'][0]
        self.assertEqual(observed,{'id':'T','time':1.0,'min':650,'max':650,'uniform':True})
    def test_parameters_and_controls_can_be_replaced(self):
        self.registry.dashboard.publish(self.ident,{'parameters':[{'title':'材料','items':[{'label':'任意模型参数','value':'8','unit':'Pa'}]}],'controls':[{'id':'mesh','label':'显示计算单元','default':True}]})
        self.registry.dashboard.publish(self.ident,{'parameters':[{'title':'边界','items':[{'label':'新边界','value':'610','unit':'K'}]}],'controls':[]})
        config=self.registry.snapshot(self.ident)['task']['presentation'];self.assertEqual(config['controls'],[]);self.assertEqual(config['parameters'][0]['items'][0]['label'],'新边界')
    def test_view_exports_preserve_mesh_and_real_results(self):
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'mesh','caseRoot':'case','kind':'mesh'}]})
        shutil.copytree(SOURCE/'1',self.work/'case/1')
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'rod','caseRoot':'case','kind':'results','fields':['T'],'shape':'rod','radius':.00485,'length':.12}],'defaultView':'rod'})
        task=self.registry.snapshot(self.ident)['task'];self.assertTrue(task['resultReady']);self.assertEqual(len(task['views']),2);self.assertEqual(self.registry.fields(self.ident,'mesh')['kind'],'mesh');self.assertEqual(max(self.registry.fields(self.ident,'rod')['frames'][0]['fields']['T']),1156.7)
    def test_initial_conditions_cannot_be_exported_as_solved_results(self):
        with self.assertRaisesRegex(ValueError,'尚无'):self.registry.dashboard.publish(self.ident,{'exports':[{'id':'results','caseRoot':'case','kind':'results','fields':['T']}]})
    def test_paths_must_stay_in_workspace(self):
        with self.assertRaisesRegex(ValueError,'本任务工作区'):self.registry.dashboard.publish(self.ident,{'exports':[{'id':'external','caseRoot':str(SOURCE),'kind':'mesh'}]})
    def test_invalid_live_delivery_keeps_valid_mesh(self):
        export_mesh(self.work/'case',self.work/'delivery/mesh.json');job=self.registry._job(self.ident);self.registry._import(job);version=job['meta']['modelVersion'];atomic(self.work/'delivery/workbench.json',{'schema':'mandifuel.handoff/v1','viewer':'missing.json'});self.registry._import(job)
        self.assertEqual(job['meta']['modelVersion'],version);self.assertTrue(self.registry.snapshot(self.ident)['task']['previewReady'])
    def test_observation_revision_does_not_loop_on_own_presentation(self):
        before=self.registry.dashboard.inspect(self.ident)['revision'];self.registry.dashboard.publish(self.ident,{'progress':{'summary':'正在生成网格'},'exports':[{'id':'mesh','caseRoot':'case','kind':'mesh'}]});after=self.registry.dashboard.inspect(self.ident)['revision'];self.assertEqual(before,after)
    def test_unknown_controls_are_rejected(self):
        with self.assertRaises(ValueError):validate_presentation({'controls':[{'id':'executeScript','label':'执行代码'}]})
    def test_default_view_can_change_without_exporting_again(self):
        shutil.copytree(SOURCE/'1',self.work/'case/1')
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'mesh','caseRoot':'case','kind':'mesh'},{'id':'raw','caseRoot':'case','kind':'results','fields':['T']}],'defaultView':'raw'})
        self.registry.dashboard.publish(self.ident,{'defaultView':'mesh'})
        self.assertEqual(self.registry.snapshot(self.ident)['task']['defaultView'],'mesh');self.assertTrue(self.registry.snapshot(self.ident)['task']['previewReady'])
    def test_followup_is_visible_to_presentation_child(self):
        before=self.registry.dashboard.inspect(self.ident)['revision'];self.registry.native_event(self.ident,{'kind':'prompt','text':'请更换显示选项'})
        facts=self.registry.dashboard.inspect(self.ident);self.assertNotEqual(before,facts['revision']);self.assertEqual(facts['task']['latestRequest'],'请更换显示选项')
    def test_bad_reconstruction_does_not_replace_good_view(self):
        shutil.copytree(SOURCE/'1',self.work/'case/1')
        spec={'id':'rod','caseRoot':'case','kind':'results','fields':['T'],'shape':'rod','radius':.00485,'length':.12}
        self.registry.dashboard.publish(self.ident,{'exports':[spec]});version=self.registry.snapshot(self.ident)['task']['modelVersion']
        bad=dict(spec,radius=.0041,radialBands=[[0,.0041,40],[.0041,.00425,0],[.00425,.00485,12]])
        with self.assertRaises(ValueError):self.registry.dashboard.publish(self.ident,{'exports':[bad]})
        self.registry._import(self.registry._job(self.ident));task=self.registry.snapshot(self.ident)['task'];self.assertEqual(task['modelVersion'],version);self.assertTrue(task['resultReady'])
    def test_display_error_does_not_block_valid_result_model(self):
        shutil.copytree(SOURCE/'1',self.work/'case/1')
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'results','fields':['T']}]})
        path=self.work/'delivery/workbench.json';manifest=json.loads(path.read_text());manifest['presentation']={'controls':[{'id':'unknown-renderer'}]};atomic(path,manifest);self.registry._import(self.registry._job(self.ident))
        task=self.registry.snapshot(self.ident)['task'];self.assertTrue(task['resultReady']);self.assertIsNone(task['importError']);self.assertIn('显示配置',task['presentationError'])
    def test_report_changes_do_not_advance_model_version(self):
        shutil.copytree(SOURCE/'1',self.work/'case/1');self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'results','fields':['T']}]});before=self.registry.snapshot(self.ident)['task'];path=self.work/'delivery/report.txt';path.write_text('第一版');manifest_path=self.work/'delivery/workbench.json';manifest=json.loads(manifest_path.read_text());manifest['files']=['delivery/report.txt'];atomic(manifest_path,manifest);job=self.registry._job(self.ident);self.registry._import(job);self.registry._save(job);path.write_text('第二版，只有报告变化');self.registry._import(job);self.registry._save(job);after=self.registry.snapshot(self.ident)['task'];self.assertEqual(before['modelVersion'],after['modelVersion']);self.assertEqual(before['views'][0]['version'],after['views'][0]['version']);self.assertGreater(after['deliveryVersion'],before['deliveryVersion'])
    def test_live_file_only_update_is_emitted_and_saved(self):
        (self.work/'delivery').mkdir();path=self.work/'delivery/report.txt';path.write_text('第一版');atomic(self.work/'delivery/workbench.json',{'schema':'mandifuel.handoff/v1','files':['delivery/report.txt']});self.registry.native_event(self.ident,{'kind':'status','status':'running'});end=time.monotonic()+4
        while time.monotonic()<end and not self.registry.snapshot(self.ident)['files']:time.sleep(.05)
        before=self.registry.snapshot(self.ident);path.write_text('第二版报告，文件名不变');end=time.monotonic()+4
        while time.monotonic()<end and self.registry.snapshot(self.ident)['task']['deliveryVersion']==before['task']['deliveryVersion']:time.sleep(.05)
        after=self.registry.snapshot(self.ident);self.assertGreater(after['task']['deliveryVersion'],before['task']['deliveryVersion']);self.assertGreater(after['cursor'],before['cursor']);self.assertEqual(json.loads((self.work.parent/'task.json').read_text())['deliveryVersion'],after['task']['deliveryVersion'])
    def test_restart_preserves_views_and_task_configuration(self):
        self.registry.dashboard.publish(self.ident,{'parameters':[{'title':'尺寸','items':[{'label':'长度','value':'120','unit':'mm'}]}],'exports':[{'id':'mesh','caseRoot':'case','kind':'mesh'}]});self.registry.close();restored=TaskRegistry(self.registry.root)
        try:self.assertTrue(restored.snapshot(self.ident)['task']['previewReady']);self.assertEqual(restored.snapshot(self.ident)['task']['presentation']['parameters'][0]['title'],'尺寸')
        finally:restored.close()

    def test_stopped_task_receives_new_display_without_restarting_agent(self):
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'mesh','caseRoot':'case','kind':'mesh'}]})
        with self.registry.lock:self.registry._job(self.ident)['meta']['status']='stopped'
        path=self.work/'delivery/workbench.json';manifest=json.loads(path.read_text());manifest['presentation']={'parameters':[{'title':'重新整理展示','items':[]}]};atomic(path,manifest)
        end=time.monotonic()+4
        while time.monotonic()<end and self.registry.snapshot(self.ident)['task']['presentation'].get('parameters',[])!=manifest['presentation']['parameters']:time.sleep(.05)
        task=self.registry.snapshot(self.ident)['task'];self.assertEqual(task['status'],'stopped');self.assertEqual(task['presentation']['parameters'],manifest['presentation']['parameters'])

    def test_successive_rendering_updates_reuse_the_same_result_model(self):
        shutil.copytree(SOURCE/'1',self.work/'case/1')
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'results','fields':['T']}]})
        before=self.registry.snapshot(self.ident)['task'];fields=self.registry.fields(self.ident)
        self.registry.dashboard.publish(self.ident,{'rendering':{'scale':[2,.5,1]}})
        self.registry.dashboard.publish(self.ident,{'rendering':{'palette':'viridis','fields':{'T':{'range':[300,800]}}}})
        after=self.registry.snapshot(self.ident)['task'];style=after['presentation']['rendering']
        self.assertEqual(style['scale'],[2,.5,1]);self.assertEqual(style['palette'],'viridis');self.assertEqual(after['modelVersion'],before['modelVersion']);self.assertEqual(self.registry.fields(self.ident),fields)
        with self.assertRaisesRegex(ValueError,'变量'):self.registry.dashboard.publish(self.ident,{'rendering':{'fields':{'absent':{'palette':'inferno'}}}})
        self.assertEqual(self.registry.snapshot(self.ident)['task']['presentation']['rendering'],style)
        self.registry.dashboard.publish(self.ident,{'rendering':{'reset':True}});revision=self.registry.snapshot(self.ident)['task']['presentation']['renderingRevision']
        self.registry.dashboard.publish(self.ident,{'rendering':{'reset':True}})
        self.assertGreater(self.registry.snapshot(self.ident)['task']['presentation']['renderingRevision'],revision)

    def test_browser_observations_do_not_trigger_presentation_loops_or_model_changes(self):
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'mesh'}]})
        before=self.registry.snapshot(self.ident)['task'];revision=self.registry.dashboard.inspect(self.ident)['revision']
        self.registry.dashboard.viewer_state(self.ident,{'view':'raw','cameraView':'3d','camera':{'yaw':1.2,'zoom':2},'rendererError':''})
        facts=self.registry.dashboard.inspect(self.ident)
        self.assertEqual(facts['viewerState']['camera']['yaw'],1.2);self.assertEqual(facts['revision'],revision)
        self.assertEqual(self.registry.snapshot(self.ident)['task']['modelVersion'],before['modelVersion'])
        self.registry.dashboard.publish(self.ident,{'viewState':{'cameraView':'3d','yaw':90}})
        first=self.registry.snapshot(self.ident)['task']['presentation']['viewStateRevision']
        self.registry.dashboard.publish(self.ident,{'panelDescription':'只调整说明'})
        self.assertEqual(self.registry.snapshot(self.ident)['task']['presentation']['viewStateRevision'],first)
        self.registry.dashboard.publish(self.ident,{'viewState':{'cameraView':'3d','yaw':90}})
        self.assertGreater(self.registry.snapshot(self.ident)['task']['presentation']['viewStateRevision'],first)
        with self.assertRaises(ValueError):self.registry.dashboard.viewer_state(self.ident,{'view':'missing'})

    def test_agent_panel_values_are_observable_and_file_updates_preserve_edits(self):
        self.registry.dashboard.publish(self.ident,{'exports':[{'id':'raw','caseRoot':'case','kind':'mesh'}]})
        before=self.registry.snapshot(self.ident)['task'];controls=[{'id':'userWidth','type':'number','label':'自定义宽度系数','default':2,'min':.1,'max':5}]
        update={'panelTitle':'用户要求的尺寸','controls':controls,'rendering':{'program':{'vertex':['x*p.userWidth','y','z']}}}
        self.registry.dashboard.publish(self.ident,update);self.registry.dashboard.parameter_values(self.ident,{'userWidth':4})
        self.assertEqual(self.registry.dashboard.inspect(self.ident)['presentation']['parameterValues']['userWidth'],4)
        self.assertEqual(self.registry.snapshot(self.ident)['task']['modelVersion'],before['modelVersion'])
        with self.assertRaises(ValueError):self.registry.dashboard.parameter_values(self.ident,{'userWidth':0})
        path=self.work/'delivery/workbench.json';manifest=json.loads(path.read_text());manifest['presentation']={**update,'parameterValues':{'userWidth':4}};atomic(path,manifest);job=self.registry._job(self.ident);self.registry._import(job)
        self.registry.dashboard.parameter_values(self.ident,{'userWidth':3})
        report=self.work/'delivery/report.txt';report.write_text('不改变参数的报告更新');manifest['files']=['delivery/report.txt'];atomic(path,manifest);self.registry._import(job)
        self.assertEqual(self.registry.dashboard.inspect(self.ident)['presentation']['parameterValues']['userWidth'],3)

if __name__=='__main__':unittest.main()
