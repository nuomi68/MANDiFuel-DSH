from pathlib import Path
import copy
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry
from frontend_session import snapshot,apply
from slot_protocol import FrontendConflict


class FrontendSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.r=TaskRegistry(Path(self.temp.name)/'tasks');prepared=self.r.prepare('仅调整显示');self.ident=prepared['task']['id'];self.d=self.r.dashboard
        self.d.publish(self.ident,{'ui':{'version':1,'mode':'above','root':{'id':'mainRoot','type':'column','children':[{'id':'note','type':'text','text':'原始说明'},{'id':'tabs','type':'tabs','children':[{'id':'a','type':'text','text':'甲'},{'id':'b','type':'text','text':'乙'}]}]},'aside':{'id':'asideRoot','type':'column','children':[{'id':'other','type':'text','text':'辅助说明'}]}}})
    def tearDown(self):self.r.close();self.temp.cleanup()
    def transact(self,operations,**kwargs):return apply(self.d,self.ident,{'expectedRevision':snapshot(self.d,self.ident)['revision'],'operations':operations,**kwargs})
    def test_move_and_local_update_preserve_other_components_and_protect_the_shell(self):
        original=snapshot(self.d,self.ident,'main')['tree']
        self.transact([{'op':'move','slot':'main','id':'note','toSlot':'aside','parent':'asideRoot'},{'op':'update','slot':'aside','id':'note','props':{'text':'新的说明'}}])
        main=snapshot(self.d,self.ident,'main')['tree'];aside=snapshot(self.d,self.ident,'aside')['tree']
        self.assertEqual(main['children'],original['children'][1:]);self.assertEqual(aside['children'][1]['text'],'新的说明')
        with self.assertRaisesRegex(ValueError,'不可写'):self.transact([{'op':'replace','slot':'native-dsh','value':{}}])
        with self.assertRaisesRegex(ValueError,'自身'):self.transact([{'op':'move','slot':'main','id':'tabs','parent':'a'}])
    def test_invalid_node_or_duplicate_id_never_commits_the_transaction(self):
        before=snapshot(self.d,self.ident)
        for op in [{'op':'update','slot':'main','id':'note','props':{'innerHTML':'<script>bad</script>'}},{'op':'insert','slot':'main','parent':'mainRoot','value':{'id':'note','type':'text','text':'重复'}}]:
            with self.assertRaises(ValueError):self.transact([op])
            self.assertEqual(snapshot(self.d,self.ident)['revision'],before['revision'])
    def test_delivered_report_exposes_a_bounded_extraction_definition(self):
        job=self.r._job(self.ident);work=job['workspace']
        (work/'report.md').write_text('出口取保存场最大值。'+'温'*6500)
        (work/'private.md').write_text('未交付')
        job['meta']['files']=[{'path':'report.md'}]
        self.assertEqual(snapshot(self.d,self.ident,'data')['availableDocuments'],['report.md'])
        doc=snapshot(self.d,self.ident,'data','report.md')['document']
        self.assertTrue(doc['truncated']);self.assertEqual(len(doc['text']),6000)
        self.assertTrue(doc['text'].startswith('出口取保存场最大值'))
        with self.assertRaises(ValueError):snapshot(self.d,self.ident,'data','private.md')
    def test_model_parameters_and_registered_receipt_match_requested_view(self):
        import json
        from unittest.mock import patch
        job=self.r._job(self.ident);work=job['workspace']
        groups=[{'title':'共享','items':[]},{'title':'工况 A','caseRoot':'cases/a','items':[]}]
        self.d.publish(self.ident,{'parameters':groups})
        views=[]
        for name in ['a','b']:
            root='cases/'+name;views.append({'id':name,'caseRoot':root,'kind':'results'})
            path=work/root/'prepare.json';path.parent.mkdir(parents=True);path.write_text(json.dumps({'sample':name}))
            job['meta']['files'].append({'path':root+'/prepare.json','bytes':path.stat().st_size})
        public={**self.r.public(job),'views':views,'defaultView':'a'}
        with patch.object(self.r,'public',return_value=public):
            default=snapshot(self.d,self.ident,'model');other=snapshot(self.d,self.ident,'model','b')
            self.assertEqual(default['modelParameters'],groups)
            self.assertEqual(other['modelParameters'],groups[:1])
            self.assertEqual(json.loads(other['inputRecord']['text']),{'sample':'b'})
            self.assertEqual(other['inputRecord']['file'],'cases/b/prepare.json')
            with self.assertRaises(ValueError):snapshot(self.d,self.ident,'model','missing')
        for root in ['../b','/tmp/b','a/../b','']:
            with self.assertRaises(ValueError):self.d.publish(self.ident,{'parameters':[dict(groups[1],caseRoot=root)]})

    def test_operator_observes_field_statistics_of_the_requested_case_and_frame(self):
        from unittest.mock import patch
        job=self.r._job(self.ident)
        views=[{'id':name,'kind':'results'} for name in ['a','b']]
        public={**self.r.public(job),'views':views,'defaultView':'a'}
        job['meta']['viewerState']={'view':'a','time':1}
        def fields(ident,view):
            return {'frames':[{'time':1,'fields':{'T':[300,300]}},
                              {'time':10,'fields':{'T':[310,320] if view=='b' else [410,430]}}]}
        with patch.object(self.r,'public',return_value=public),patch.object(self.r,'fields',side_effect=fields):
            self.assertEqual(snapshot(self.d,self.ident,'model','a')['fieldFacts'],
                             [{'id':'T','time':1,'min':300,'max':300,'uniform':True}])
            self.assertEqual(snapshot(self.d,self.ident,'model','b')['fieldFacts'],
                             [{'id':'T','time':10,'min':310,'max':320,'uniform':False}])

    def test_operator_can_read_the_exact_registered_study_case_beyond_the_short_index(self):
        from unittest.mock import patch
        job=self.r._job(self.ident);public=self.r.public(job)
        roots=[f'cases/p{i:02d}' for i in range(1,26)]
        job['meta']['study']={'runs':[{'caseRoot':root} for root in roots]}
        case=job['workspace']/roots[-1];(case/'system').mkdir(parents=True)
        (case/'system/controlDict').touch();(case/'10').mkdir()
        (case/'10/strain').write_text('FoamFile {format ascii;class volSymmTensorField;object strain;} dimensions [0 0 0 0 0 0 0]; internalField uniform (0 0 0 0 0 0);')
        with patch.object(self.r,'public',return_value=public):
            result=snapshot(self.d,self.ident,'data','case:'+roots[-1])['cases'][0]
            self.assertEqual(result['caseRoot'],roots[-1])
            self.assertIn('strain:xx',result['fieldCatalog']['fields'][0]['selectors'])
            with self.assertRaisesRegex(ValueError,'没有这个算例'):snapshot(self.d,self.ident,'data','case:missing')

    def test_display_followup_preserves_the_latest_calculation_goal(self):
        self.r.native_event(self.ident,{'kind':'prompt','text':'比较三种工况'})
        self.r.native_event(self.ident,{'kind':'display-prompt','text':'把配色改为灰色'})
        task=self.d.inspect(self.ident)['task']
        self.assertEqual(task['request'],'比较三种工况')
        self.assertEqual(task['latestRequest'],'把配色改为灰色')
        self.assertTrue(task['displayOnly'])

    def test_task_index_only_signals_render_errors_for_the_current_revisions(self):
        job=self.r._job(self.ident);meta=job['meta']
        ui=meta['presentation']['uiRevision'];version=meta['presentationVersion']
        meta['uiState']={'revision':ui,'presentationVersion':version-1,'errors':[{'id':'a','message':'old'}]}
        meta['viewerState']={'rendererError':'old','revision':90}
        self.assertNotIn('renderIssue',self.r.public(job))
        meta['uiState']['presentationVersion']=version
        issue=self.r.public(job)['renderIssue'];self.assertTrue(issue)
        self.assertEqual(self.r.public(job)['renderIssue'],issue)
        meta['uiState']['errors']=[];self.assertNotIn('renderIssue',self.r.public(job))

    def test_bind_csv_and_add_one_result_panel_atomically(self):
        work=self.r._job(self.ident)['workspace']
        (work/'profiles.csv').write_text('radius,T\n1,300\n2,305\n')
        table={'id':'profile','type':'table','source':{'kind':'dataset','dataset':'temperatures'},'columns':['radius','T']}
        op={'op':'insert','slot':'aside','parent':'asideRoot','value':table}
        self.transact([op],datasets={'temperatures':{'file':'profiles.csv'}})
        before=snapshot(self.d,self.ident,'aside')
        self.assertEqual([node['id'] for node in before['tree']['children']],['other','profile'])
        self.assertEqual(before['documentOptions']['datasets']['temperatures']['file'],'profiles.csv')
        with self.assertRaises(ValueError):
            self.transact([dict(op,value=dict(table,id='broken',columns=['missing']))],datasets={'temperatures':{'file':'profiles.csv'}})
        self.assertEqual(snapshot(self.d,self.ident,'aside')['revision'],before['revision'])
    def test_manual_parameter_change_and_new_request_reject_stale_work(self):
        self.transact([{'op':'upsert','slot':'settings','value':{'id':'width','type':'number','label':'宽度','parameter':True,'min':1,'max':10,'default':2}}])
        stale=snapshot(self.d,self.ident)['revision'];self.d.parameter_values(self.ident,{'width':4})
        with self.assertRaises(FrontendConflict):apply(self.d,self.ident,{'expectedRevision':stale,'operations':[{'op':'update','slot':'main','id':'note','props':{'text':'过时'}}]})
        self.r.native_event(self.ident,{'kind':'display-prompt','text':'新的显示要求'})
        with self.assertRaisesRegex(FrontendConflict,'新的用户请求'):apply(self.d,self.ident,{'expectedRevision':snapshot(self.d,self.ident)['revision'],'expectedRequest':'仅调整显示','update':{'panelTitle':'过时'}})
        self.assertEqual(snapshot(self.d,self.ident,'settings')['values']['width'],4)
    def test_live_selection_receipt_is_scoped_and_not_replayed(self):
        from frontend_session import selection_check,selection_check_result
        rev=snapshot(self.d,self.ident)['revision']
        self.assertEqual(selection_check(self.r,self.ident,{'revision':rev}),{'status':'offline'})
        self.d.ui_state(self.ident,{'browserId':'browser-a','revision':snapshot(self.d,self.ident)['uiRevision']})
        job=self.r._job(self.ident);expected={'status':'verified','before':{'view':'a','time':2},'observed':{'view':'b','time':2},'restored':True}
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(selection_check,self.r,self.ident,{'revision':snapshot(self.d,self.ident)['revision']})
            with self.r.condition:
                self.assertTrue(self.r.condition.wait_for(lambda:'selectionCheck' in job,timeout=2))
                command=job['selectionCheck']['command']
                self.assertEqual(selection_check_result(self.r,self.ident,{**command,'browserId':'elsewhere','result':expected}),{'accepted':False})
                with self.assertRaises(ValueError):selection_check_result(self.r,self.ident,{**command,'result':{'status':'verified'}})
                self.assertTrue(selection_check_result(self.r,self.ident,{**command,'result':expected})['accepted'])
            self.assertEqual(future.result(timeout=2),expected)
        self.assertFalse(selection_check_result(self.r,self.ident,{**command,'result':expected})['accepted'])

    def test_interaction_commands_are_scoped_and_do_not_replace_the_ui_tree(self):
        before=snapshot(self.d,self.ident,'main')['tree'];version=snapshot(self.d,self.ident)['uiRevision']
        value=self.transact([{'op':'interact','slot':'main','id':'tabs','state':{'activeTab':'b'}}])
        self.assertEqual(value['uiRevision'],version);self.assertGreater(value['interactionRevision'],0);self.assertEqual(snapshot(self.d,self.ident,'main')['tree'],before)
        for state in [{'activeTab':'outside'},{'query':'search'}]:
            with self.assertRaises(ValueError):self.transact([{'op':'interact','slot':'main','id':'tabs','state':state}])
    def test_actual_browser_state_is_available_and_stale_observations_are_refused(self):
        page=snapshot(self.d,self.ident);observation={'revision':page['uiRevision'],'presentationVersion':page['presentationVersion'],'ready':True,'panels':['tabs'],'errors':[],'viewport':{'width':1200,'height':900},'nodes':[{'id':'tabs','type':'tabs','visible':True,'rect':{'x':0,'y':0,'width':600,'height':300},'activeTab':'b'}]}
        self.assertTrue(self.d.ui_state(self.ident,observation)['observed'])
        actual=snapshot(self.d,self.ident)['browser'];self.assertTrue(actual['connected']);self.assertEqual(actual['nodes'][0]['activeTab'],'b')
        observation['presentationVersion']-=1;self.assertFalse(self.d.ui_state(self.ident,observation)['observed'])
        observation['viewport']['width']=float('nan')
        with self.assertRaises(ValueError):self.d.ui_state(self.ident,observation)
    def test_user_tab_changes_invalidate_an_agent_snapshot_without_changing_configuration(self):
        page=snapshot(self.d,self.ident);old=page['revision']
        self.d.ui_state(self.ident,{'revision':page['uiRevision'],'presentationVersion':page['presentationVersion'],'panels':['tabs'],'errors':[],'nodes':[{'id':'tabs','type':'tabs','visible':True,'rect':{'x':0,'y':0,'width':100,'height':100},'activeTab':'b'}]})
        self.assertNotEqual(snapshot(self.d,self.ident)['revision'],old)
        with self.assertRaises(FrontendConflict):apply(self.d,self.ident,{'expectedRevision':old,'operations':[{'op':'interact','slot':'main','id':'tabs','state':{'activeTab':'a'}}]})


if __name__=='__main__':unittest.main()
