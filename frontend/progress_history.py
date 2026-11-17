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
    if rows and all(rows[-1].get(key)==snapshot.get(key) for key in ('summary','stages','subprocesses')):return False
    row={'id':rows[-1]['id']+1 if rows else 1,'timestamp':timestamp or datetime.now(timezone.utc).isoformat(),'round':meta.get('promptRevision',1),**snapshot}
    if restored:row['restored']=True
    rows.append(row);return True
