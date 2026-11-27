"""Regression checks for quantities that share a label, but have different physical support."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adaptive_ui import exact_dataset_frames
from agent_panel import validate_program
from process_monitor import process_progress
from registry import current_render_step
from scientific_samples import channel_rows


class PhysicalIdentityTests(unittest.TestCase):
    def test_time_case_and_reference_inventory_are_independent_conditions(self):
        views = {'s2': {'caseRoot':'cases/s2', 'task':{'savedTimes':[360000], 'fields':[{'id':'Cs'}]}}}
        table = {'columns':[{'id':k} for k in ('viewId','t','fraction_field')],
                 'rows':[{'viewId':'s2','t':360000,'fraction_field':.468334}]}
        binding = {'selection':{'viewColumn':'viewId','timeColumn':'t','timeUnit':'s'}}
        def check():
            exact_dataset_frames(table,binding,views,'s2',{'file':'curves.csv'},Path.cwd())
        native={'rows':[{'time':360000,'fraction':.46702946316949}]}
        with patch('scientific_samples.inventory_rows',return_value=native):
            with self.assertRaisesRegex(ValueError,'原场积分'):check()
            row=table['rows'][0]
            row['fraction_field']=.4670295
            check()
            row['caseRoot']='cases/s2-finer'
            with self.assertRaisesRegex(ValueError,'目录'):check()
            row.pop('caseRoot')
            row['t']=360001
            with self.assertRaisesRegex(ValueError,'保存帧'):check()

    def test_missing_outlet_face_leaves_gap_and_retains_delivered_value(self):
        table={'columns':[{'id':'wall_outlet_T_K'}], 'rows':[{'wall_outlet_T_K':869.970}]}
        result=channel_rows(Path.cwd(),{},table,[])
        self.assertIsNone(result['rows'][0]['wall_outlet_T_K'])
        self.assertEqual(result['outletAudit'][0]['delivered'],869.970)
        self.assertEqual(table['rows'][0]['wall_outlet_T_K'],869.970)

    def test_claim_of_completion_is_not_published_as_a_progress_topic(self):
        from process_briefs import pending,publish
        from registry import TaskRegistry
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            r=TaskRegistry(Path(tmp))
            try:
                ident=r.prepare('检查输入')['task']['id']
                r.bind(ident,'science')
                for event in ({'kind':'prompt','text':'检查输入'},{'kind':'status','status':'running'},
                              {'kind':'tool-end','tool':'bash','failed':True}):
                    r.native_event(ident,event)
                window=pending(r)[0]
                publish(r,ident,{'key':window['key'],'topic':'全部工况均已算完'})
                progress=r.snapshot(ident)['task']['progress']
                self.assertEqual(progress['summary'],'最近一次工具调用报错')
                self.assertEqual(progress['summaryOrigin'],'observed')
                self.assertEqual(pending(r),[])
            finally:r.close()

    def test_surface_cannot_be_replaced_by_manual_coordinates_or_text(self):
        marker=dict(type='boundaryProbe',id='outer',patch='outer',field='sigma_yy')
        validate_program({'annotations':[marker]})
        for override in ({'text':'"−158 MPa"'},{'position':['0','0','0']},{'patch':None}):
            with self.assertRaises(ValueError):validate_program({'annotations':[{**marker,**override}]})

    def test_receipts_win_over_both_history_and_model_outcomes(self):
        state={'reporting':{'total':6,'solved':6,'collected':6},
               'cases':[{'execution':{'status':'running'}}],
               'brief':{'status':'completed','topic':'全部工况均已算完'}}
        progress=process_progress({'status':'completed','processState':state})
        self.assertIn('回执仍为运行中',progress['summary'])
        self.assertNotIn('全部工况',progress['summary'])
        self.assertEqual(next(s['status'] for s in progress['stages'] if s['id']=='solve'),'active')
        meta={'presenter':{'state':'idle','operator':{'confirmed':True}},'uiState':{'revision':0,'errors':[{'id':'model','message':'场未加载'}]}}
        self.assertEqual(current_render_step(meta)['state'],'warning')
