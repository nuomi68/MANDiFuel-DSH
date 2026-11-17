"""Bounded per-task rendering; file discovery never waits for mesh exports."""
from collections import deque
import threading
import time


class ArtifactQueue:
    def __init__(self,render,workers=2):
        self.render=render;self.condition=threading.Condition();self.pending=deque();self.queued=set();self.active=set();self.again=set();self.closed=False;self.errors={};self.started={}
        self.threads=[threading.Thread(target=self._run,name=f'presentation-artifacts-{i}',daemon=True) for i in range(workers)]
        for thread in self.threads:thread.start()

    def submit(self,ident,priority=False):
        with self.condition:
            if self.closed:return
            if ident in self.active:self.again.add(ident);return
            if ident in self.queued:return
            (self.pending.appendleft if priority else self.pending.append)(ident);self.queued.add(ident);self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or self.pending)
                if self.closed:return
                ident=self.pending.popleft();self.queued.remove(ident);self.active.add(ident);self.started[ident]=time.monotonic()
            try:
                self.render(ident)
                with self.condition:self.errors.pop(ident,None)
            except Exception as error:
                with self.condition:self.errors[ident]=str(error)[:500]
            finally:
                with self.condition:
                    self.active.discard(ident);self.started.pop(ident,None)
                    if ident in self.again:
                        self.again.remove(ident)
                        if not self.closed:self.pending.append(ident);self.queued.add(ident);self.condition.notify()

    def snapshot(self):
        with self.condition:return {'active':sorted(self.active),'pending':list(self.pending),'errors':dict(self.errors),'elapsed':{key:round(time.monotonic()-start,1) for key,start in self.started.items()}}

    def close(self):
        with self.condition:self.closed=True;self.pending.clear();self.queued.clear();self.condition.notify_all()
        for thread in self.threads:thread.join(timeout=.1)
