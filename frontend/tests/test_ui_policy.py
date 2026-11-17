import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ui_policy import clean_document
from registry import TaskRegistry
from frontend_session import snapshot,apply

class UIPolicyTests(unittest.TestCase):
    def test_scalar_cards_and_exact_duplicate_windows_are_removed_across_slots(self):
        note={'id':'note','type':'text','text':'结果来源与对照说明'}
        ui={'version':1,'root':{'id':'root','type':'column','children':[{'id':'value','type':'metric','source':{'kind':'history','field':'T'}},note]},'aside':{'id':'copy','type':'column','children':[{**note,'id':'duplicate','title':'另一标题'}]}}
        value,removed=clean_document(ui);self.assertEqual(value['root']['children'],[note]);self.assertNotIn('aside',value);self.assertIn('value',removed);self.assertIn('duplicate',removed);self.assertEqual(len(ui['root']['children']),2)
    def test_different_data_or_display_semantics_are_preserved(self):
        chart={'id':'a','type':'chart','series':[{'source':{'kind':'dataset','dataset':'data'},'x':'time','y':'stress'}]}
        other={**chart,'id':'b','series':[{'source':{'kind':'dataset','dataset':'data'},'x':'time','y':'temperature'}]}
        ui={'version':1,'root':{'id':'root','type':'tabs','children':[chart,other]}};self.assertEqual(clean_document(ui),(ui,[]))
    def test_an_all_scalar_layout_restores_native_model_instead_of_an_empty_window(self):
        self.assertIsNone(clean_document({'version':1,'root':{'id':'value','type':'metric'}})[0])
        for value in ['300','2.5 µm','-1.2e8 Pa']:
            self.assertIsNone(clean_document({'version':1,'root':{'id':'value','type':'text','text':value}})[0])
    def test_current_page_state_is_exposed_and_ui_progress_is_not_writable(self):
        with tempfile.TemporaryDirectory() as folder:
            r=TaskRegistry(Path(folder)/'tasks')
            try:
                ident=r.prepare('测试当前页面')['task']['id'];d=r.dashboard
                d.publish(ident,{'ui':{'version':1,'root':{'id':'one','type':'text','text':'当前结论'}}})
                page=snapshot(d,ident);self.assertEqual(page['composition']['main']['text'],'当前结论');self.assertTrue(page['composition']['main']['contentKey']);self.assertFalse(page['policy']['scalarCards'])
                with self.assertRaisesRegex(ValueError,'process-observer'):apply(d,ident,{'expectedRevision':page['revision'],'update':{'progress':{'summary':'伪造进度'}}})
                d.publish(ident,{'ui':{'version':1,'root':{'id':'n','type':'metric','source':{'kind':'history','field':'missing'}}}})
                self.assertIsNone(r.snapshot(ident)['task']['presentation']['ui'])
            finally:r.close()
