import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registry import TaskRegistry

class ProcessMonitorTests(unittest.TestCase):
    def test_running_event_before_prompt_cannot_leave_progress_at_preparing(self):
        from process_monitor import process_event,process_progress
        meta={'status':'running'};process_event(meta,{'kind':'status','status':'running'});process_event(meta,{'kind':'prompt'});process_event(meta,{'kind':'tool','action':'正在提取结果'})
        self.assertNotIn('awaitingStart',meta['processState']);self.assertIn('提取',process_progress(meta)['summary'])
        meta['processState']['reporting']={'total':7,'solved':7,'collected':5,'failed':0};self.assertIn('5/7',process_progress(meta)['summary'])
        legacy={'status':'completed','promptRevision':1,'processState':{'awaitingStart':True,'summary':'正在准备新请求'}};self.assertIn('结束',process_progress(legacy)['summary'])
    def test_solver_log_updates_without_ui_agent_and_never_writes_case_files(self):
        with tempfile.TemporaryDirectory() as folder:
            r=TaskRegistry(Path(folder)/'tasks');r.process_monitor.close();r.dashboard.stop.set();r.dashboard.thread.join()
            try:
                p=r.prepare('求解进度');ident=p['task']['id'];work=Path(p['workspace']);case=work/'case';(case/'system').mkdir(parents=True);(case/'system/controlDict').write_text('FoamFile {}');(case/'constant/polyMesh').mkdir(parents=True)
                for name in ['points','faces','owner','neighbour','boundary']:(case/'constant/polyMesh'/name).write_text('mesh')
                (case/'.mandifuel-execution.json').write_text(json.dumps({'status':'running'}));log=case/'log.offbeat';log.write_text('Time = 0.1\nTime = 0.25\n')
                r.native_event(ident,{'kind':'status','status':'running'});r.process_monitor.scan(ident);self.assertIn('0.25',r.snapshot(ident)['task']['progress']['summary'])
                log.write_text(log.read_text()+'Time = 0.5\n');hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in case.rglob('*') if f.is_file()};r.process_monitor.scan(ident)
                self.assertIn('0.5',r.snapshot(ident)['task']['progress']['summary']);self.assertEqual(hashes,{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in case.rglob('*') if f.is_file()});self.assertNotIn('presenter',r._job(ident)['meta']);self.assertEqual(r._job(ident)['meta']['events'],[])
            finally:r.close()
