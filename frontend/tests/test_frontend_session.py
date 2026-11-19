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
