"""Real file arrivals exercise observation, export, ownership, and imports."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry,atomic
from workspace_watch import WorkspaceWatcher,discover_cases

SOURCE=Path(__file__).resolve().parent/'fixtures/radial-52'

class WorkspaceWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.r=TaskRegistry(Path(self.temp.name)/'tasks');self.d=self.r.dashboard;self.d.stop.set();self.d.thread.join();self.d.watcher=WorkspaceWatcher(settle_seconds=0)
        task=self.r.prepare('监听多组模型');self.id=task['task']['id'];self.work=Path(task['workspace']);self.job=self.r._job(self.id)
        self.study={'schema':'mandifuel.study/v1','kind':'scan','parameters':[{'id':'x'}],'responses':[{'id':'temperature'}],'preview':{'fields':['T'],'time':'latest'},'runs':[{'id':'a','status':'queued','parameters':{'x':1},'responses':{},'caseRoot':'cases/a'},{'id':'b','status':'queued','parameters':{'x':2},'responses':{},'caseRoot':'cases/b'}]}
        (self.work/'delivery').mkdir();atomic(self.work/'delivery/study.json',self.study);atomic(self.work/'delivery/workbench.json',{'schema':'mandifuel.handoff/v1','study':'delivery/study.json'})
    def tearDown(self):self.r.close();self.temp.cleanup()
    def case(self,name):
        for part in ['0','system','constant']:shutil.copytree(SOURCE/part,self.work/'cases'/name/part)
    def test_ordinary_csv_is_discovered_as_a_renderable_table_without_ui_handoff(self):
        results=self.work/'results';results.mkdir();path=results/'power.csv'
        path.write_text('term,value_W\nsource,300.0\nouter,300.002\n');original=path.read_bytes()
        (results/'summary.json').write_text(json.dumps({'radial_sample_window':{'z_center_m':1.5,'note':'volume-weighted mean'}}))
        self.d.watch_files(self.id);self.d.watch_files(self.id)
        facts=self.d.inspect(self.id)
        table=next(row for row in facts['availableTables'] if row['file']=='results/power.csv')
        self.assertEqual(table['rows'],2);self.assertEqual(table['sample'][1]['value_W'],300.002)
        self.assertEqual(table['categories']['term'],['source','outer'])
        report=next(row for row in facts['availableReports'] if row['file']=='results/summary.json')
        self.assertEqual(report['metadata']['radial_sample_window']['note'],'volume-weighted mean')
        self.assertEqual(path.read_bytes(),original)
    def observe(self):
        self.r._import(self.job);self.d.watch_files(self.id);self.d.watch_files(self.id)
        return self.r.snapshot(self.id)['task']
    def test_each_bound_case_gets_a_mesh_then_saved_fields_without_main_agent_or_solver(self):
        self.case('a');raw=(self.work/'delivery/study.json').read_bytes();task=self.observe();a=self.r.study(self.id)['runs'][0];key=a['defaultView']
        self.assertTrue(task['modelReady']);self.assertEqual(self.r.fields(self.id,key)['kind'],'mesh');self.assertEqual(a['status'],'queued');self.assertEqual(raw,(self.work/'delivery/study.json').read_bytes());self.assertNotIn('defaultView',self.r.study(self.id)['runs'][1])
        self.study['runs'][0]['status']='running';atomic(self.work/'delivery/study.json',self.study);shutil.copytree(SOURCE/'1',self.work/'cases/a/1');atomic(self.work/'cases/a/.mandifuel-execution.json',{'status':'running'})
        task=self.observe();a=self.r.study(self.id)['runs'][0];self.assertEqual(a['status'],'running');self.assertEqual(a['responses'],{});self.assertEqual(a['defaultView'],key);self.assertEqual(max(self.r.fields(self.id,key)['frames'][0]['fields']['T']),1156.7)
        self.case('b');task=self.observe();b=self.r.study(self.id)['runs'][1];self.assertNotEqual(b['defaultView'],key);self.assertEqual(self.r.fields(self.id,b['defaultView'])['kind'],'mesh')
        paths=[f['path'] for f in self.r.snapshot(self.id)['inputs']];self.assertIn('cases/a/constant/solverDict',paths);self.assertIn('cases/b/constant/solverDict',paths)
        revision=self.job['meta']['workspaceWatch']['revision'];self.d.watch_files(self.id);self.assertEqual(self.job['meta']['workspaceWatch']['revision'],revision);self.assertEqual(self.job['meta']['events'],[])
    def test_failed_group_retains_diagnostics_and_never_acquires_result_or_response(self):
        self.case('a');self.study['runs'][0]['status']='failed';atomic(self.work/'delivery/study.json',self.study);atomic(self.work/'cases/a/.mandifuel-execution.json',{'status':'failed','exit_code':1});(self.work/'cases/a/log.offbeat').write_text('failed input')
        task=self.observe();self.assertFalse(task['modelReady']);self.assertEqual(self.r.study(self.id)['runs'][0]['responses'],{});self.assertIn('cases/a/log.offbeat',[f['path'] for f in self.r.snapshot(self.id)['files']])
    def test_missing_case_roots_are_bound_only_by_explicit_history_identity_and_result_root(self):
        self.case('a');self.study['runs'][0].pop('caseRoot');atomic(self.work/'delivery/study.json',self.study);atomic(self.work/'history.json',[{'point':{'id':'a'},'status':'running','result_root':str(self.work/'cases/a')}]);self.observe()
        run=self.r.study(self.id)['runs'][0];self.assertEqual(run['caseRoot'],'cases/a');self.assertTrue(run['viewIds'])
        # Similar directory names alone cannot establish an ownership binding.
        self.case('b');self.study['runs'][1].pop('caseRoot');atomic(self.work/'delivery/study.json',self.study);self.observe();self.assertEqual(self.r.study(self.id)['runs'][1]['viewIds'],[]);self.assertEqual(self.r.study(self.id)['runs'][0]['caseRoot'],'cases/a')
    def test_partial_json_coalesces_and_valid_report_wakes_once(self):
        self.observe();revision=self.job['meta']['workspaceWatch']['revision'];path=self.work/'measurements.json';path.write_text('{"columns":');self.observe();self.assertEqual(self.job['meta']['workspaceWatch']['revision'],revision)
        atomic(path,{'columns':[{'id':'x'}],'rows':[[1]]});self.observe();facts=self.d.inspect(self.id);self.assertGreater(facts['workspaceChanges']['revision'],revision);self.assertIn('measurements.json',[f['path'] for f in self.r.snapshot(self.id)['files']]);before=facts['dataRevision'];self.d.watch_files(self.id);self.assertEqual(self.d.inspect(self.id)['dataRevision'],before)
    def test_reference_cases_symlinks_and_unbound_directories_are_not_shared_models(self):
        self.case('a');shutil.copytree(self.work/'cases/a',self.work/'source-case');(self.work/'outside').symlink_to(SOURCE,target_is_directory=True)
        self.assertEqual([c['caseRoot'] for c in discover_cases(self.work)],['cases/a']);self.study['runs'][0].pop('caseRoot');atomic(self.work/'delivery/study.json',self.study);self.assertFalse(self.observe()['modelReady'])
    def test_ordinary_terminal_history_is_mapped_entirely_on_the_observation_side(self):
        (self.work/'delivery/study.json').unlink();(self.work/'delivery/workbench.json').unlink();self.case('a');shutil.copytree(SOURCE/'1',self.work/'cases/a/1')
        history=[{'point':{'id':'a','power':10000},'status':'completed','response':{'temperature':1156.7},'result_root':str(self.work/'cases/a')}]
        atomic(self.work/'history.json',history);self.observe();self.assertFalse(self.r.snapshot(self.id)['task']['study'])
        facts=self.d.inspect(self.id);self.assertEqual(facts['workspaceHistory'][0]['samples'][0]['point']['id'],'a')
        definition={'kind':'scan','parameters':[{'id':'power','unit':'W/m','source':'point.power'}],'responses':[{'id':'temperature','unit':'K','source':'response.temperature'}],'preview':{'fields':['T']}}
        self.d.publish(self.id,{'studyMapping':{'history':'history.json','study':definition}});self.observe()
        run=self.r.study(self.id)['runs'][0];self.assertEqual(run['responses']['temperature'],1156.7);self.assertTrue(run['viewIds']);self.assertFalse((self.work/'delivery/study.json').exists());self.assertEqual(json.loads((self.work/'history.json').read_text()),history)
        history.append({'point':{'id':'b','power':20000},'status':'queued'});atomic(self.work/'history.json',history);self.observe();self.assertEqual(len(self.r.study(self.id)['runs']),2);self.assertEqual(self.r.study(self.id)['runs'][1]['responses'],{})

    def test_presentation_child_exports_are_bound_to_one_explicit_run_and_seed_preview_fields(self):
        self.case('a');shutil.copytree(SOURCE/'1',self.work/'cases/a/1');self.study['runs'][0]['status']='completed';atomic(self.work/'delivery/study.json',self.study);self.observe()
        self.d.publish(self.id,{'exports':[{'id':'chosen-a','runId':'a','caseRoot':'cases/a','kind':'results','fields':['T']}]})
        run=self.r.study(self.id)['runs'][0];self.assertEqual(run['defaultView'],'chosen-a');self.assertEqual(run['preview']['fields'],['T']);self.assertEqual(self.r.study(self.id)['runs'][1]['viewIds'],[])
        with self.assertRaisesRegex(ValueError,'runId'):self.d.publish(self.id,{'exports':[{'id':'wrong','runId':'b','caseRoot':'cases/a','kind':'results','fields':['T']}]})

    def test_nested_reports_are_indexed_and_exposed_before_any_model_export(self):
        self.case('a');report=self.work/'results/result.json';report.parent.mkdir();atomic(report,{'totals':[{'name':'source','power':4.0},{'name':'boundary','power':3.99}]});original=report.read_bytes()
        self.d.watch_files(self.id,render=False)
        with patch('export_case.export_mesh',side_effect=AssertionError('inventory must not render')):
            self.d.watch_files(self.id,render=False)
        self.assertIn('results/result.json',[f['path'] for f in self.r.snapshot(self.id)['files']]);facts=self.d.inspect(self.id);records=next(row for row in facts['availableRecords'] if row['file']=='results/result.json');self.assertEqual(records['rowsPath'],'totals');self.assertEqual(records['count'],2);self.assertFalse(self.r.snapshot(self.id)['task']['modelReady']);self.assertEqual(report.read_bytes(),original)

    def test_a_fresh_terminal_task_needs_no_delivery_directory_or_ui_contract(self):
        task=self.r.prepare('普通终端任务');ident=task['task']['id'];work=Path(task['workspace']);self.assertFalse((work/'delivery').exists());(work/'results').mkdir();atomic(work/'results/result.json',{'quantities':[{'value':4.0}]})
        self.d.watch_files(ident,render=False);self.d.watch_files(ident,render=False)
        self.assertTrue((work/'delivery/workspace-observation.json').is_file());self.assertIn('results/result.json',[f['path'] for f in self.r.snapshot(ident)['files']]);self.assertGreater(self.r.snapshot(ident)['task']['workspaceRevision'],0)

    def test_a_failed_index_commit_is_retried_without_new_file_changes(self):
        self.case('a');self.d.watch_files(self.id,render=False)
        with patch.object(self.d.watcher,'reconcile',side_effect=OSError('temporary save')):
            with self.assertRaises(OSError):self.d.watch_files(self.id,render=False)
        self.assertNotIn(self.id,self.d.watcher.accepted);self.d.watch_files(self.id,render=False);self.assertTrue(self.job['meta'].get('workspaceWatch'))

    def test_stable_single_case_preview_survives_a_cold_cache_without_reexport(self):
        (self.work/'delivery/study.json').unlink();(self.work/'delivery/workbench.json').unlink();self.case('a');shutil.copytree(SOURCE/'1',self.work/'cases/a/1');self.job['meta']['status']='completed'
        self.d.preview(self.id);version=self.job['meta']['modelVersion'];self.d.previews.clear()
        with patch.object(self.d,'publish',side_effect=AssertionError('unchanged fields must not reexport')):self.d.preview(self.id)
        self.assertEqual(self.job['meta']['modelVersion'],version);self.assertEqual(len(self.r.fields(self.id,'live-results')['frames']),1)

if __name__=='__main__':unittest.main()
