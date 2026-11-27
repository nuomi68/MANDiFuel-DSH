"""Generate and evolve a persistent application without starting an agent."""
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

from mandifuel_run.case import RECEIPT, inspect_case, locked, run_case, save_json
from .thermal_rod import REPO, INPUTS, PARAMETERS, bind, check_template, digest, extract, has_heat_flow, numeric

from .definition import validate, views


def read(path):
    return json.loads(path.read_text())


def now():
    return datetime.now(timezone.utc).isoformat()


def copy_input(source, dest, names):
    for name in names:
        src = source / name
        if src.resolve() != source.resolve()/name or not src.is_file():
            raise ValueError(f'原始证据缺失或引用无效 {name}')
        out = dest/name
        out.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(src, out)


class Application:
    def __init__(self, workspace, case, storage):
        workspace = Path(workspace).resolve()
        self.workspace = workspace
        self.case = (workspace/case).resolve()
        if not self.case.is_relative_to(workspace):
            raise ValueError('算例必须位于当前任务工作区')
        self.relative = str(self.case.relative_to(workspace))
        key = hashlib.sha256(self.relative.encode()).hexdigest()[:24]
        self.root = Path(storage)/key
        self.spec = self.root/'app_spec.json'

    def availability(self):
        if self.spec.exists():
            return dict(available=True, generated=True)
        try:
            self._source()
        except (ValueError, OSError) as error:
            return dict(available=False, reason=str(error))
        return dict(available=True, generated=False)

    def capabilities(self):
        checked = self._source()
        bindings = {k: {'unit': PARAMETERS[k][1], 'value': v, 'targets': PARAMETERS[k][2]}
                    for k, v in bind(self.case).items()}
        outputs = dict(field='T', regions=['fuel','cladding'], kinds=['field','profile','statistic'], reductions=['min','max'])
        if has_heat_flow(self.case, checked['final_time']):
            outputs['kinds'].append('heatFlow')
            outputs['heatFlow'] = '全周四项功率（W），定义只含 id、label、kind；表列 quantity、direction、method、value'
        return dict(available=True, generated=False, bindings=bindings, outputCapabilities=outputs)

    def _source(self):
        check_template(self.case)
        receipt = read(self.case/RECEIPT)
        checked = inspect_case(self.case)
        if (receipt.get('status')!='completed' or checked['status']!='completed'
                or checked['exit_code'] != 0 or not checked['terminal_marker']):
            raise ValueError('生成计算器需要成功的原始求解回执和终态场')
        return checked

    def create(self, proposal):
        self.root.parent.mkdir(exist_ok=True, parents=True)
        with locked(self.root.with_suffix('.lock')):
            if self.spec.exists():
                current = read(self.spec)
                requested = validate(proposal,check_template(self.root/'template'),heat_flow='heatFlows' in self.artifact('baseline','result'))
                if any(current.get(k)!=v for k,v in requested.items()):
                    raise ValueError('该算例已有应用，请用当前版本演化')
                return self.state()
            checked = self._source()
            with tempfile.TemporaryDirectory(dir=self.root.parent) as tmp:
                stage = Path(tmp)/'app'
                template = stage/'template'
                copy_input(self.case, template, INPUTS)
                inputs = check_template(template)
                end = checked['final_time']
                with_heat=has_heat_flow(self.case,end)
                archived_inputs=(*INPUTS,'rodDict') if with_heat else INPUTS
                if with_heat:copy_input(self.case,template,['rodDict'])
                definition = validate(proposal,inputs,heat_flow=with_heat)
                original = stage/'runs'/'baseline'
                archive = original/'case'
                fields=[end+'/T']
                if with_heat:fields.append(end+'/Q')
                copy_input(self.case, archive, (*archived_inputs, RECEIPT, 'log.offbeat', *fields))
                if check_template(archive) != inputs or any(digest(template/f)!=digest(archive/f) for f in archived_inputs):
                    raise ValueError('归档期间算例输入发生变化，请重试')
                if inspect_case(archive)['status']!='completed':
                    raise ValueError('归档后的终点证据不完整')
                result = extract(archive, original, end, inputs)
                spec = dict(schema='mandifuel.app/v1', appId=self.root.name, version=1,
                            solver='OFFBEAT', adapter='steady-thermal-rod/v1', baseCase=self.relative,
                            templateSha256={f:digest(template/f) for f in archived_inputs},
                            workflow=['prepare','readback','solve','extract','verify'], **definition)
                (stage/'versions').mkdir()
                save_json(stage/'versions/1.json', spec)
                save_json(stage/'app_spec.json', spec)
                save_json(original/'record.json', dict(id='baseline', version=1, createdAt=now(),
                          status='completed', inputs=inputs, peak=result['fuelMaxTemperature']))
                os.rename(stage, self.root)
        return self.state()

    def evolve(self, version, *, proposal=None, components=None):
        with locked(self.root/'spec.lock'):
            spec = read(self.spec)
            self._version(spec, version)
            if proposal is not None:
                updated = validate(proposal,check_template(self.root/'template'),heat_flow='heatFlows' in self.artifact('baseline','result'))
                old = {p['id']:p['binding'] for p in spec['parameters']}
                if any(p['id'] in old and p['binding']!=old[p['id']] for p in updated['parameters']):
                    raise ValueError('已存在的参数标识不能改绑其他物理输入')
                spec.update(updated)
            elif components is not None:
                spec['components'] = views(components,spec['outputs'],spec['parameters'])
            else:
                raise ValueError('请提交新的应用定义或显示组件')
            if spec != read(self.spec):
                spec['version'] += 1
                save_json(self.root/'versions'/f"{spec['version']}.json", spec)
                save_json(self.spec, spec)
        return self.state()

    @staticmethod
    def _version(spec, version):
        if type(version) is not int or version != spec['version']:
            raise ValueError('应用版本已变化，请重新读取参数契约')

    def state(self):
        records = []
        for path in (self.root/'runs').glob('*/record.json'):
            record = read(path)
            if record['status']=='running':
                with (path.parent/'worker.lock').open('a') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        record = read(path)
                        if record['status']=='running':
                            record.update(status='interrupted', error='上次执行中断，未发布结果')
                            save_json(path,record)
            records.append(record)
        return dict(spec=read(self.spec), runs=sorted(records,key=lambda r:r['createdAt']))

    def candidate(self, case_root, spec=None):
        if not isinstance(case_root,str) or not case_root or Path(case_root).is_absolute() or '..' in Path(case_root).parts:
            raise ValueError('候选需要当前工作区中的相对算例目录')
        source = (self.workspace/case_root).resolve()
        if not source.is_relative_to(self.workspace):
            raise ValueError('候选必须位于当前任务工作区')
        spec = spec if spec is not None else read(self.spec)
        # Read a single snapshot. Both physical validation and the draft use those same bytes.
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp)
            copy_input(source, snapshot, spec['templateSha256'])
            inputs = check_template(snapshot)
            base = check_template(self.root/'template')
            if any(digest(snapshot/name)!=signature for name,signature in spec['templateSha256'].items()
                   if name not in {'0/T','constant/solverDict'}):
                raise ValueError('候选网格或固定输入与本应用不同')
        bindings = {p['binding'] for p in spec['parameters']}
        if any(inputs[k]!=base[k] for k in inputs if k not in bindings):
            raise ValueError('候选改变了当前契约未开放的物理参数')
        return dict(appId=spec['appId'],version=spec['version'],caseRoot=str(source.relative_to(self.workspace)),
                    values={p['id']:inputs[p['binding']] for p in spec['parameters']})

    def run(self, version, request_id, values, candidate=None):
        if not isinstance(request_id,str) or not re.fullmatch('[a-f0-9]{32}',request_id):
            raise ValueError('缺少合法的运行请求标识')
        folder = self.root/'runs'/request_id
        with ExitStack() as stack:
            with locked(self.root/'spec.lock'):
                if (folder/'record.json').is_file():
                    existing = read(folder/'record.json')
                    if version!=existing['version'] or values!=existing.get('requested') or candidate!=existing.get('candidate'):
                        raise ValueError('运行请求标识已用于其他输入')
                    return existing
                spec = read(self.spec)
                self._version(spec,version)
                if not isinstance(values,dict) or set(values)!={p['id'] for p in spec['parameters']}:
                    raise ValueError('输入必须与当前版本的参数契约一致')
                changes = {p['binding']:numeric(values[p['id']],p['binding']) for p in spec['parameters']}
                if candidate is not None and self.candidate(candidate,spec)['values']!=values:
                    raise ValueError('提交值与候选输入卡不一致，请重新载入候选或使用自定义工况')
                folder.mkdir(exist_ok=True)
                stack.enter_context(locked(folder/'worker.lock'))
                case = folder/'case'
                record = dict(id=request_id, version=version, createdAt=now(), status='running', requested=values)
                if candidate is not None:
                    record['candidate'] = candidate
                save_json(folder/'record.json', record)
            try:
                copy_input(self.root/'template', case, spec['templateSha256'])
                if any(digest(case/f)!=h for f,h in spec['templateSha256'].items()):
                    raise ValueError('归档输入签名已变化')
                bind(case, changes)
                inputs = check_template(case)
                if any(inputs[k]!=v for k,v in changes.items()):
                    raise ValueError('参数回读与请求不一致')
                record['inputs'] = inputs
                save_json(folder/'readback.json', dict(inputs=inputs, sha256={f:digest(case/f) for f in INPUTS}))
                # The sandbox keeps its temporary directory beside the case, outside OpenFOAM's time folders.
                script = ('export MANDIFUEL_PLUGIN_ROOT="$1"; source "$1/configs/launcher.env" && source "$MANDIFUEL_OPENFOAM_BASHRC" '
                          '&& exec "$MANDIFUEL_OFFBEAT_BIN/offbeat" > log.offbeat 2>&1')
                cmd = [sys.executable, str(REPO/'dsh/offline-exec.py'), '--project-root', str(folder.resolve()),
                       '--', 'bash','-c',script,'mandifuel-app',str(REPO)]
                receipt = run_case(case, command=cmd, timeout=180)
                if receipt['status']!='completed' or receipt['exit_code']!=0:
                    raise ValueError('OFFBEAT 未正常到达终点，请查看执行回执与日志')
                result = extract(case, folder, receipt['final_time'], inputs)
                if any(o['kind']=='heatFlow' for o in spec['outputs']) and 'heatFlows' not in result:
                    raise ValueError('本次运行缺少热流表所需的终态场')
                record.update(status='completed', peak=result['fuelMaxTemperature'])
            except Exception as error:
                record.update(status='failed', error=str(error))
            record['finishedAt'] = now()
            save_json(folder/'record.json', record)
        return record

    def artifact(self, run_id, name):
        if not isinstance(run_id,str) or not re.fullmatch('baseline|[a-f0-9]{32}',run_id):
            raise ValueError('运行标识无效')
        folder = self.root/'runs'/run_id
        record = read(folder/'record.json')
        if name=='receipt':
            return read(folder/'case'/RECEIPT)
        if name=='readback':
            return read(folder/'readback.json') if run_id!='baseline' else dict(inputs=record['inputs'], origin='archived-inputs')
        if name=='log':
            logs = [folder/'case'/n for n in ('log.offbeat','log.mandifuel-runner')]
            return {p.name:p.read_text(errors='replace')[-64000:] for p in logs if p.is_file()}
        if record['status']!='completed':
            raise ValueError('本次运行没有可发布的结果')
        if name in ('result','field'):
            return read(folder/(name+'.json'))
        if name=='raw':
            result = read(folder/'result.json')
            path = folder/'case'/result['fieldFile']
            if digest(path)!=result['fieldSha256']:
                raise ValueError('归档终态场的哈希已变化')
            return dict(file=result['fieldFile'], sha256=result['fieldSha256'], content=path.read_text())
        raise ValueError('未注册的证据类型')

    def table(self, output, ids):
        spec=read(self.spec)
        item=next((o for o in spec['outputs'] if o['id']==output),None)
        if not item or item['kind']=='field':raise ValueError('未定义的表数据输出')
        if len(ids)>256:raise ValueError('单次最多读取 256 个工况')
        records={r['id']:(i,r) for i,r in enumerate(self.state()['runs'])}
        columns=[dict(id='case',label='工况'),*[{k:p[k] for k in ('id','label','unit')} for p in spec['parameters']]]
        profile=item['kind']=='profile'
        if profile:columns.append(dict(id='radius',label='半径',unit='m'))
        if item['kind']=='heatFlow':columns.extend([dict(id='quantity',label='热量项目'),dict(id='direction',label='正方向'),dict(id='method',label='取值方法')])
        columns.append(dict(id='value',label=item['label'],unit=item['unit']))
        rows=[]
        for ident in ids:
            if ident not in records:raise ValueError('应用工况不存在')
            i,r=records[ident]
            source=self.artifact(ident,'result')
            base={'case':'原始工况' if ident=='baseline' else f'复算 {i}', 'runId':'app:'+ident,
                  **{p['id']:r['inputs'][p['binding']] for p in spec['parameters']}}
            if item['kind']=='heatFlow':
                rows.extend(dict(base,**p) for p in source['heatFlows'])
                continue
            samples=[p for p in source['profile'] if p['region']==item['region']]
            if profile:rows.extend(dict(base,radius=p['radius'],value=p['T']) for p in samples)
            else:
                reduce=min if item['reduction']=='min' else max
                rows.append(dict(base,value=reduce(p['T'] for p in samples)))
        return dict(columns=columns,rows=rows)
