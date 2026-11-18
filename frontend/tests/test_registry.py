import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry,validate_bundle


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.registry=TaskRegistry(Path(self.temp.name)/'tasks');self.prepared=self.registry.prepare('原生任务\n求温度');self.ident=self.prepared['task']['id'];self.work=Path(self.prepared['workspace']);self.registry.bind(self.ident,'native-session-1')
    def tearDown(self):self.registry.close();self.temp.cleanup()
    def handoff(self,viewer=True):
        case=self.work/'case';(case/'system').mkdir(parents=True,exist_ok=True);(case/'system/controlDict').write_text('FoamFile {}');delivery=self.work/'delivery';delivery.mkdir(exist_ok=True)
        bundle={'schema':'mandifuel.viewer/v1','caseRoot':str(case),'task':{'title':'温度','shape':'mesh','radius':1,'innerRadius':0,'cells':1,'fields':[{'id':'T','unit':'K','label':'温度','range':[299,301]}]},'data':{'series':True,'r':[0],'frames':[{'time':1,'mesh':'m','fields':{'T':[300]}}],'meshes':{'m':{'points':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[0,1,2],'cells':[0]}}}}
        (delivery/'viewer.json').write_text(json.dumps(bundle));manifest={'schema':'mandifuel.handoff/v1','inputs':['case/system/controlDict']}
        if viewer:manifest['viewer']='delivery/viewer.json'
        (delivery/'workbench.json').write_text(json.dumps(manifest));return bundle
    def finish(self):
        self.registry.native_event(self.ident,{'kind':'status','status':'running'});self.registry.native_event(self.ident,{'kind':'turn','reason':'completed'});self.registry.native_event(self.ident,{'kind':'status','status':'idle'});return self.registry.snapshot(self.ident)
    def test_solver_workspace_has_no_ui_contract_or_frontend_instructions(self):
        instructions=(self.work/'AGENTS.md').read_text()+(self.work/'resources.md').read_text()
        for word in ['WORKBENCH','STUDY_HANDOFF','前端','展示子','生成式','delivery/']:self.assertNotIn(word,instructions)
    def test_state_versions_order_stream_and_snapshot_and_survive_reload(self):
        before=self.registry.snapshot(self.ident)['task']['stateVersion']
        running=self.registry.native_event(self.ident,{'kind':'status','status':'running'})
        done=self.finish();version=done['task']['stateVersion']
        self.assertGreater(running['task']['stateVersion'],before);self.assertGreater(version,running['task']['stateVersion'])
        self.assertEqual(self.registry.updates(self.ident,running['cursor'])[-1]['data']['stateVersion'],version)
        self.assertEqual(json.loads((self.work.parent/'task.json').read_text())['stateVersion'],version)
        self.registry.close();self.registry=TaskRegistry(Path(self.temp.name)/'tasks')
        self.assertGreaterEqual(self.registry.snapshot(self.ident)['task']['stateVersion'],version)
    def test_empty_observer_index_before_results_is_not_an_import_error(self):
        delivery=self.work/'delivery';delivery.mkdir(exist_ok=True)
        (delivery/'workspace-observation.json').write_text(json.dumps({'schema':'mandifuel.workspace-observation/v1','revision':1,'models':[],'inputs':[],'files':[]}))
        job=self.registry._job(self.ident);job['meta']['importError']='old error'
        self.registry._import(job)
        self.assertNotIn('importError',job['meta']);self.assertFalse(self.registry.public(job)['resultReady'])
        (delivery/'workbench.json').write_text(json.dumps({'schema':'mandifuel.handoff/v1'}))
        self.registry._import(job)
        self.assertIn('清单中没有模型或文件',job['meta']['importError'])
    def test_display_request_does_not_change_calculation_status_or_prompt(self):
        self.finish();job=self.registry._job(self.ident);before=json.loads(json.dumps(job['meta']))
        self.registry.native_event(self.ident,{'kind':'display-prompt','text':'把颜色改为灰色'})
        self.assertEqual(job['meta']['status'],'completed');self.assertEqual(job['meta']['prompt'],before['prompt'])
        self.assertEqual(job['meta'].get('promptRevision'),before.get('promptRevision'))
        self.assertEqual(job['meta']['presentation'].get('progress'),before.get('presentation',{}).get('progress'))
        self.assertEqual(job['meta']['presenter']['state'],'queued')
        self.assertEqual(job['meta']['latestDisplayPrompt'],'把颜色改为灰色')
        self.assertTrue(self.registry.dashboard.inspect(self.ident)['task']['displayOnly'])
        self.registry.native_event(self.ident,{'kind':'prompt','text':'修改真实材料后重算'})
        self.assertNotIn('latestDisplayPrompt',job['meta'])
        self.assertFalse((self.work/'WORKBENCH.md').exists());self.assertFalse((self.work/'STUDY_HANDOFF.md').exists())

    def test_native_completion_imports_real_mapping(self):
        self.handoff();s=self.finish();self.assertTrue(s['task']['resultReady']);self.assertEqual(s['task']['resultVersion'],1);self.assertEqual(len(s['inputs']),1)
    def test_followup_reuses_unchanged_result(self):
        self.handoff();self.finish();s=self.finish();self.assertEqual(s['task']['resultVersion'],1)
    def test_input_only_delivery_has_no_fake_model(self):
        self.handoff(viewer=False);s=self.finish();self.assertFalse(s['task']['resultReady']);self.assertEqual(len(s['inputs']),1);self.assertIsNone(s['task']['importError'])
    def test_invalid_delivery_keeps_previous_success(self):
        self.handoff();self.finish();(self.work/'delivery/workbench.json').write_text(json.dumps({'schema':'mandifuel.handoff/v1','viewer':'../../outside'}));s=self.finish();self.assertTrue(s['task']['resultReady']);self.assertEqual(s['task']['resultVersion'],1);self.assertIn('导入失败',s['task']['importError'])
    def test_file_access_stays_inside_manifest(self):
        self.handoff();self.finish();self.assertEqual(self.registry.file(self.ident,'case/system/controlDict').read_text(),'FoamFile {}')
        with self.assertRaises(ValueError):self.registry.file(self.ident,'../../outside')
    def test_metadata_preserves_native_session_after_restart(self):
        self.finish();self.registry.close();restored=TaskRegistry(self.registry.root)
        try:self.assertEqual(restored.snapshot(self.ident)['task']['nativeSessionId'],'native-session-1');self.assertNotIn('messages',restored.snapshot(self.ident))
        finally:restored.close()
    def test_native_title_sync_does_not_change_solver_state_or_prompt(self):
        before=self.registry.snapshot(self.ident)['task'];prompt=self.registry.jobs[self.ident]['meta']['prompt']
        self.registry.native_event(self.ident,{'kind':'title','title':'DSH 自动拟定的工程标题','sessionId':'native-session-1'})
        after=self.registry.snapshot(self.ident)['task'];self.assertEqual(after['title'],'DSH 自动拟定的工程标题');self.assertEqual(after['status'],before['status']);self.assertEqual(after['eventCount'],before['eventCount']);self.assertEqual(self.registry.jobs[self.ident]['meta']['prompt'],prompt)
        with self.assertRaisesRegex(ValueError,'不属于'):self.registry.native_event(self.ident,{'kind':'title','title':'other','sessionId':'unrelated'})
    def test_native_draft_accepts_first_direct_prompt(self):
        d=self.registry.draft();ident=d['task']['id'];self.assertTrue(d['task']['draft']);self.assertTrue((Path(d['workspace'])/'AGENTS.md').is_file())
        self.registry.native_event(ident,{'kind':'prompt','text':'计算燃料棒温度'})
        current=self.registry.snapshot(ident)['task'];self.assertFalse(current['draft']);self.assertEqual(current['title'],'计算燃料棒温度');self.assertNotIn('code',current)
    def test_new_draft_after_storage_move_uses_current_disk(self):
        old=self.registry.draft()['task']['id']
        root=self.registry.root
        self.registry.close()
        archive=Path(self.temp.name)/'archive'
        (root/old).rename(archive)
        (root/old).symlink_to(archive,target_is_directory=True)
        self.registry=TaskRegistry(root)
        self.assertTrue(self.registry.snapshot(old)['task']['draft'])
        current=self.registry.draft()
        self.assertNotEqual(current['task']['id'],old)
        self.assertTrue(Path(current['workspace']).resolve().is_relative_to(root))
        self.assertEqual(self.registry.draft()['task']['id'],current['task']['id'])
    def test_native_session_adopts_only_managed_workspace(self):
        self.assertEqual(self.registry.adopt(str(self.work),'another-native')['taskId'],self.ident)
        self.assertEqual(self.registry.adopt('/tmp','outside-native')['taskId'],None)
        self.assertIn('another-native',self.registry.snapshot(self.ident)['task']['nativeSessionIds'])
    def test_restart_does_not_retain_stale_live_sessions(self):
        self.registry.native_event(self.ident,{'kind':'status','status':'running','sessionId':'old'});self.registry.close();restored=TaskRegistry(self.registry.root)
        try:
            restored.native_event(self.ident,{'kind':'status','status':'running','sessionId':'new'});restored.native_event(self.ident,{'kind':'turn','reason':'completed'});restored.native_event(self.ident,{'kind':'status','status':'idle','sessionId':'new'})
            self.assertEqual(restored.snapshot(self.ident)['task']['status'],'completed')
        finally:restored.close()
    def test_native_failure_is_visible(self):
        self.registry.native_event(self.ident,{'kind':'failure','error':'原生接口错误'});s=self.registry.snapshot(self.ident);self.assertEqual(s['task']['status'],'failed');self.assertEqual(s['task']['error'],'原生接口错误')
    def test_invalid_mesh_cell_mapping_rejected(self):
        bundle=self.handoff();bundle['data']['meshes']['m']['cells']=[9]
        with self.assertRaises(ValueError):validate_bundle(bundle)

if __name__=='__main__':unittest.main()
