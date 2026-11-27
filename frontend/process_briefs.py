"""Bounded scientific conversation windows for the read-only LLM observer."""
import hashlib
import json
import re


def activity_topic(value):
    """The model describes an activity. Only the observer may assert its outcome."""
    if not isinstance(value, str):
        return ''
    topic = value.strip()
    if not 2 <= len(topic) <= 64 or re.search(r'[\r\n<>`。；！？]|已|完毕|完成|算完|结束|成功|均通过|全部通过|已收敛|未收敛|验证通过|核验通过|\d+\s*/\s*\d+', topic):
        return ''
    return topic if re.match(r'^(?:正在|准备)?(?:检查|核对|复核|核查|读取|提取|分析|评估|比较|对比|整理|梳理|查找|检索|定位|选择|建立|构建|生成|配置|设置|调整|计算|求解|执行|运行|启动|监测|跟踪|汇总|验证|绘制|换算|联动|绑定|处理|更新|导出|校验|诊断|查看|拟合|估算|推导|说明|解释|确认|尝试)', topic) else ''


def short_text(value, limit=180):
    text = re.sub(r'```[\s\S]*?(?:```|$)', ' ', str(value or ''))
    text = re.sub(r'(?i)(?:bearer\s+|(?:api[_-]?key|password|token|secret)\s*[:=]\s*)[^\s,;]+', '[已省略]', text)
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit-1] + '…'


def observe(meta, payload):
    state = meta['processState']
    kind = payload['kind']
    if kind == 'prompt':
        state['question'] = short_text(payload.get('text', '').split('用户请求：\n')[-1], 240)
        state['recent'] = []
    role, value = {
        'tool': ('tool-call', payload.get('action')),
        'assistant-note': ('assistant-statement', payload.get('text')),
        'tool-end': ('tool-error' if payload.get('failed') else 'tool-return',
                     payload.get('tool') or '工具返回'),
        'subprocess': ('child-event', ' '.join(str(payload.get(k) or '') for k in ('label','status','action'))),
    }.get(kind, ('', ''))
    if role and value:
        recent = state.setdefault('recent', [])
        event = {'kind':role, 'text':short_text(value)}
        if not recent or recent[-1] != event:
            recent.append(event)
            del recent[:-6]
            state['eventRevision']=state.get('eventRevision',0)+1
        if role=='tool-error':
            state.pop('brief',None)


def brief_input(meta):
    state = meta.get('processState', {})
    if 'recent' not in state or meta.get('draft') or not meta.get('nativeSessionId'):
        return None
    cases = state.get('cases', [])
    counts = {}
    for case in cases:
        status = case.get('execution', {}).get('status', 'unknown')
        counts[status] = counts.get(status, 0) + 1
    facts = {'cases':len(cases), 'meshes':sum(bool(c.get('meshReady')) for c in cases),
             'savedFields':sum(bool(c.get('savedFields')) for c in cases),
             'receipts':counts, 'study':dict(state.get('reporting', {}))}
    status = meta['status']
    if state.get('awaitingStart') and state.get('awaitingStartRound') == meta.get('promptRevision', 0):
        status = 'queued'
    window = {'round':meta.get('promptRevision', 0), 'status':status, 'request':state.get('question', ''),
              'recent':list(state['recent']), 'workspace':facts}
    digest = hashlib.sha256(json.dumps([state.get('eventRevision',0),window], sort_keys=True).encode()).hexdigest()
    return {'id':meta['id'], 'sessionId':meta['nativeSessionId'], 'key':digest, 'window':window}


def pending(registry):
    with registry.lock:
        ready = []
        for job in registry.jobs.values():
            meta = job['meta']
            item = brief_input(meta)
            if item and meta['processState'].get('brief', {}).get('key') != item['key']:
                ready.append(item)
        return ready


def publish(registry, ident, data):
    from process_monitor import process_progress
    with registry.lock:
        job = registry._job(ident)
        meta = job['meta']
        item = brief_input(meta)
        if not item or item['key'] != data.get('key'):
            return {'accepted':False}
        topic = data.get('topic')
        if not isinstance(topic, str) or not 2 <= len(topic.strip()) <= 64 or re.search(r'[\r\n<>\x60]', topic):
            raise ValueError('无效的流程摘要')
        state = meta['processState']
        if state.get('brief', {}).get('key') == item['key']:
            return {'accepted':False}
        # Record an empty topic for an unsupported assertion so the same window
        # is not repeatedly sent to the provider. The facts remain visible.
        state['brief'] = {'key':item['key'], 'status':item['window']['status'], 'topic':activity_topic(topic)}
        meta['processProgress'] = process_progress(meta)
        registry._save(job)
        registry._emit(job, 'state', registry.public(job))
        return {'accepted':True}
