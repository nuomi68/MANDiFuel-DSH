import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry,atomic

class ProgressHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'tasks';self.registry=TaskRegistry(self.root);self.registry.process_monitor.close();p=self.registry.prepare('燃料棒任务');self.ident=p['task']['id'];self.work=Path(p['workspace']);self.job=self.registry._job(self.ident)
    def tearDown(self):self.registry.close();self.temp.cleanup()
    def event(self,action):self.registry.native_event(self.ident,{'kind':'tool','action':action})
    def files(self,progress=None):
        (self.work/'delivery').mkdir(exist_ok=True);(self.work/'delivery/report.txt').write_text('初版报告');manifest={'schema':'mandifuel.handoff/v1','files':['delivery/report.txt']}
        if progress:manifest['presentation']={'progress':{'summary':progress,'stages':[]}}
        atomic(self.work/'delivery/workbench.json',manifest);return manifest
    def test_history_and_heading_share_the_independent_process_source(self):
        from process_briefs import pending,publish
        self.registry.bind(self.ident,'science')
        self.event('正在生成网格');self.event('Read OFFBEAT source');self.registry.dashboard.publish(self.ident,{'parameters':[{'title':'几何','items':[]}],'progress':{'summary':'UI 不得覆盖'}});self.event('正在提取温度结果')
        item=pending(self.registry)[0]
        self.assertTrue(publish(self.registry,self.ident,{'key':item['key'],'topic':'检查温度场的提取方法'})['accepted'])
        rows=self.registry.progress(self.ident)['rows'];task=self.registry.snapshot(self.ident)['task']
        self.assertEqual(rows[-1]['summaryOrigin'],'llm');self.assertNotIn('正在提取温度结果',[r['summary'] for r in rows])
        self.assertEqual(rows[-1]['summary'],task['progress']['summary']);self.assertTrue(all(r['source']=='process-observer' for r in rows));self.assertNotIn('progress',task['presentation'])
    def test_summary_window_round_failure_and_terminal_fences(self):
        from process_briefs import pending,publish
        self.registry.bind(self.ident,'science')
        self.registry.native_event(self.ident,{'kind':'prompt','text':'只检查输入，不运行求解器'})
        self.registry.native_event(self.ident,{'kind':'status','status':'running'})
        for n in range(12):self.event('已完成物理求解 '+str(n))
        old=pending(self.registry)[0]
        self.assertEqual(len(old['window']['recent']),6)
        self.registry.native_event(self.ident,{'kind':'tool-end','tool':'bash','failed':True})
        self.assertIn('报错',self.registry.public(self.job)['progress']['summary'])
        data={'key':old['key'],'topic':'检查输入条件'}
        self.assertFalse(publish(self.registry,self.ident,data)['accepted'])
        current=pending(self.registry)[0]
        self.assertEqual(current['window']['recent'][-1]['kind'],'tool-error')
        self.registry.native_event(self.ident,{'kind':'turn','reason':'completed'})
        self.registry.native_event(self.ident,{'kind':'status','status':'idle'})
        self.assertFalse(publish(self.registry,self.ident,dict(data,key=current['key']))['accepted'])
        final=pending(self.registry)[0]
        self.assertTrue(publish(self.registry,self.ident,dict(data,key=final['key']))['accepted'])
        self.assertFalse(pending(self.registry))
        self.assertEqual(self.registry.public(self.job)['progress']['stages'],[])
        self.registry.native_event(self.ident,{'kind':'prompt','text':'新的要求'})
        self.assertFalse(publish(self.registry,self.ident,dict(data,key=final['key']))['accepted'])
        self.assertNotIn('检查输入条件',self.registry.public(self.job)['progress']['summary'])
    def test_subprocess_completion_is_recorded_without_ui_work(self):
        for status in ['running','completed']:self.registry.native_event(self.ident,{'kind':'subprocess','sessionId':'child','label':'材料校核','status':status})
        rows=self.registry.progress(self.ident)['rows'];self.assertEqual(rows[-2]['subprocesses'][0]['status'],'running');self.assertEqual(rows[-1]['subprocesses'][0]['status'],'completed');self.assertEqual(self.job['meta']['status'],'queued')
    def test_history_survives_restart(self):
        self.event('正在生成网格');self.registry.native_event(self.ident,{'kind':'status','status':'running'});self.registry.native_event(self.ident,{'kind':'turn','reason':'completed'});self.registry.native_event(self.ident,{'kind':'status','status':'idle'});before=self.registry.progress(self.ident);self.registry.close();restored=TaskRegistry(self.root)
        try:self.assertEqual(restored.progress(self.ident),before)
        finally:restored.close()
    def test_legacy_ui_history_is_not_presented_as_execution_evidence(self):
        meta=copy.deepcopy(self.job['meta']);meta['presentation']={'progress':{'summary':'伪进度'}};meta['progressHistory']=[{'id':1,'summary':'旧 UI 进度','stages':[]}];atomic(self.work.parent/'task.json',meta);self.registry.close();restored=TaskRegistry(self.root)
        try:
            self.assertEqual(restored.progress(self.ident)['rows'],[]);self.assertFalse(restored.progress(self.ident)['complete']);self.assertNotEqual(restored.snapshot(self.ident)['task']['progress']['summary'],'伪进度')
        finally:restored.close()
    def test_new_computation_resets_progress_but_a_display_request_does_not(self):
        self.registry.native_event(self.ident,{'kind':'prompt','text':'开始计算'});self.event('正在生成网格');before=self.registry.progress(self.ident);self.registry.native_event(self.ident,{'kind':'display-prompt','text':'修改颜色'});after=self.registry.progress(self.ident)
        self.assertEqual([r for r in after['rows'] if r['source']=='process-observer'],before['rows'])
        self.assertEqual(after['rows'][-1]['source'],'ui-renderer')
        self.registry.native_event(self.ident,{'kind':'prompt','text':'新的计算'});row=self.registry.progress(self.ident)['rows'][-1];self.assertEqual(row['summary'],'正在准备新请求');self.assertEqual(row['round'],2)
    def test_export_registration_cannot_change_workflow_progress(self):
        self.files('旧清单进度');self.event('正在提取物理场');before=self.registry.snapshot(self.ident)['task']['progress'];self.registry.dashboard.publish(self.ident,{'defaultView':'main','progress':{'summary':'UI 改写进度'}});self.assertEqual(self.registry.snapshot(self.ident)['task']['progress'],before)
    def test_file_and_controls_do_not_restore_legacy_ui_progress(self):
        manifest=self.files('清单进度');self.event('正在提取物理场');before=self.registry.snapshot(self.ident)['task']['progress'];count=len(self.registry.progress(self.ident)['rows']);self.registry._import(self.job);self.registry._save(self.job);manifest['presentation']['controls']=[];atomic(self.work/'delivery/workbench.json',manifest);self.registry._import(self.job);self.registry._save(self.job);self.assertEqual(self.registry.public(self.job)['progress'],before);self.assertEqual(len(self.registry.progress(self.ident)['rows']),count)
    def test_terminal_state_does_not_leave_preparing_as_current_progress(self):
        self.registry.native_event(self.ident,{'kind':'status','status':'running'});self.registry.native_event(self.ident,{'kind':'turn','reason':'completed'});self.registry.native_event(self.ident,{'kind':'status','status':'idle'});self.assertIn('结束',self.registry.public(self.job)['progress']['summary']);self.assertEqual(self.registry.progress(self.ident)['rows'][-1]['summary'],self.registry.public(self.job)['progress']['summary'])
    def test_delivery_version_changes_for_modified_content_with_same_name(self):
        self.files();self.registry._import(self.job);self.registry._save(self.job);before=self.registry.public(self.job)['deliveryVersion'];(self.work/'delivery/report.txt').write_text('第二版报告，名称不变');self.registry._import(self.job);self.registry._save(self.job);self.assertGreater(self.registry.public(self.job)['deliveryVersion'],before)
if __name__=='__main__':unittest.main()
