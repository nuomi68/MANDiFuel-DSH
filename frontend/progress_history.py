"""Persist exactly the progress snapshots shown below the task title."""
from datetime import datetime,timezone
import copy

def current_progress(meta):
    from process_monitor import process_progress
    if meta.get('draft'):return {'summary':'','stages':[],'source':'process-observer'}
    return process_progress(meta)

def record_progress(meta,*,timestamp=None,restored=False):
    snapshot=current_progress(meta)
    if not snapshot['summary']:return False
    rows=meta.setdefault('progressHistory',[])
    round_=meta.get('promptRevision',1)
    if rows and rows[-1].get('round')==round_ and all(rows[-1].get(key)==snapshot.get(key) for key in ('summary','stages','subprocesses')):return False
    row={'id':rows[-1]['id']+1 if rows else 1,'timestamp':timestamp or datetime.now(timezone.utc).isoformat(),'round':round_,**snapshot}
    if restored:row['restored']=True
    rows.append(row);return True

def execution_history(meta):
    science = meta.get('progressHistory',[])
    rows = [copy.deepcopy(row) for row in science if row.get('source')=='process-observer']
    complete = meta.get('progressHistoryComplete',False) and len(rows)==len(science)
    for step in meta.get('renderHistory',[]):
        rows.append(dict(source='ui-renderer', timestamp=step['timestamp'], summary=step['label'],
                         detail=step.get('detail',''), state=step['state']))
    rows.sort(key=lambda row:datetime.fromisoformat(row['timestamp']).timestamp())
    return {'rows':rows,'complete':complete}
