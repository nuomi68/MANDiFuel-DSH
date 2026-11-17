import sys,time,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from artifact_queue import ArtifactQueue

class ArtifactQueueTests(unittest.TestCase):
    def test_a_slow_archive_does_not_block_a_new_task_and_repeated_saves_coalesce(self):
        entered=threading.Event();release=threading.Event();fast=threading.Event();counts={}
        def render(ident):
            counts[ident]=counts.get(ident,0)+1
            if ident=='archive':entered.set();release.wait(3)
            else:fast.set()
        q=ArtifactQueue(render,workers=2)
        try:
            q.submit('archive');self.assertTrue(entered.wait(1));q.submit('current',priority=True);self.assertTrue(fast.wait(1));self.assertIn('archive',q.snapshot()['active'])
            for _ in range(20):q.submit('archive')
            release.set();deadline=time.monotonic()+1
            while counts.get('archive',0)<2 and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(counts['archive'],2);self.assertEqual(counts['current'],1)
        finally:release.set();q.close()

    def test_export_failure_is_observable_and_does_not_stop_the_queue(self):
        done=threading.Event()
        def render(ident):
            if ident=='broken':raise ValueError('field is being saved')
            done.set()
        q=ArtifactQueue(render,workers=1)
        try:
            q.submit('broken');q.submit('valid');self.assertTrue(done.wait(1));self.assertEqual(q.snapshot()['errors']['broken'],'field is being saved')
        finally:q.close()
